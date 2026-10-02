"""Team mode on this machine: the mirror of the team's claims, and the edit check the guard calls.

The guard never waits on the chain in the common case. `knos mirror` (one background process per team, started
lazily, gone after 30 idle minutes) copies the credential's live claims into a local table every 3 seconds. The
check reads that table. Only when the mirror is older than 5 seconds does it make one direct read, with a 1 second
budget; if that fails too, the edit goes ahead in local-only mode with a one-line warning. An RPC outage never
blocks work.

The rules:
  - an edit to unit U is allowed if this agent holds a confirmed winning claim covering U;
  - otherwise it is refused if any live claim of another holder overlaps U, winner or pending;
  - otherwise the guard places a claim and waits up to 5 s for the verdict: won -> allowed, lost -> refused,
    timeout or RPC failure -> allowed in local-only mode with the warning.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from . import config, protocol, registry, units

def _env_s(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


POLL_S = 3.0
FRESH_S = 5.0
DIRECT_READ_S = _env_s("KNOS_TEAM_READ_S", 1.0)  # tests on a loaded machine raise these; the product never does
VERDICT_S = _env_s("KNOS_TEAM_VERDICT_S", 5.0)
IDLE_EXIT_S = 30 * 60

HOST_NAMES = {"claude": "claude-code", "codex": "codex", "cursor": "cursor", "opencode": "opencode",
              "copilot": "copilot", "terminal": "cli", "sdk": "sdk"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (address TEXT PRIMARY KEY, unit_hash BLOB, ancestors BLOB, holder BLOB,
  signer TEXT, lease_until INTEGER, kind INTEGER, since INTEGER);
CREATE TABLE IF NOT EXISTS mine (address TEXT PRIMARY KEY, unit TEXT, host TEXT, session TEXT, verdict TEXT,
  slot INTEGER, lease_until INTEGER, at REAL);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS events (ts REAL, kind TEXT, detail TEXT);
"""


@dataclass
class Decision:
    allow: bool
    reason: str = ""
    warning: str = ""


@dataclass
class Runtime:
    repo: Path
    tf: config.TeamFile
    key: Keypair
    salt: bytes
    machine: str

    @property
    def team(self) -> protocol.Team:
        return config.protocol_team(self.tf, self.salt)

    def holder(self, host: str, session: str) -> protocol.Holder:
        return protocol.Holder(self.key, HOST_NAMES.get(host, host), self.machine, session)

    @property
    def dir(self) -> Path:
        d = config.root() / str(self.tf.credential)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.dir / "mirror.db"), timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout = 5000")
        # A cache of the chain: rebuilt by the next sync if lost, so it never waits on the disk (an fsync on a slow
        # disk can take a second, and this sits in front of every edit).
        conn.execute("PRAGMA synchronous = OFF")
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass
        conn.executescript(_SCHEMA)
        return conn


def runtime(repo: Path, fetch_salt: bool = True) -> Runtime | None:
    """Team mode for `repo`, or None when there is no `.knos/team.json` or this machine is not set up for it."""
    tf = config.load(repo)
    if tf is None:
        return None
    key = config.member_key()
    if key is None:
        return None
    salt = config.salt(tf, key, fetch=fetch_salt)
    if not salt:
        return None
    return Runtime(Path(repo), tf, key, salt, config.machine_id())


# ---- the mirror -----------------------------------------------------------------------------------------------------

def _meta(conn: sqlite3.Connection, k: str, default: str = "") -> str:
    row = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return row[0] if row else default


def _set(conn: sqlite3.Connection, k: str, v) -> None:
    conn.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def sync(rt: Runtime, timeout: float = 5.0) -> int:
    """Copy every live claim into the mirror; returns how many."""
    slot, live = protocol.read_live(rt.team, timeout=timeout)
    now_chain = protocol.chain_time(rt.tf.url, timeout)
    conn = rt.db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM claims")
        conn.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)", [_row(c) for c in live])
        _set(conn, "synced_at", time.time())
        _set(conn, "chain_time", now_chain)
        _set(conn, "chain_offset", now_chain - time.time())
        _set(conn, "slot", slot)
        conn.execute("COMMIT")
    finally:
        conn.close()
    return len(live)


