"""Provenance: for each of the four programs, one chain a stranger can follow from source to a run on chain.

    python scripts/provenance.py                 # print the chains, from what this repository records
    python scripts/provenance.py --write         # rewrite the block of docs/PROVENANCE.md between its markers
    python scripts/provenance.py --check         # exit 1 when docs/PROVENANCE.md is not what the records give
    python scripts/provenance.py --rpc [URL]     # also read the cluster: the hash each program runs, each proposal's
                                                 # state, the build record of upgrade_gate, the execution transaction
    python scripts/provenance.py --rpc --record  # and keep what was read in docs/provenance.json (the release does)

The chain, per program:

    source commit -> verified-build run -> build hash -> the hash on chain at the public program id
                  -> the upgrade proposal and its execution transaction -> one exercised scenario

Where each link comes from. The proposal, its build hash, the commit and the run: web/upgrades.json, which
scripts/upgrade_feed.py writes from the multisig's accounts and from upgrade_gate's record on chain. The public
program ids: programs-v2/program_ids.json. The version devnet runs at each id, and a transaction that exercised a
capability there: docs/capabilities.json. The time lock, as a claim that is checked live: docs/facts.json. The release
that proposed the build: CHANGELOG.md. The hash a program runs and the transaction that executed a proposal are on
chain and nowhere in those files, so they are read with --rpc and kept, with the time of the read, in
docs/provenance.json.

A link the records do not hold is printed as MISSING with the reason. Nothing is filled in: no link is guessed from
another, and a hash read from the cluster is never written as if the repository had recorded it before.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "PROVENANCE.md"
RECORD = ROOT / "docs" / "provenance.json"
PROGRAMS = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")
DEVNET = "https://api.devnet.solana.com"
BEGIN, END = "<!-- provenance:begin -->", "<!-- provenance:end -->"
MISSING = "MISSING"
LINKS = ("source commit", "verified-build run", "build hash", "hash on chain", "upgrade proposal", "execution transaction",
         "exercised scenario")
REPO = "drexthealpha/Knos"      # whose program.yml the release reads (src/knos/mainnet_check.py REPO)
_SIG = re.compile(r"[1-9A-HJ-NP-Za-km-z]{64,88}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def load(root: Path = ROOT) -> dict:
    """Everything the chains are assembled from, as the repository holds it. A file that is absent is None."""
    changelog = root / "CHANGELOG.md"
    return {"ids": _json(root / "programs-v2" / "program_ids.json") or {},
            "upgrades": _json(root / "web" / "upgrades.json") or {},
            "capabilities": _json(root / "docs" / "capabilities.json") or {},
            "facts": (_json(root / "docs" / "facts.json") or {}).get("facts", []),
            "changelog": changelog.read_text(encoding="utf-8") if changelog.is_file() else "",
            "record": _json(root / "docs" / "provenance.json") or {}}


def subject(data: dict, program: str) -> dict | None:
    """The proposal a program's chain is about: the newest one that executed, and when none has, the newest that is
    pending. A cancelled or replaced proposal never ran and never will, so it is not a link of anything."""
    mine = sorted((e for e in data["upgrades"].get("entries", []) if e.get("program") == program), key=lambda e: -int(e.get("index", 0)))
    for status in ("executed", "pending"):
        for e in mine:
            if e.get("status") == status:
                return e
    return None


def version_of(data: dict, program: str, entry: dict | None) -> str | None:
    """The version the proposal's build is, by docs/capabilities.json: the one devnet runs when the proposal executed,
    the newest listed one when it is pending and devnet runs an older one. None when the manifest cannot say."""
    p = data["capabilities"].get("programs", {}).get(program) or {}
    if entry is None or not p:
        return None
    if entry.get("status") == "executed":
        return p.get("on_chain")
    newest = (p.get("versions") or [None])[-1]
    return newest if newest != p.get("on_chain") else None


def release_note(data: dict, program: str, version: str | None) -> str | None:
    """The first release whose CHANGELOG section names `program version`, as "0.3.14"; None when no section does."""
    if not version:
        return None
    for part in reversed(re.split(r"^## ", data["changelog"], flags=re.M)[1:]):      # the oldest section that names it
        if f"`{program} {version}`" in part:
            return part.split()[0]
    return None


def scenario(data: dict, program: str, address: str, version: str | None) -> dict | None:
    """One capability whose evidence is a transaction at this public id, on this version: {"id", "what", "signature"}."""
    for c in data["capabilities"].get("capabilities", []):
        ev = c.get("evidence") or {}
        dep, ex = ev.get("deployed") or {}, ev.get("exercised") or {}
        # the version that carries the capability, or a run scripts/exercise_public.py made at this id (`round`): that
        # run starts only once the public id runs the proposal's build, whichever version first carried the capability
        if dep.get("program") == program and dep.get("id") == address and (dep.get("version") == version or ex.get("round")) \
                and _SIG.fullmatch(str(ex.get("signature", ""))):
            return {"id": c["id"], "what": c["what"], "signature": ex["signature"]}
    return None


def exercises(data: dict, program: str, address: str) -> list[tuple[str, str]]:
    """(capability, signature) for every capability exercised by a transaction at this public id."""
    out = []
    for c in data["capabilities"].get("capabilities", []):
        ev = c.get("evidence") or {}
        dep, ex = ev.get("deployed") or {}, ev.get("exercised") or {}
        if dep.get("program") == program and dep.get("id") == address and _SIG.fullmatch(str(ex.get("signature", ""))):
            out.append((c["id"], ex["signature"]))
    return out


def summary(c: dict) -> list[str]:
    """One table for a program: the build its chain is about, where it runs, since when, and what was run on it. The
    slot and the exercise transactions are filled by `scripts/exercise_public.py record`, only once the public id
    runs this build."""
    e, links = c["entry"] or {}, c["links"]
    live = bool(links["hash on chain"].get("same"))
    commit, build = links["source commit"]["value"], links["build hash"]["value"]
    ran = ", ".join(f"[{sig[:8]}...](https://explorer.solana.com/tx/{sig}?cluster=devnet) (`{cid}`)" for cid, sig in c["exercises"])
    return ["| source commit | verified build hash | program id | proposal | slot it went live | exercise transactions |", "|---|---|---|---|---|---|",
            f"| {f'`{commit}`' if commit else MISSING} | {f'`{build}`' if build else MISSING} | `{c['address']}` | {e.get('index', MISSING)} | "
            + (str(c["slot"]) if c["slot"] is not None else "not recorded" if live else "not live yet") + " | "
            + (ran or ("none recorded" if live else "none: the public id does not run this build yet")) + " |", ""]


def link(value: str | None, where: str, why: str = "") -> dict:
    return {"value": value, "where": where, "why": why}


def chain_of(data: dict, program: str) -> dict:
    """One program's chain: {"program", "address", "runs", "version", "entry", "release", "links": {name: link}}."""
    address = data["ids"].get(program)
    entry = subject(data, program)
    runs = (data["capabilities"].get("programs", {}).get(program) or {}).get("on_chain")
    version = version_of(data, program, entry)
    seen = (data["record"].get("programs") or {}).get(program) or {}
    out: dict[str, dict] = {}
    feed = "web/upgrades.json"
    if entry is None:
        why = "web/upgrades.json has no executed or pending upgrade proposal for this program"
        for name in LINKS[:3] + LINKS[4:6]:
            out[name] = link(None, feed, why)
    else:
        executed = entry.get("status") == "executed"
        out["source commit"] = link(entry.get("source_commit"), feed, "upgrade_gate holds no record for this build hash")
        out["verified-build run"] = link(str(entry["gate_run"]) if entry.get("gate_run") else None, feed,
                                         "upgrade_gate holds no record for this build hash")
        out["build hash"] = link(entry.get("build_hash"), feed, "the proposal's buffer is closed and no earlier read of it is on file")
        state = f"proposal {entry.get('index')} ({entry.get('proposal')}): {entry.get('squads_status')}, approved by " \
                f"{entry.get('approved')} of {entry.get('threshold')}"
        if not executed and entry.get("earliest_execution_utc"):
            state += ", can execute once the time lock has run (`earliest_execution_utc` of this entry in the feed says when)"
        out["upgrade proposal"] = link(state if entry.get("proposal") else None, feed, "the feed names no proposal account")
        sig = seen.get("execution_signature") if seen.get("proposal") == entry.get("index") else None
        out["execution transaction"] = link(
            sig if executed else None, "docs/provenance.json",
            "the proposal executed and no read of its transaction is on file (run with --rpc --record)" if executed
            else "the proposal had not executed when web/upgrades.json was generated")
    h = seen.get("on_chain_hash")
    same = bool(entry) and h is not None and h == entry.get("build_hash")
    if h and _HEX64.fullmatch(str(h)):
        note = "the build above" if same else ("NOT the build above: its proposal had not executed" if entry and entry.get("status") != "executed"
                                                 else "NOT the build above")
        out["hash on chain"] = link(f"{h} ({note}; when it was read is `read` in docs/provenance.json)", "docs/provenance.json")
        out["hash on chain"]["same"] = same
    else:
        out["hash on chain"] = link(None, "docs/provenance.json", "no read of the cluster is on file (run with --rpc --record)")
    got = scenario(data, program, str(address), version) if entry and entry.get("status") == "executed" else None
    if got:
        out["exercised scenario"] = link(f"{got['signature']} ({got['id']}: {got['what']})", "docs/capabilities.json")
    elif entry and entry.get("status") != "executed":
        out["exercised scenario"] = link(None, "docs/capabilities.json", "nothing can be exercised at the public id before the proposal executes; "
                                         "a run on a staging deployment is not evidence")
    else:
        out["exercised scenario"] = link(None, "docs/capabilities.json", f"no capability has a transaction at this id for {program} {version or '?'}")
    return {"program": program, "address": address, "runs": runs, "version": version, "entry": entry,
            "slot": seen.get("live_slot") if same else None, "exercises": exercises(data, program, str(address)) if same else [],
            "release": release_note(data, program, version), "links": {name: out[name] for name in LINKS},
            "now": {"hash": h, "commit": seen.get("on_chain_commit"), "run": seen.get("on_chain_run")} if h else None}


