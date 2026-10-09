"""docs/MANIFEST.md: one page that ties a release together.

    python scripts/release_manifest.py            # write docs/MANIFEST.md
    python scripts/release_manifest.py --check    # exit 1 when the page is not what its sources give

The page says, for the release this tree is: its version and tag; for each program its public id, the build that is
LIVE at that id, the proposal that would replace it with its verified build hash and source commit; every proposal that
is pending; one row for every capability (source, test, deployed build, transaction, independent reproduction: a cell
with nothing behind it says "none"); and the limits that are still open.

Nothing on it is typed and nothing is assumed. Each part is read from the file that owns it:

    pyproject.toml                the version, and so the tag
    programs-v2/program_ids.json  the public program ids
    docs/capabilities.json        the version each public id runs (`programs.*.on_chain`), every capability's stage
    docs/provenance.json          the hash at each public id, from one read of the cluster
    web/upgrades.json             the proposals: build hash, source commit, verified-build run, status
    docs/DISCLOSURE.md            the limits, one line each ("## Outstanding limits")
    docs/load.json                the orders the load runs sent to the public ids (`measured`), with their dates
    docs/fee_slots.json           the slot of each recorded transaction, read from the cluster by `--read-slots`

For every recorded order at the public ids the page names the fee schedule that applied (knos_pay 2.1's tiers or 2.2's
0.30% with its 0.05 floor), decided in this order: the fee the order stored, when its record states it (a fee is taken
at funding and held with the order, so the stored fee IS the schedule); else the build live at the transaction's slot
(docs/fee_slots.json against the slots docs/provenance.json and web/upgrades.json give each build); else its date,
which only rules out a build whose proposal could not yet execute. A row none of these decide says so.

No time is printed: when a proposal can execute is in web/upgrades.json and on chain, and a page that named it would be
false after it ran (scripts/doc_claims.py refuses such a sentence). No count of capabilities is printed either: the
rows are the count.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

import capabilities as cap  # noqa: E402
import provenance as prov  # noqa: E402

DOC = "docs/MANIFEST.md"
SENTENCE = "The neutral meter for AI agent work: neither side keeps the count."
REPO = "https://github.com/drexthealpha/Knos"
LIMITS = "## Outstanding limits"
TX = "https://explorer.solana.com/tx/{}?cluster=devnet"


def version(root: Path = ROOT) -> str:
    m = re.search(r'(?m)^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("pyproject.toml names no version")
    return m.group(1)


def _short(h: str | None) -> str:
    return f"`{h}`" if h else "not recorded"


def _pending_after(data: dict, program: str, entry: dict | None) -> dict | None:
    """The newest proposal for `program` that is pending and newer than `entry` (the one its chain is about), or None."""
    after = int((entry or {}).get("index", -1))
    mine = [e for e in data["upgrades"].get("entries", [])
            if e.get("program") == program and e.get("status") == "pending" and int(e.get("index", 0)) > after]
    return max(mine, key=lambda e: int(e.get("index", 0)), default=None)


def programs(data: dict) -> list[str]:
    """One row for each program: what the public id runs, as the records say, and the build that would replace it."""
    lines = ["| program | public program id | LIVE at that id | hash at that id | its proposal | the proposal's verified build hash | built from |",
             "|---|---|---|---|---|---|---|"]
    listed = data["capabilities"].get("programs", {})
    for c in prov.chains(data):
        e, now = c["entry"], c["now"] or {}
        same = bool(c["links"]["hash on chain"].get("same"))
        # a provenance chain is about the newest proposal that RAN; a newer one that is pending is what would replace
        # the build that is live, so the row names that one, and the hash at the id is not its build until it runs
        if (later := _pending_after(data, c["program"], e)) is not None:
            e, same = later, bool(now.get("hash")) and now.get("hash") == later.get("build_hash")
        live = f"{c['program']} {c['runs']}" if c["runs"] else "not recorded"
        if e is None:
            proposal, built, source = "none", "none", "none"
        else:
            proposal = f"{e.get('index')}: {e.get('status')}" + ("" if same or e.get("status") != "executed" else ", and the hash read is not its build")
            built = _short(e.get("build_hash"))
            run = f", run `{e['gate_run']}`" if e.get("gate_run") else ""
            source = f"[`{str(e.get('source_commit'))[:7]}`]({REPO}/commit/{e.get('source_commit')}){run}" if e.get("source_commit") else "not recorded"
        hash_now = _short(now.get("hash")) + (" (the proposal's build)" if same else " (not the proposal's build)" if e and now.get("hash") else "")
        lines.append(f"| {c['program']} | `{c['address']}` | {live} | {hash_now} | {proposal} | {built} | {source} |")
    for name, p in listed.items():                                     # a program with no upgrade chain (upgrade_gate)
        if name not in prov.PROGRAMS:
            lines.append(f"| {name} | `{p.get('id')}` | {name} {p.get('on_chain')} | not read | none | none | none |")
    return lines


def pending(data: dict) -> list[str]:
    entries = sorted((e for e in data["upgrades"].get("entries", []) if e.get("status") == "pending"), key=lambda e: int(e.get("index", 0)))
    if not entries:
        return ["None: web/upgrades.json lists no pending proposal."]
    lines = ["| proposal | program | would deploy build | approvals |", "|---|---|---|---|"]
    lines += [f"| {e.get('index')} (`{e.get('proposal')}`) | {e.get('program')} | `{e.get('build_hash')}` | {e.get('approved')} of {e.get('threshold')} |"
              for e in entries]
    return lines


NONE = "none"


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def source_of(c: dict) -> str:
    got = (c.get("evidence") or {}).get("implemented")
    if not got:
        return NONE
    return f"[`{got['path']}`](../{got['path']})" + (f": `{_cell(got['names'])}`" if got.get("names") else "")


def test_of(c: dict) -> str:
    got = (c.get("evidence") or {}).get("tested")
    if not got:
        return NONE
    return f"[`{got['test']}`](../{got['test']})" + (f": `{_cell(got['names'])}`" if got.get("names") else "")


def build_of(c: dict, data: dict) -> str:
    """The build a capability is deployed in, and the hash the last read of the cluster found at that public id. The
    hash is the hash of what the id runs NOW: when the id has moved past the version the evidence names, the cell says
    so, and when the cluster was not read for that program it says "not read"."""
    got = (c.get("evidence") or {}).get("deployed")
    if not got:
        return NONE
    name = str(got.get("program"))
    listed = data["capabilities"].get("programs", {}).get(name, {})
    if listed.get("id") != got.get("id"):
        return f"none at a public id (`{name} {got.get('version')}` ran at a staging id)"
    seen = (data["record"].get("programs") or {}).get(name, {}).get("on_chain_hash")
    at = f"`{seen[:16]}`" if seen else "not read"
    if str(listed.get("on_chain")) == str(got.get("version")):
        return f"`{name} {got.get('version')}`, hash at its public id {at}"
    return f"`{name} {got.get('version')}` and later; its public id runs {listed.get('on_chain')}, hash at that id {at}"


def transaction_of(c: dict, root: Path = ROOT) -> str:
    got = (c.get("evidence") or {}).get("exercised")
    if not got or not got.get("signature"):
        return NONE
    link = f"[{got['signature'][:8]}...]({TX.format(got['signature'])})"
    return link if cap.ids_of(c, root) == "public" else f"none at the public ids (staging: {link})"


def reproduction_of(c: dict) -> str:
    """An independent reproduction: a run by someone who is not Knos, recorded as the capability's `reproduced` evidence."""
    got = (c.get("evidence") or {}).get("reproduced")
    if not got:
        return NONE
    return f"[outside run]({got['url']})" if got.get("url") else f"[`{got['file']}`](../{got['file']})" if got.get("file") else NONE


