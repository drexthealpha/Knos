"""`knos record verify`: hold a Knos Record to itself, to Solana and to Sibyl's memory.

    1. the file    every line parses, has the record's fields, is line n at seq n, links to the hash before it, hashes
                   to what it says, has the tier its kind names, and holds nothing a public record may not
    2. anchors     each anchor covers the lines right after the last one; the Merkle root of those lines, recomputed
                   here, is the root it states, and its head is the hash of its last line
    3. the chain   each anchor's transaction exists on the cluster, succeeded, was signed by the wallet the line names,
                   and its Memo instruction is exactly the memo recomputed in 2 (skipped with offline=True: then the
                   report says the chain was not read)
    4. Sibyl       when Sibyl's store is beside the file (or one is given), every line in Sibyl's journal (COLD) is in
                   the file with the same hash and every line of the file is in Sibyl's journal; each claim's entity
                   (WARM) and each paper's reference (REFERENCE) points at its latest line. Lines removed from the end
                   of the file, which break no hash, are caught here, and by the next anchor's `first`.

A public copy of the file has no Sibyl store beside it; it is then checked by 1-3 and the report says Sibyl was not
consulted. Lines after the last anchor are reported as unanchored: nothing on chain vouches for them yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import anchoring as anc
from . import journal, merkle


def _check_lines(lines: list[dict], problems: list[str]) -> None:
    prev = journal.GENESIS
    for i, e in enumerate(lines):
        where = f"line {i + 1}"
        if set(e) != set(journal.FIELDS):
            problems.append(f"{where} has fields {sorted(e)}, not the record's {sorted(journal.FIELDS)}")
            prev = e.get("hash", "")
            continue
        if e["v"] != journal.VERSION:
            problems.append(f"{where} is version {e['v']!r}; this verifier reads version {journal.VERSION}")
        if e["seq"] != i:
            problems.append(f"{where} says seq {e['seq']}; it is line {i} counting from 0 (a line was removed, added or moved)")
        if e["prev"] != prev:
            problems.append(f"{where} (seq {e['seq']}) does not link to the line before it")
        if e["hash"] != journal.line_hash(e):
            problems.append(f"{where} (seq {e['seq']}) does not hash to what it says: it was edited")
        if journal.KINDS.get(e["kind"]) != e["tier"]:
            problems.append(f"{where} (seq {e['seq']}) is kind {e['kind']!r} in tier {e['tier']!r}")
        leaks = journal.redaction_problems(e.get("payload"))
        if leaks:
            problems.append(f"{where} (seq {e['seq']}) may not be in a public record: {leaks[0]}")
        prev = e["hash"]


def _check_anchors(lines: list[dict], fetch, offline: bool, problems: list[str], trusted: frozenset = frozenset()) -> list[dict]:
    out = []
    expected_first = 0
    for a in anc.anchors(lines):
        p = a.get("payload") or {}
        row = {"seq": a["seq"], "first": p.get("first"), "last": p.get("last"), "root": p.get("root"), "tx": p.get("tx"),
               "cluster": p.get("cluster"), "signer": p.get("signer"), "root_ok": False, "chain": "not read"}
        out.append(row)
        row["pinned"] = p.get("signer") in trusted
        if not row["pinned"]:
            problems.append(f"the anchor at seq {a['seq']} is signed by {p.get('signer')}, which is not a pinned anchoring key "
                            f"({', '.join(sorted(trusted)) or 'none'}): anyone can anchor a rewritten journal with a wallet of their own. "
                            f"If this is your own record, anchored by your own wallet, verify it with --signer {p.get('signer')} "
                            f"(or KNOS_RECORD_SIGNERS={p.get('signer')})")
        try:
            first, last = int(p["first"]), int(p["last"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"the anchor at seq {a['seq']} does not say which lines it covers")
            continue
        if first != expected_first:
            problems.append(f"the anchor at seq {a['seq']} starts at seq {first}; the lines before it end at {expected_first - 1}")
        if not first <= last < a["seq"] or last >= len(lines):
            problems.append(f"the anchor at seq {a['seq']} covers seq {first}..{last}, which it cannot")
            continue
        expected_first = last + 1
        batch = lines[first:last + 1]
        root = merkle.root([e.get("hash", "") for e in batch]) if all(journal.is_hash(e.get("hash")) for e in batch) else None
        memo = anc.memo_text(root, first, last, batch[-1].get("hash", "")) if root else None
        row["root_ok"] = root == p.get("root") and batch[-1].get("hash") == p.get("head") and memo == p.get("memo")
        if not row["root_ok"]:
            problems.append(f"the Merkle root of seq {first}..{last}, recomputed, is not the root the anchor at seq {a['seq']} states")
        if offline:
            continue
        if p.get("cluster") not in anc.CLUSTERS:
            row["chain"] = "refused"
            problems.append(f"the anchor at seq {a['seq']} names cluster {p.get('cluster')!r}; Knos Record reads devnet or a localnet only")
            continue
        try:
            got = fetch(p.get("tx"), p.get("cluster"))
        except Exception as why:  # noqa: BLE001 - any failure to read is reported, never taken as a pass
            row["chain"] = f"unreadable ({type(why).__name__})"
            problems.append(f"the anchor at seq {a['seq']}: its transaction could not be read from {p.get('cluster')} ({type(why).__name__}: {str(why)[:120]})")
            continue
        if not got.get("found"):
            row["chain"] = "not found"
            problems.append(f"the anchor at seq {a['seq']}: transaction {p.get('tx')} is not on {p.get('cluster')}")
        elif got.get("err") is not None:
            row["chain"] = "failed"
            problems.append(f"the anchor at seq {a['seq']}: transaction {p.get('tx')} failed on chain")
        elif got.get("memo") != memo or memo is None:
            row["chain"] = "mismatch"
            problems.append(f"the anchor at seq {a['seq']}: the memo on chain is not the one recomputed from the file")
        elif p.get("signer") not in (got.get("signers") or []):
            row["chain"] = "wrong signer"
            problems.append(f"the anchor at seq {a['seq']}: {p.get('signer')} did not sign transaction {p.get('tx')}")
        else:
            row["chain"] = "ok"
            row["slot"] = got.get("slot")
            row["block_time"] = got.get("block_time")
    return out


def _check_sibyl(lines: list[dict], store, problems: list[str]) -> dict:
    kept = journal.remembered(store)
    by_seq = {int(e["seq"]): e for e in kept}
    in_file = {int(e["seq"]): e for e in lines if isinstance(e.get("seq"), int)}
    missing_from_file = sorted(s for s in by_seq if s not in in_file)
    missing_from_sibyl = sorted(s for s in in_file if s not in by_seq)
    differs = sorted(s for s in in_file if s in by_seq and journal.canonical(by_seq[s]) != journal.canonical(in_file[s]))
    edited = sorted(s for s, e in by_seq.items() if e.get("hash") != journal.line_hash(e))
    if edited:
        problems.append(f"{len(edited)} line(s) in the memory's journal do not hash to what they say (seq {edited[:5]}): the memory was edited")
    if missing_from_file:
        problems.append(f"the memory's journal holds {len(missing_from_file)} line(s) the file does not (seq {missing_from_file[:5]}): lines were removed")
    if missing_from_sibyl:
        problems.append(f"the file holds {len(missing_from_sibyl)} line(s) the memory's journal never saw (seq {missing_from_sibyl[:5]})")
    if differs:
        problems.append(f"{len(differs)} line(s) differ between the file and the memory's journal (seq {differs[:5]})")
    latest: dict[tuple[str, str], dict] = {}
    for e in lines:
        if e.get("tier") in ("WARM", "REFERENCE"):
            latest[(e["tier"], e["claim"])] = e
    tiers = {"WARM": 0, "REFERENCE": 0}
    for (tier, name), e in latest.items():
        held = store.get(journal.CLAIM_CATEGORY, name) if tier == "WARM" else store.reference(journal.PAPER_PREFIX + name)
        if held.get("_hash") != e["hash"]:
            what = "claim" if tier == "WARM" else "paper"
            problems.append(f"the memory's {tier} {what} {name!r} is not the file's latest line for it (seq {e['seq']})")
        else:
            tiers[tier] += 1
    return {"consulted": True, "cold_events": len(kept), "warm_claims_ok": tiers["WARM"], "reference_papers_ok": tiers["REFERENCE"],
            "missing_from_file": missing_from_file, "missing_from_sibyl": missing_from_sibyl, "differs": differs, "edited": edited}


def _default_fetch(tx: str, cluster: str) -> dict:
    return anc.chain_memo(tx, anc.rpc_url(cluster))


def verify(root=None, *, offline: bool = False, fetch: Callable[[str, str], dict] | None = None, store=None,
           use_sibyl: bool | None = None, signers=None) -> dict:
    """The report: {ok, lines, head, anchored, unanchored, anchors[], sibyl{}, chain_read, problems[]}. `ok` is True
    only when no check found a problem. `store`: a Sibyl store to hold the file to (default: the one beside the file,
    when there is one; use_sibyl=False never consults it). `signers`: the anchoring keys to trust (default
    anchoring.trusted_signers(): KNOS_RECORD_SIGNERS, else the pinned keys); an anchor by any other key is a problem."""
    problems: list[str] = []
    path = journal.journal_path(root)
    try:
        lines = journal.entries(root)
    except journal.RecordError as why:
        return {"ok": False, "path": str(path), "lines": 0, "problems": [str(why)], "anchors": [], "sibyl": {"consulted": False}}
    _check_lines(lines, problems)
    trusted = anc.trusted_signers(signers)
    rows = _check_anchors(lines, fetch or _default_fetch, offline, problems, trusted)
    covered = (int(anc.anchors(lines)[-1]["payload"]["last"]) + 1) if anc.anchors(lines) and rows[-1]["root_ok"] else 0
    sib: dict = {"consulted": False}
    if use_sibyl is not False:
        st = store
        if st is None and (Path(path).parent / "sibyl.db").exists():
            st = journal.sibyl(root)
        if st is not None:
            sib = _check_sibyl(lines, st, problems)
        elif use_sibyl:
            problems.append("a memory store was asked for and there is none beside the file")
    return {"ok": not problems, "path": str(path), "lines": len(lines), "head": lines[-1]["hash"] if lines else journal.GENESIS,
            "anchored": covered, "unanchored": len(lines) - covered, "anchors": rows, "chain_read": not offline,
            "signers": sorted(trusted), "sibyl": sib, "problems": problems}


def lines_of(report: dict) -> list[str]:
    """The report in words."""
    out = [f"Knos Record {report['path']}: {report['lines']} line(s), head {report.get('head', '')[:16]}"]
    for a in report.get("anchors", []):
        out.append(f"  anchor seq {a['seq']}: lines {a['first']}..{a['last']} root {str(a['root'])[:16]} "
                   f"root {'recomputed OK' if a['root_ok'] else 'MISMATCH'}; chain {a['chain']} ({a.get('cluster')} tx {a.get('tx')})")
    if report.get("lines") and not report.get("anchors"):
        out.append("  no anchor: nothing on chain vouches for any line; a rewritten copy would look the same")
    if report.get("unanchored"):
        out.append(f"  {report['unanchored']} line(s) after the last anchor: nothing on chain vouches for them yet")
    s = report.get("sibyl") or {}
    if s.get("consulted"):
        out.append(f"  memory: {s['cold_events']} COLD event(s), {s['warm_claims_ok']} WARM claim(s) and {s['reference_papers_ok']} "
                   "REFERENCE paper(s) agree with the file" if not (s["missing_from_file"] or s["missing_from_sibyl"] or s["differs"] or s["edited"])
                   else "  memory: the memory and the file disagree (see below)")
    else:
        out.append("  memory: not consulted (no store beside the file)")
    if not report.get("chain_read", True):
        out.append("  chain: not read (--offline): the roots were recomputed, not checked against Solana")
    for p in report.get("problems", []):
        out.append(f"  PROBLEM: {p}")
    out.append("OK" if report["ok"] else f"FAILED: {len(report.get('problems', []))} problem(s)")
    return out