def _row(c: protocol.LiveClaim) -> tuple:
    """A claim as the mirror keeps it; `since` is when it was placed (its first lease end minus the lease)."""
    return (str(c.address), c.data.unit_hash, c.data.ancestors, c.data.holder, str(c.signer), c.lease_until,
            c.data.kind, c.data.lease_until - protocol.LEASE_S)


def _mirror_age(conn: sqlite3.Connection) -> float:
    try:
        return time.time() - float(_meta(conn, "synced_at", "0"))
    except ValueError:
        return 1e9


def mirror_status(repo: Path) -> tuple[float | None, bool]:
    """How old the local mirror is in seconds (or None if never synced), and whether `knos mirror` is running."""
    tf = config.load(repo)
    if tf is None:
        return None, False
    d = config.root() / str(tf.credential)
    running = False
    lock = d / "mirror.pid"
    try:
        pid = int(lock.read_text().strip())
        running = _alive(pid)
    except (OSError, ValueError):
        running = False
    db_file = d / "mirror.db"
    if not db_file.exists():
        return None, running
    try:
        conn = sqlite3.connect(str(db_file), timeout=1)
        try:
            raw = _meta(conn, "synced_at", "")
            if not raw:
                return None, running
            age = max(0.0, time.time() - float(raw))
            return age, running
        finally:
            conn.close()
    except Exception:
        return None, running


def _chain_now(conn: sqlite3.Connection) -> int:
    try:
        return int(time.time() + float(_meta(conn, "chain_offset", "0")))
    except ValueError:
        return int(time.time())


def ensure_mirror(rt: Runtime) -> None:
    """Start `knos mirror` for this repo in the background if it is not already running. Never raises."""
    if os.environ.get("KNOS_NO_MIRROR"):
        return
    lock = rt.dir / "mirror.pid"
    try:
        pid = int(lock.read_text().strip())
        if _alive(pid):
            return
    except (OSError, ValueError):
        pass
    try:
        kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                        "cwd": str(rt.repo)}
        if os.name == "nt":
            kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([sys.executable, "-m", "knos.team.live", str(rt.repo)], **kwargs)
    except OSError:
        pass


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run_mirror(repo: Path, once: bool = False) -> int:
    """The single-instance background loop: sync every 3 s, renew this machine's winning claims at half their
    lease, sweep long-expired claims now and then, exit after 30 idle minutes."""
    rt = runtime(repo)
    if rt is None:
        return 1
    lock = rt.dir / "mirror.pid"
    try:
        fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            if _alive(int(lock.read_text().strip())):
                return 0
        except (OSError, ValueError):
            pass
        lock.unlink(missing_ok=True)
        fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    last_sweep = 0.0
    try:
        while True:
            try:
                sync(rt)
                renew_due(rt)
                if time.time() - last_sweep > 300:
                    protocol.sweep(rt.team, rt.key)
                    write_records(rt)
                    last_sweep = time.time()
            except Exception:  # noqa: BLE001 - offline: keep the last good mirror and try again
                pass
            if once:
                return 0
            conn = rt.db()
            try:
                used = float(_meta(conn, "used_at", str(time.time())))
            finally:
                conn.close()
            if time.time() - used > IDLE_EXIT_S:
                return 0
            time.sleep(POLL_S)
    finally:
        lock.unlink(missing_ok=True)