def evidence(c: dict) -> str:
    """The evidence of a capability's own stage, and of no other: one link."""
    stage = c["stage"]
    if not stage or not (c.get("evidence") or {}).get(stage):
        return "none: not built"
    if stage == "implemented":
        return source_of(c).split(": `")[0]
    if stage == "tested":
        return test_of(c).split(": `")[0]
    if stage == "deployed":
        got = c["evidence"]["deployed"]
        return f"`{got['program']} {got['version']}` at its public id"
    if stage == "exercised":
        got = c["evidence"]["exercised"]
        return f"[{got['signature'][:8]}...]({TX.format(got['signature'])})"
    return reproduction_of(c)


def stage_of(c: dict, root: Path = ROOT) -> str:
    return cap.WORDS[c["stage"]] + (", on staging program ids" if c["stage"] == "exercised" and cap.ids_of(c, root) == "staging" else "")


HEAD = ("capability", "stage", "source", "test", "deployed build", "transaction", "independent reproduction")


def row(c: dict, data: dict, root: Path = ROOT) -> list[str]:
    """One capability, one row, seven cells; a cell with nothing behind it says "none" and is never blank."""
    cells = [f"`{c['id']}`", stage_of(c, root), source_of(c), test_of(c), build_of(c, data), transaction_of(c, root), reproduction_of(c)]
    return [cell.strip() or NONE for cell in cells]