def chains(data: dict) -> list[dict]:
    return [chain_of(data, p) for p in PROGRAMS]


def complete(chain: dict) -> bool:
    """Every link is recorded, and the hash on chain is the build's."""
    return all(v["value"] for v in chain["links"].values()) and bool(chain["links"]["hash on chain"].get("same"))


def missing(chain: dict) -> list[str]:
    return [name for name, v in chain["links"].items() if not v["value"]]


def time_lock(data: dict) -> str:
    seconds = data["upgrades"].get("time_lock")
    fact = next((f for f in data["facts"] if f.get("live") == "upgrade_delay"), None)
    hours = f"{seconds // 3600} hours" if isinstance(seconds, int) else MISSING
    return f"{hours} (web/upgrades.json `time_lock`" + (f"; docs/facts.json checks {fact['say'][0]} hours against the cluster at release)" if fact and fact.get("say") else ")")


def _show(name: str, v: dict, chain: dict) -> str:
    if not v["value"]:
        return f"**{MISSING}**: {v['why']}"
    text = str(v["value"])
    if name == "source commit":
        return f"[`{text}`](https://github.com/{REPO}/commit/{text})"
    if name == "verified-build run":
        return (f"run `{text}` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with "
                f"the commit; the record holds the run's number and not its repository: the release reads runs of {REPO}, "
                f"so look at https://github.com/{REPO}/actions/runs/{text}")
    if name == "build hash":
        return f"`{text}` (sha256 of the executable; read from the {(chain['entry'] or {}).get('hash_from') or 'feed'})"
    if name in ("execution transaction", "exercised scenario"):
        sig, _, rest = text.partition(" ")
        return f"[`{sig}`](https://explorer.solana.com/tx/{sig}?cluster=devnet)" + (f" {rest}" if rest else "")
    if name == "hash on chain":
        h, _, rest = text.partition(" ")
        return f"`{h}` {rest}"
    return text