def renew_due(rt: Runtime) -> None:
    conn = rt.db()
    try:
        rows = conn.execute("SELECT address, host, session, lease_until FROM mine WHERE verdict IN ('won','held')"
                            ).fetchall()
        now = _chain_now(conn)
    finally:
        conn.close()
    for address, host, session, lease_until in rows:
        if lease_until - now > protocol.LEASE_S / 2:
            continue
        try:
            new = protocol.renew(rt.team, protocol.Holder(rt.key, host, rt.machine, session),
                                 Pubkey.from_string(address))
        except LookupError:  # gone without a release from here: swept after it lapsed
            _forget(rt, address)
            _event(rt, "lapsed", {"claim": address,
                                  "holder": protocol.Holder(rt.key, host, rt.machine, session).hash(rt.salt).hex()})
            continue
        except Exception:  # noqa: BLE001
            continue
        conn = rt.db()
        try:
            conn.execute("UPDATE mine SET lease_until=? WHERE address=?", (new, address))
        finally:
            conn.close()


def _forget(rt: Runtime, address: str) -> None:
    conn = rt.db()
    try:
        conn.execute("DELETE FROM mine WHERE address=?", (address,))
    finally:
        conn.close()


# ---- the check ------------------------------------------------------------------------------------------------------

def _names(rt: Runtime) -> dict[str, str]:
    p = rt.dir / "members.json"
    try:
        if time.time() - p.stat().st_mtime < 600:
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        got = registry.names(rt.tf.url, rt.tf.credential, rt.salt, timeout=DIRECT_READ_S + 2)
        p.write_text(json.dumps(got), encoding="utf-8")
        return got
    except Exception:  # noqa: BLE001
        return {}


def who(rt: Runtime, signer: str, holder: bytes) -> str:
    name = _names(rt).get(signer) or signer[:6]
    return f"{name}/{units.holder_host(rt.salt, holder)}"


def refusal(rt: Runtime, rel: str, signer: str, holder: bytes, since: int | None) -> str:
    when = datetime.fromtimestamp(since).strftime("%H:%M") if since else "earlier"
    return f"{rel} is claimed by {who(rt, signer, holder)} since {when} (Knos). Ask them, or take other work."


def edit_rule(rows, me: bytes, uh: bytes, anc: bytes, now: int, verdicts: dict[str, str]) -> tuple[str, tuple | None]:
    """The guard's rule over the live claims, pure so the property test can hold it to account.

    rows: (address, unit_hash, ancestors, holder_hash, signer, lease_until) of every claim on chain.
    Returns ("allow", None) if this holder has a confirmed winning claim covering the unit; ("refuse", row) if any
    live claim of another holder overlaps it, winner or pending; else ("claim", None): place one and decide."""
    others = []
    for row in rows:
        address, h, a, hold, lease = row[0], row[1], row[2], row[3], row[5]
        if lease <= now:
            continue
        if hold == me:
            # a claim of mine covers the unit if it is the unit itself or one of its ancestor directories
            if (h == uh or any(anc[i:i + 8] == h[:8] for i in range(0, len(anc), 8))) and                     verdicts.get(address) in ("won", "held"):
                return "allow", None
            continue
        if units.overlaps(h, a, uh, anc):
            others.append(row)
    if others:
        return "refuse", others[0]
    return "claim", None