def capabilities(data: dict, root: Path = ROOT) -> list[str]:
    lines = ["| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    lines += ["| " + " | ".join(row(c, data, root)) + " |" for c in data["capabilities"].get("capabilities", [])]
    return lines


def limits(root: Path = ROOT) -> list[str]:
    """The lines of docs/DISCLOSURE.md's "Outstanding limits": each is one list item on one line."""
    text = (root / "docs" / "DISCLOSURE.md").read_text(encoding="utf-8")
    if LIMITS not in text:
        raise SystemExit(f'docs/DISCLOSURE.md has no "{LIMITS}" section')
    body = text.split(LIMITS, 1)[1].split("\n## ", 1)[0]
    got = [line for line in body.splitlines() if line.startswith("- ")]
    if not got:
        raise SystemExit(f'"{LIMITS}" in docs/DISCLOSURE.md lists nothing')
    return got


SLOTS = "docs/fee_slots.json"
_DAY = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b|\b(\d{1,2}) (October|September|November) (\d{4})\b")
_MONTH = {"September": 9, "October": 10, "November": 11}


def _json_of(path: Path) -> dict:
    import json
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _day(text: str | None) -> str | None:
    m = _DAY.search(text or "")
    if not m:
        return None
    return m.group(1) or f"{m.group(4)}-{_MONTH[m.group(3)]:02d}-{int(m.group(2)):02d}"


def _units(text: str) -> int:
    whole, _, frac = text.replace(",", "").partition(".")
    return int(whole) * 1_000_000 + int((frac + "000000")[:6])


def orders(data: dict, root: Path = ROOT) -> list[dict]:
    """Every order (or job) a record of this tree says was funded or paid at the public knos_pay: what, the transaction,
    its date, its amount and stored fee when the record states them. One row per transaction."""
    caps, out, seen = data["capabilities"], [], set()
    pay_id = (caps.get("programs", {}).get("knos_pay") or {}).get("id")
    rnd = caps.get("public_round") or {}
    if rnd.get("fund", {}).get("tx"):
        f = rnd["fund"]
        out.append({"what": f"the public round: order `{f.get('order')}` funded by `{f.get('comment')}`", "tx": f["tx"], "date": _day(rnd.get("date")),
                    "amount": f.get("amount"), "fee": f.get("fee"), "from": "docs/capabilities.json `public_round`"})
        seen.add(f["tx"])
    for c in caps.get("capabilities", []):
        ev = c.get("evidence") or {}
        got, dep = ev.get("exercised") or {}, ev.get("deployed") or {}
        if not got.get("signature") or got["signature"] in seen or got.get("ids") != "public" or dep.get("id") != pay_id:
            continue
        said = " ".join(got.get("asserted") or [])
        m = re.search(r"holds (\d[\d,]*\.\d\d) and its fee of (\d[\d,]*\.\d\d)", said)
        out.append({"what": f"`{c['id']}` ({got.get('round')} round)", "tx": got["signature"], "date": None,
                    "amount": m.group(1) if m else None, "fee": m.group(2) if m else None, "from": "docs/capabilities.json"})
        seen.add(got["signature"])
    for m in (_json_of(root / "docs" / "load.json").get("measured") or []):
        progs = m.get("programs") or ({"knos_pay": m["program"]} if m.get("program") else {})
        if progs.get("knos_pay") != pay_id:
            continue
        n = m.get("attempted") or m.get("orders")
        kind = "paid" if m.get("kind") == "pay" else "funded and refunded"
        out.append({"what": f"{n} orders {kind} by a load run, {m.get('relays')} relay{'' if m.get('relays') == 1 else 's'}; order ids not kept in docs/load.json", "tx": None,
                    "date": m.get("date"), "amount": None, "fee": None, "from": "docs/load.json `measured`"})
    return out


def builds(data: dict) -> list[dict]:
    """knos_pay's builds at its public id that this tree knows the first slot of, oldest first: {version, slot, fee}."""
    import knos.fees as fees
    out = []
    rec = (data["record"].get("programs") or {}).get("knos_pay") or {}
    # the build the cluster was read running, and the one before it (docs/provenance.json `before`), each from its live slot
    known = {int(r["proposal"]): r.get("live_slot") for r in (rec.get("before") or {}, rec) if r.get("proposal") is not None}
    entries = {int(e.get("index", 0)): e for e in data["upgrades"].get("entries", []) if e.get("program") == "knos_pay"}
    for idx, e in sorted(entries.items()):
        slot = e.get("executed_slot") or known.get(idx)
        if e.get("status") == "executed" and slot:
            new = idx > fees.OLD_PAY_PROPOSALS
            out.append({"proposal": idx, "slot": int(slot), "rule": fees.NEW if new else fees.OLD})
    return out


def schedule(o: dict, data: dict, slots: dict) -> tuple[str, str]:
    """(the fee schedule that applied, how this page knows it)."""
    import knos.fees as fees
    words = {r.build: rule_words(r) for r in (fees.OLD, fees.NEW)}
    if o.get("amount") and o.get("fee"):
        amount, fee = _units(o["amount"]), _units(o["fee"])
        fits = [r for r in (fees.OLD, fees.NEW) if r.order(amount) == fee]
        if len(fits) == 1:
            return words[fits[0].build], f"the order's stored fee: {o['fee']} on {o['amount']}"
    slot = (slots.get(o["tx"]) or {}).get("slot") if o.get("tx") else None
    if slot:
        live = [b for b in builds(data) if b["slot"] <= int(slot)]
        if live:
            b = live[-1]
            return words[b["rule"].build], f"the build live at slot {slot}: proposal {b['proposal']}'s, live from slot {b['slot']}"
        return "not decided", f"slot {slot} is before every build this tree knows the slot of"
    if o.get("date"):
        later = sorted((e for e in data["upgrades"].get("entries", []) if e.get("program") == "knos_pay" and int(e.get("index", 0)) > fees.OLD_PAY_PROPOSALS
                        and e.get("status") in ("pending", "executed") and e.get("earliest_execution_utc")), key=lambda e: e["earliest_execution_utc"])
        rec = (data["record"].get("programs") or {}).get("knos_pay") or {}
        # the read that found 2.1 live: the newest read, or, once 2.2 runs, the one kept with the build before (`before`)
        old = rec if rec.get("proposal") is not None and int(rec["proposal"]) <= fees.OLD_PAY_PROPOSALS else (rec.get("before") or {})
        read = str((data["record"] if old is rec else old).get("read", ""))[:10]
        old_live = old.get("proposal") is not None and int(old["proposal"]) <= fees.OLD_PAY_PROPOSALS and read < o["date"]
        if later and o["date"] < later[0]["earliest_execution_utc"][:10] and old_live:
            return words[fees.OLD.build], (f"its date: a day before proposal {later[0]['index']} (2.2) could execute (web/upgrades.json "
                                           f"`earliest_execution_utc`) and after the cluster read that found proposal {old['proposal']} (2.1) live "
                                           f"(docs/provenance.json `read`{'' if old is rec else ' of `before`'})")
        if later and o["date"] < later[0]["earliest_execution_utc"][:10]:
            return "knos_pay 2.0 or 2.1, not 2.2", f"its date rules out 2.2 only (proposal {later[0]['index']} could not yet execute); " + (
                "`--read-slots` reads the slot" if o.get("tx") else "the run kept no transaction to read a slot from")
    return "not decided", "no stored fee, slot or date in the record; `--read-slots` reads the slot"


def rule_words(r) -> str:
    """A knos_pay build's fee schedule in one phrase: orders and jobs apart where the build has them apart."""
    import knos.fees as fees
    job = f"{fees.pct(r.job_bps)} of the amount, at least {fees._money(r.job_floor)}"
    return f"knos_pay {r.build}: jobs and orders {r.rate()}" if not r.tiers and r.rate() == job else f"knos_pay {r.build}: orders {r.rate()}; jobs {job}"


def fee_rows(data: dict, root: Path = ROOT) -> list[str]:
    slots = _json_of(root / SLOTS)
    lines = ["| order | transaction | fee schedule that applied | how it is known | from |", "|---|---|---|---|---|"]
    for o in orders(data, root):
        tx = f"[{o['tx'][:8]}...]({TX.format(o['tx'])})" if o.get("tx") else "none kept"
        rule, how = schedule(o, data, slots)
        lines.append(f"| {_cell(o['what'])} | {tx} | {rule} | {_cell(how)} | {o['from']} |")
    return lines


def start_here(data: dict, root: Path = ROOT) -> list[str]:
    """One line for each program a payment runs through: source -> build hash -> deployed version -> transactions ->
    fee schedule."""
    import knos.fees as fees
    rows = orders(data, root)
    caps = data["capabilities"]
    out = []
    for c in prov.chains(data):
        if c["program"] not in ("knos_pay", "knos_oidc"):
            continue
        e, now = c["entry"] or {}, c["now"] or {}
        src = f"[`{str(e.get('source_commit'))[:7]}`]({REPO}/commit/{e.get('source_commit')})" if e.get("source_commit") else "source not recorded"
        h = _short(now.get("hash")[:16] if now.get("hash") else None)
        live = f"{c['program']} {c['runs']} at `{c['address']}`" if c["runs"] else f"`{c['address']}`, version not recorded"
        mine = ([o["tx"] for o in rows if o.get("tx")] if c["program"] == "knos_pay" else
                [x["evidence"]["exercised"]["signature"] for x in caps.get("capabilities", []) if (x.get("evidence") or {}).get("exercised", {}).get("signature")
                 and x["evidence"]["exercised"].get("ids") == "public" and (x["evidence"].get("deployed") or {}).get("id") == c["address"]])
        mine = list(dict.fromkeys(mine))
        txs = f"{len(mine)} recorded transaction{'' if len(mine) == 1 else 's'}" + (f", first [{mine[0][:8]}...]({TX.format(mine[0])})" if mine else "")
        if c["program"] == "knos_pay":
            nxt = _pending_after(data, "knos_pay", c["entry"])
            rule = fees.rule(fees.NEW_VERSION if c["runs"] and str(c["runs"]).startswith("2.2") else 1)
            fee = "fee schedule: " + rule_words(rule) + (f"; proposal {nxt['index']} (pending) would charge {rule_words(fees.NEW)}" if nxt and rule is fees.OLD else "")
        else:
            fee = "no fee: the verifier moves no money"
        out.append(f"- **{c['program']}**: {src} -> build {h} -> {live} -> {txs} -> {fee}.")
    return out


def read_slots(root: Path = ROOT, rpc: str | None = None, say: Callable[[str], None] = print, call=None) -> int:
    """The slot and block time of every recorded transaction whose slot is not kept yet, into docs/fee_slots.json."""
    import json

    from knos import chain
    url = rpc or chain.ledger().url
    ask = call or (lambda method, params: chain.call(url, method, params))
    path, have = root / SLOTS, _json_of(root / SLOTS)
    for o in orders(prov.load(root), root):
        if o.get("tx") and o["tx"] not in have:
            got = ask("getTransaction", [o["tx"], {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}])
            if got:
                have[o["tx"]] = {"slot": int(got["slot"]), "block_time": got.get("blockTime")}
    path.write_text(json.dumps(dict(sorted(have.items())), indent=1) + "\n", encoding="utf-8")
    say(f"{SLOTS}: {len(have)} transactions with their slots")
    return 0


def render(root: Path = ROOT) -> str:
    data, v = prov.load(root), version(root)
    feed = data["upgrades"]
    parts = [
        f"# Release manifest: Knos {v}", "", f"**{SENTENCE}**", "",
        "One page for this release: the source, the bytes each public program id runs, every capability's stage, and the",
        "limits still open. `python scripts/release_manifest.py` writes it from the files named under each heading, and",
        "`--check` fails when it differs from them. Nothing here is typed by hand, and no time is printed.", "",
        "## Start here", "",
        "Each program a payment runs through, in one line: the source, the hash of the build at its public id, the version",
        "deployed there, the transactions recorded, and the fee schedule. The rows behind each step are below.", "",
        *start_here(data, root), "",
        "## Source", "",
        f"- Release: Knos {v} (`pyproject.toml`). Tag: [`v{v}`]({REPO}/tree/v{v}); `git rev-list -n 1 v{v}` prints its commit. A file",
        "  cannot hold the hash of the commit that holds it.",
        "- Cluster: Solana devnet. The money is test USDC. Mainnet is not touched.", "",
        "## Programs: what is live at each public id", "",
        "Read from `docs/capabilities.json` (`programs`), `docs/provenance.json` (one read of the cluster; its `read` says",
        "when) and `web/upgrades.json` (the multisig's accounts; its `generated` says when). A proposal that is pending has",
        "not run: the public id runs the build in the third column until it does.", "",
        *programs(data), "",
        "A program whose source changed after its proposal's commit has no verified build hash on this page until the",
        "`verified-build` job has built it and a new proposal names it: `git diff <built from> -- programs-v2/<program>`",
        "shows whether it changed. Each link of each chain is in [PROVENANCE.md](PROVENANCE.md).", "",
        "## Pending proposals", "",
        f"Upgrade multisig `{feed.get('multisig', 'not recorded')}`, {feed.get('threshold', '?')} of {feed.get('members', '?')}. From `web/upgrades.json`; when each can",
        "execute is its `earliest_execution_utc` there.", "",
        *pending(data), "",
        "## Capabilities: the stage of each, with its evidence", "",
        "One row for each capability: where it is in the source, the test that covers it, the build it is deployed in with",
        "the hash last read at that public id, a transaction that exercised it, and a reproduction by someone outside.",
        "From `docs/capabilities.json` and `docs/provenance.json`. A stage is the highest that has evidence; deployed and",
        "exercised count only at the public program ids. A cell with nothing behind it says none. The note of each",
        "capability is in [CAPABILITIES.md](CAPABILITIES.md).", "",
        *capabilities(data, root), "",
        "## Fee schedule of each recorded order", "",
        "Every order or job a record of this tree says ran at the public knos_pay, and the fee schedule that applied: the",
        "fee the order stored when the record states it, else the build live at its slot (`docs/fee_slots.json`, written by",
        "`python scripts/release_manifest.py --read-slots`), else what its date rules out.", "",
        *fee_rows(data, root), "",
        "## Outstanding limits", "",
        "From [DISCLOSURE.md](DISCLOSURE.md), one line each.", "",
        *limits(root), "",
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None, say: Callable[[str], None] = print, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when docs/MANIFEST.md is not what its sources give")
    ap.add_argument("--read-slots", action="store_true", help="read each recorded transaction's slot from the cluster into docs/fee_slots.json, then write")
    ap.add_argument("--rpc", help="with --read-slots: the cluster's endpoint (default: KNOS_RPC, else public devnet)")
    a = ap.parse_args(argv)
    if a.read_slots:
        read_slots(root, a.rpc, say)
    page, want = root / DOC, render(root)
    if a.check:
        if not page.is_file() or page.read_text(encoding="utf-8") != want:
            say(f"{DOC} is stale: run python scripts/release_manifest.py")
            return 1
        say(f"{DOC} is what its sources give")
        return 0
    page.write_text(want, encoding="utf-8", newline="")
    say(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