def _now(c: dict) -> str:
    """What the public id runs today and whether that build is tied to a commit: said for every program, because a
    chain about a proposal that has not executed says nothing about the build people are using meanwhile."""
    now = c["now"]
    if not now:
        return f"What the public id runs: **{MISSING}**: no read of the cluster is on file."
    tied = (f"upgrade_gate's record ties that build to commit `{now['commit']}` and run `{now['run']}`" if now.get("commit") else
            f"the commit and the run that built it are **{MISSING}**: upgrade_gate holds no build record for that hash, so "
            "nothing on chain ties that build to a commit")
    return f"What the public id ran when docs/provenance.json was read: `{now['hash']}`; {tied}."


def render(data: dict) -> str:
    """The block of docs/PROVENANCE.md, markers included."""
    got = chains(data)
    up = data["upgrades"]
    out = [BEGIN, "",
           "Assembled by `python scripts/provenance.py --write` from web/upgrades.json (the multisig's accounts as the feed read "
           "them; its `generated` says when), docs/capabilities.json, programs-v2/program_ids.json, docs/facts.json, CHANGELOG.md"
           + (" and docs/provenance.json (one read of the cluster; its `read` says when)." if data["record"].get("read") else
              ". docs/provenance.json does not exist: no read of the cluster is on file."),
           f"Cluster: {up.get('cluster', MISSING)}. Upgrade multisig: `{up.get('multisig', MISSING)}`, {up.get('threshold', '?')} of "
           f"{up.get('members', '?')}, time lock {time_lock(data)}.", "",
           "| program | public id | devnet runs, as docs/capabilities.json records it | the chain is about | links recorded | complete |", "|---|---|---|---|---|---|"]
    for c in got:
        e = c["entry"]
        about = MISSING if e is None else f"proposal {e['index']} ({e['status']} in web/upgrades.json)" + (f", {c['program']} {c['version']}" if c["version"] else "")
        out.append(f"| {c['program']} | `{c['address']}` | {c['runs'] or MISSING} | {about} | "
                   f"{len(LINKS) - len(missing(c))} of {len(LINKS)} | {'yes' if complete(c) else 'no'} |")
    out.append("")
    for c in got:
        e = c["entry"]
        out += [f"### {c['program']}", "",
                f"Public id `{c['address']}`. docs/capabilities.json records version {c['runs'] or MISSING} running there. "
                + ("No upgrade proposal is on record." if e is None else
                   f"The chain below is the build of proposal {e['index']}" + (f", {c['program']} {c['version']}" if c["version"] else "")
                   + (", which runs there now." if e["status"] == "executed" else ", which was approved and had not executed when "
                      "web/upgrades.json was generated: the public id runs the older build until it does, and the live state is in "
                      "web/upgrades.json." if e.get("squads_status") == "Approved"
                      else ", which was pending when web/upgrades.json was generated."))
                + (f" Release note: CHANGELOG.md, {c['release']}." if c["release"] else f" Release note: **{MISSING}**: no section of CHANGELOG.md names this build."),
                "", _now(c), "", *summary(c),
                "| # | link | what is recorded | recorded in |", "|---|---|---|---|"]
        for i, (name, v) in enumerate(c["links"].items(), 1):
            out.append(f"| {i} | {name} | {_show(name, v, c)} | {v['where']} |")
        gone = missing(c)
        out += ["", ("Every link is recorded and the hash on chain is this build's." if complete(c) else
                     f"Not complete: {len(gone)} of {len(LINKS)} links are {MISSING} ({', '.join(gone)})." if gone else
                     "Not complete: the hash on chain is not this build's."), ""]
    out.append(END)
    return "\n".join(out)