def check(rt: Runtime, rel: str, host: str, session: str, verdict_s: float = VERDICT_S) -> Decision:
    unit = units.unit(rel)
    if not unit:
        return Decision(True)
    uh = units.unit_hash(rt.salt, rt.tf.repo_id, unit)
    anc = units.ancestors(rt.salt, rt.tf.repo_id, unit)
    holder = rt.holder(host, session)
    me = holder.hash(rt.salt)
    conn = rt.db()
    try:
        _set(conn, "used_at", time.time())
        stale = _mirror_age(conn) > FRESH_S
    finally:
        conn.close()
    ensure_mirror(rt)
    conn = rt.db()
    try:
        now = _chain_now(conn)
        rows = conn.execute("SELECT address, unit_hash, ancestors, holder, signer, lease_until, kind, since "
                            "FROM claims").fetchall()
        mine = {r[0]: r[1] for r in conn.execute("SELECT address, verdict FROM mine")}
    finally:
        conn.close()
    if stale:
        # The mirror is behind: read just the claims that can overlap this file (its own and its folders'), one
        # getMultipleAccounts within the budget. Failing that, local-only with the warning; never block on the RPC.
        try:
            _, near = protocol.read_units(rt.team, unit, timeout=DIRECT_READ_S)
        except Exception:  # noqa: BLE001
            return Decision(True, warning="team registry unreachable: working in local-only mode (Knos)")
        rows = [_row(c) for c in near]
    what, other = edit_rule(rows, me, uh, anc, now, mine)
    if what == "allow":
        return Decision(True)
    if what == "refuse":
        address, hold, signer = other[0], other[3], other[4]
        since = other[7] if len(other) > 7 else None
        _event(rt, "blocked", {"by": HOST_NAMES.get(host, host), "claim": address, "holder": me.hex()})
        return Decision(False, refusal(rt, rel, signer, hold, since))
    v = protocol.claim(rt.team, holder, unit, within=verdict_s)
    if v.outcome in ("won", "held"):
        _remember(rt, v, unit, holder)
        return Decision(True)
    if v.outcome == "lost" and v.lost_to is not None:
        _event(rt, "lost", {"claim": str(v.address), "holder": me.hex()})
        return Decision(False, refusal(rt, rel, str(v.lost_to.signer), v.lost_to.data.holder,
                                       v.lost_to.data.lease_until - protocol.LEASE_S))
    if v.outcome == "stale":
        return Decision(True, warning=f"{rel}: its previous claim lapsed without release; editing (Knos)")
    return Decision(True, warning="team registry unreachable: working in local-only mode (Knos)")


def _remember(rt: Runtime, v: protocol.Verdict, unit: str, holder: protocol.Holder) -> None:
    conn = rt.db()
    try:
        lease = _chain_now(conn) + protocol.LEASE_S
        conn.execute("INSERT INTO mine VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(address) DO UPDATE SET "
                     "verdict=excluded.verdict, slot=excluded.slot, at=excluded.at",
                     (str(v.address), unit, holder.host, holder.session, v.outcome, v.slot or 0, lease, time.time()))
        _set(conn, "synced_at", 0)  # the next check re-reads, so the new claim is in the mirror
    finally:
        conn.close()
    _event(rt, "claim", {"unit_hash": units.unit_hash(rt.salt, rt.tf.repo_id, unit).hex(), "claim": str(v.address),
                         "holder": holder.hash(rt.salt).hex()})


def _event(rt: Runtime, kind: str, detail: dict) -> None:
    try:
        conn = rt.db()
        try:
            conn.execute("INSERT INTO events VALUES (?,?,?)", (time.time(), kind, json.dumps(detail)))
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def claim_units(rt: Runtime, globs: list[str], host: str, session: str,
                verdict_s: float = VERDICT_S) -> list[tuple[str, protocol.Verdict]]:
    """An explicit claim (`knos claim`, the MCP `remember(claiming=true)` through `explicit`, and the SDK): one chain
    claim per glob, directory globs as directory units."""
    out = []
    holder = rt.holder(host, session)
    for g in globs:
        unit = units.unit(_unit_of_glob(g))
        if not unit:
            continue
        v = protocol.claim(rt.team, holder, unit, kind=units.DIR if unit.endswith("/") else units.FILE,
                           within=verdict_s)
        if v.outcome in ("won", "held"):
            _remember(rt, v, unit, holder)
        out.append((g, v))
    return out


def _unit_of_glob(g: str) -> str:
    """A glob as the unit it covers: a literal path as itself, anything with a wildcard as its literal directory."""
    import re
    m = re.search(r"[*?\[]", g)
    if not m:
        return g
    head = g[: m.start()]
    return (head[: head.rfind("/") + 1] if "/" in head else "") or "./"


def release_all(rt: Runtime, host: str, session: str) -> int:
    """Release this agent's chain claims (on `knos done`)."""
    holder = rt.holder(host, session)
    conn = rt.db()
    try:
        rows = conn.execute("SELECT address FROM mine WHERE host=? AND session=?",
                            (holder.host, holder.session)).fetchall()
    finally:
        conn.close()
    n = 0
    for (address,) in rows:
        try:
            if protocol.release(rt.team, holder, Pubkey.from_string(address)):
                n += 1
        except Exception:  # noqa: BLE001 - it lapses at its lease
            continue
        _forget(rt, address)
        _event(rt, "release", {"claim": address, "holder": holder.hash(rt.salt).hex()})
    return n



