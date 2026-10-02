"""`knos doctor`: what is guarded, what is not, and what needs a person.

On this machine: which agent hosts have the edit guard, whether this repo has the commit guard and the committed repo
hooks. In a team: this key's float (how many more claims it can place), and which members have shown no activity on
chain recently (their machines may be unguarded or offline). Nothing here writes anything.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def local(repo: Path | None) -> list[tuple[str, bool, str]]:
    """(check, ok, detail) rows for this machine."""
    from . import commit_guard, guard, team_setup
    from .init import present
    rows = []
    wired = guard.installed()
    names = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor", "opencode": "OpenCode"}
    for host, name in names.items():
        here = present(host) if host != "opencode" else bool(shutil.which("opencode")) or wired.get(host, False)
        if not here and not wired.get(host):
            continue
        rows.append((f"{name} edit guard", bool(wired.get(host)),
                     "on" if wired.get(host) else "off: run  knos init"))
    if repo is not None:
        ok = commit_guard.installed(repo)
        rows.append(("commit guard (raw shell writes)", ok, "on" if ok else "off: run  knos init --team"))
        if (repo / ".knos" / "team.json").exists():
            got = team_setup.installed(repo)
            rows.append(("repo hooks for cloud sessions", got["claude_repo"] and got["codex_repo"],
                         "committed in .claude/settings.json and .codex/hooks.json" if got["claude_repo"]
                         else "missing: run  knos init --team, then commit"))
    return rows


def team(repo: Path, quiet_days: int = 7) -> list[tuple[str, bool, str]]:
    import time

    from .team import config, live, rpc, service
    rows = []
    tf = config.load(repo)
    if tf is None:
        return rows
    try:
        got = service.status(tf)
    except Exception as why:  # noqa: BLE001
        got = None
        rows.append(("team registry reachable", False, f"{tf.cluster}: {type(why).__name__}; edits run local-only"))
    else:
        rows.append(("team registry reachable", True, f"{got['name']} on {got['cluster']}"))
        me = got.get("me")
        if me:
            rows.append(("this machine is a member", me["member"], "yes" if me["member"] else
                         "no: send the owner the join code from  knos init"))
            rows.append(("key float", me["claims_headroom"] >= 5,
                         f"{me['sol']:.4f} SOL, room for about {me['claims_headroom']} live claims"))
        cutoff = None
        for m in got["members"]:
            try:
                sigs = rpc.call(tf.url, "getSignaturesForAddress", [m["key"], {"limit": 1}], timeout=10) or []
            except Exception:  # noqa: BLE001
                continue
            last = sigs[0].get("blockTime") if sigs else None
            cutoff = cutoff or time.time() - quiet_days * 86_400
            if not last or last < cutoff:
                rows.append((f"member {m['name'] or m['key'][:8]}", False,
                             f"no chain activity in {quiet_days} days: that machine may be offline or unguarded"))

    age, running = live.mirror_status(repo)
    if age is None:
        rows.append(("local mirror", False, f"never synced, knos mirror {'is running' if running else 'is not running'}"))
    else:
        fresh = age <= live.FRESH_S
        status_word = "fresh" if fresh else "stale"
        running_word = "knos mirror is running" if running else "knos mirror is not running"
        detail = f"{age:.1f}s old ({status_word}), {running_word}"
        rows.append(("local mirror", fresh and running, detail))
    return rows


def run(repo: Path | None) -> list[tuple[str, bool, str]]:
    rows = local(repo)
    if repo is not None and (repo / ".knos" / "team.json").exists():
        try:
            rows += team(repo)
        except ImportError as why:
            rows.append(("team extras installed", False, f"missing {why.name}: pip install -U knos"))
    rows += jobs()
    return rows


def jobs() -> list[tuple[str, bool, str]]:
    """The escrow this machine hires and works through, and how it waits for settlement (Alpenglow-aware)."""
    try:
        from .jobs import finality, net
        cluster = net.cluster()
        url = net.ledger().url
    except ImportError as why:
        return [("jobs extras installed", False, f"missing {why.name}: pip install -U knos")]
    except Exception as why:  # noqa: BLE001 - net.Refused, a bad setting
        return [("jobs network", False, str(why))]
    try:
        mode, gap = finality.mode(url, timeout=3.0)
    except Exception:  # noqa: BLE001 - offline: say so, it is not a failure of this machine
        return [("jobs settlement", True, f"{cluster}: RPC unreachable now; will settle at 'confirmed'")]
    why = (f"finalized is {gap} slot(s) behind confirmed, measured now" if mode == "finalized"
           else f"finalized trails confirmed by {gap} slots")
    rows = [("jobs settlement", True, f"{cluster}: waits for '{mode}' ({why})")]
    from .jobs import market
    try:
        rows.append(("escrow program version", True, f"{cluster} runs knos-escrow "
                     f"{market.assert_program_version(net.ledger())}, as this client needs"))
    except market.ProgramVersionError as e:
        rows.append(("escrow program version", False, str(e)))
    except Exception as e:  # noqa: BLE001 - offline mid-check
        rows.append(("escrow program version", True, f"{cluster}: not checked now ({type(e).__name__})"))
    return rows