def placed(doc: str, block: str) -> str:
    if BEGIN not in doc or END not in doc:
        raise SystemExit(f"stopped: {DOC.name} has no {BEGIN} ... {END} block to write between")
    return doc.split(BEGIN)[0] + block + doc.split(END, 1)[1]


# ---- the cluster ------------------------------------------------------------------------------------------------------

def execution_signature(call: Callable[[str, list], Any], proposal: str, programdata: str) -> str | None:
    """The transaction that executed a proposal: the newest successful one that names both the proposal account and
    the program's data account (an approval names the first and not the second). None when there is none."""
    for row in call("getSignaturesForAddress", [proposal, {"limit": 25, "commitment": "confirmed"}]) or []:
        if row.get("err") is not None:
            continue
        tx = call("getTransaction", [row["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
        if not tx:
            continue
        keys = list(tx["transaction"]["message"].get("accountKeys", []))
        loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
        keys += list(loaded.get("writable", [])) + list(loaded.get("readonly", []))
        if programdata in keys and proposal in keys:
            return str(row["signature"])
    return None


def live(data: dict, url: str) -> tuple[dict, list[str]]:
    """(what the cluster says now, as docs/provenance.json holds it; lines for a reader). Needs the network and Knos's
    own modules; nothing is written here."""
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import upgrade_feed as feed
    from knos import chain as kchain, mainnet_check as mc
    from solders.pubkey import Pubkey

    account = mc._rpc(url)

    def call(method: str, params: list) -> Any:
        return kchain.call(url, method, params, timeout=30)

    ids = data["ids"]
    seen: dict = {"read": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cluster": mc._cluster(url), "rpc": url, "programs": {}}
    lines = []
    for program in PROGRAMS:
        address, entry = ids[program], subject(data, program)
        now = feed.program_hash(account, address)
        row: dict = {"address": address, "on_chain_hash": now}
        pd = account(str(mc.programdata_address(address)))
        if pd and len(pd[1]) >= 12:
            row["live_slot"] = int.from_bytes(pd[1][4:12], "little")        # the slot of the last deployment: when this build went live
        rec = feed.gate_record(account, address, now)
        if rec:
            row["on_chain_commit"], row["on_chain_run"] = rec.sha, rec.run_id
        lines.append(f"{program}: {address} runs {now or 'nothing (not deployed)'}"
                     + (f", built from {rec.sha} in run {rec.run_id} (upgrade_gate's record)" if rec else
                        ", and upgrade_gate holds no build record for that hash"))
        if entry:
            got = account(entry["proposal"])
            p = mc.read_proposal(got[1]) if got else None
            row.update(proposal=entry["index"], proposal_status=p.status if p else None)
            word = "the proposal's build" if now == entry.get("build_hash") else "not the proposal's build"
            lines.append(f"  proposal {entry['index']}: {p.status if p else MISSING + ' (the proposal account could not be read)'}; "
                         f"the feed says {entry.get('squads_status')}; the program runs {word}")
            if p and p.status == "Executed":
                row["execution_signature"] = execution_signature(call, entry["proposal"], str(mc.programdata_address(Pubkey.from_string(address))))
                lines.append(f"  executed in {row['execution_signature'] or MISSING + ' (no transaction names both the proposal and the program data)'}")
                if now != entry.get("build_hash"):
                    lines.append("  PROBLEM: the proposal executed and the program does not run its build")
            elif p and p.status != entry.get("squads_status"):
                lines.append("  the feed is older than the cluster: run scripts/upgrade_feed.py, then this again")
        seen["programs"][program] = row
    if data["record"].get("next"):          # the build scripts/exercise_public.py propose-oidc named: not something a read replaces
        seen["next"] = data["record"]["next"]
    return seen, lines


def main(argv: list[str] | None = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="rewrite the block of docs/PROVENANCE.md")
    ap.add_argument("--check", action="store_true", help="exit 1 when docs/PROVENANCE.md is not what the records give")
    ap.add_argument("--rpc", nargs="?", const=DEVNET, help="read the cluster as well (default: devnet's public endpoint)")
    ap.add_argument("--record", action="store_true", help="with --rpc: keep what was read in docs/provenance.json")
    ap.add_argument("--strict", action="store_true", help="exit 1 while any chain is not complete")
    a = ap.parse_args(argv)
    data = load()
    bad = 0
    if a.rpc:
        try:
            seen, lines = live(data, a.rpc)
        except SystemExit:
            raise
        except Exception as why:  # noqa: BLE001 - no network is not an answer
            say(f"stopped: {a.rpc} could not be read ({type(why).__name__}: {why}). Nothing was written.")
            return 2
        for line in lines:
            say(line)
        bad += any("PROBLEM" in line for line in lines)
        if a.record:
            RECORD.write_text(json.dumps(seen, indent=1) + "\n", encoding="utf-8", newline="")
            data = load()
    elif a.record:
        say("--record needs --rpc: only a read of the cluster is kept")
        return 2
    block = render(data)
    if a.write:
        DOC.write_text(placed(DOC.read_text(encoding="utf-8"), block), encoding="utf-8", newline="")
    elif a.check:
        if not DOC.is_file() or placed(DOC.read_text(encoding="utf-8"), block) != DOC.read_text(encoding="utf-8"):
            say("docs/PROVENANCE.md is not what the records give: run python scripts/provenance.py --write")
            return 1
    else:
        say(block)
    got = chains(data)
    for c in got:
        say(f"{c['program']}: " + ("complete" if complete(c) else f"{MISSING} {', '.join(missing(c)) or 'nothing; the hash on chain is not this build'}"))
    return 1 if bad or (a.strict and not all(complete(c) for c in got)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