def events(rt: Runtime, since: float = 0.0) -> list[dict]:
    conn = rt.db()
    try:
        rows = conn.execute("SELECT ts, kind, detail FROM events WHERE ts >= ? ORDER BY ts", (since,)).fetchall()
    finally:
        conn.close()
    return [{"ts": ts, "kind": kind, **json.loads(detail)} for ts, kind, detail in rows]


def journal_for(rt: Runtime, holder: bytes, start: int, length: int = 86_400) -> list[dict]:
    """This agent host's new Sibyl journal entries in the period (what its record anchors), from this repo's store."""
    from datetime import datetime, timezone

    from ..memory import Memory, _flatten
    host = units.holder_host(rt.salt, holder)
    label = {v: k for k, v in HOST_NAMES.items()}.get(host, host)
    lo = datetime.fromtimestamp(start, timezone.utc).isoformat()
    hi = datetime.fromtimestamp(start + length, timezone.utc).isoformat()
    try:
        with Memory(rt.repo) as mem:
            rows = mem.journal(limit=5000)
    except Exception:  # noqa: BLE001 - no store here: nothing to anchor
        return []
    out = []
    for e in rows:
        ts = str(e.get("ts") or "")
        f = _flatten(e)
        if lo <= ts < hi and str(f.get("where", "")).startswith(label + "/"):
            out.append({"id": e.get("id"), "ts": ts, "text": f.get("text", "")})
    return out


def period_of(rt: Runtime, holder: bytes, start: int, journal: list[dict] | None = None):
    from . import records
    if journal is None:
        journal = journal_for(rt, holder, start)
    return records.build(rt.salt, holder, start, events(rt, start - 1), journal)


def write_records(rt: Runtime, now: float | None = None) -> list[str]:
    """Write yesterday's record for every holder that acted from this machine (once per holder and day)."""
    from . import records
    start = records.period_start(now) - records.DAY
    holders = {e["holder"] for e in events(rt, start) if e.get("holder") and float(e["ts"]) < start + records.DAY}
    done = []
    for h in holders:
        p = period_of(rt, bytes.fromhex(h), start)
        try:
            sig = records.write(rt.tf.url, rt.tf.credential, rt.key, p)
        except Exception:  # noqa: BLE001 - try again next sweep
            continue
        if sig:
            done.append(sig)
    return done


def explicit(repo: Path, globs: list[str], host: str, session: str) -> str | None:
    """`knos claim` and the MCP `remember(claiming=true)` in a team: claim the same globs on chain. Returns who holds
    them when another machine's agent won, else None (won, or no team, or the chain unreachable: local only)."""
    if not (Path(repo) / ".knos" / "team.json").exists() or not globs:
        return None
    try:
        rt = runtime(Path(repo))
        if rt is None:
            return None
        for _, v in claim_units(rt, globs, host, session):
            if v.outcome == "lost" and v.lost_to is not None:
                release_all(rt, host, session)
                return who(rt, str(v.lost_to.signer), v.lost_to.data.holder)
    except Exception:  # noqa: BLE001 - unreachable chain: the claim stays local, as the guard fails open
        return None
    return None


def explicit_release(repo: Path, host: str, session: str) -> None:
    """`knos done` and the MCP `done` in a team: give this agent's chain claims back too (else they lapse)."""
    if not (Path(repo) / ".knos" / "team.json").exists():
        return
    try:
        rt = runtime(Path(repo))
        if rt is not None:
            release_all(rt, host, session)
    except Exception:  # noqa: BLE001 - it lapses at its lease
        pass


if __name__ == "__main__":  # the background mirror: python -m knos.team.live <repo>
    raise SystemExit(run_mirror(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()))
