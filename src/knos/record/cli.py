"""The Knos Record commands, reached through `knos record ...` (knos.badge routes them here) or `python -m knos.record`.

    knos record verify [DIR|journal.jsonl] [--offline] [--json] [--no-sibyl]
    knos record anchor [DIR] [--keypair FILE] [--dry-run]
    knos record journal [DIR] [--json] [--claim ID] [--kind KIND]
    knos record prove SEQ [DIR]        the Merkle audit path of one line in its anchored batch
    knos record search QUERY [--root DIR] [--limit N] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys

from . import anchoring as anc
from . import journal, merkle
from . import verifier as ver


def _prove(root, seq: int) -> dict:
    lines = journal.entries(root)
    for a in anc.anchors(lines):
        p = a["payload"]
        if int(p["first"]) <= seq <= int(p["last"]):
            batch = [e["hash"] for e in lines[int(p["first"]):int(p["last"]) + 1]]
            i = seq - int(p["first"])
            path = merkle.proof(batch, i)
            return {"seq": seq, "hash": lines[seq]["hash"], "index": i, "size": len(batch), "path": path, "root": p["root"],
                    "anchor_seq": a["seq"], "tx": p["tx"], "cluster": p["cluster"],
                    "checks": merkle.check_proof(lines[seq]["hash"], i, len(batch), path, p["root"])}
    raise journal.RecordError(f"no anchor covers seq {seq} yet: run knos record anchor")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="knos record", description="Knos Record: the append-only, hash-chained, devnet-anchored record.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="recompute every hash and Merkle root and check them against Solana and the memory engine")
    v.add_argument("path", nargs="?", default=None)
    v.add_argument("--offline", action="store_true", help="do not read the chain; recompute only")
    v.add_argument("--no-sibyl", action="store_true", help="do not consult the memory store beside the file")
    v.add_argument("--signer", action="append", default=[], help="an anchoring public key to trust (repeat it). To verify YOUR OWN record, pass the public key of the wallet that anchored it "
                        "(knos record anchor's signer), or set KNOS_RECORD_SIGNERS=<key>[,<key>...]. Default: KNOS_RECORD_SIGNERS, else Knos's pinned key 8aukezen..")
    v.add_argument("--json", action="store_true")
    a = sub.add_parser("anchor", help="put the Merkle root of the unanchored lines on Solana devnet (SPL Memo)")
    a.add_argument("path", nargs="?", default=None)
    a.add_argument("--keypair", default=None, help="a funded devnet wallet (solana-keygen file); else KNOS_RECORD_KEY")
    a.add_argument("--dry-run", action="store_true", help="say what would be anchored; send and write nothing")
    j = sub.add_parser("journal", help="print the record's lines")
    j.add_argument("path", nargs="?", default=None)
    j.add_argument("--claim", default=None)
    j.add_argument("--kind", default=None)
    j.add_argument("--json", action="store_true")
    s = sub.add_parser("search", help="search the record in the memory engine (every tier), with the reason for what came back")
    s.add_argument("query")
    s.add_argument("--root", default=None, help="the record's folder (default: the one `knos record journal` reads)")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    p = sub.add_parser("prove", help="the Merkle audit path of one line")
    p.add_argument("seq", type=int)
    p.add_argument("path", nargs="?", default=None)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "verify":
            rep = ver.verify(args.path, offline=args.offline, use_sibyl=False if args.no_sibyl else None, signers=args.signer)
            print(json.dumps(rep, indent=1) if args.json else "\n".join(ver.lines_of(rep)))
            return 0 if rep["ok"] else 1
        if args.cmd == "anchor":
            got = anc.anchor(args.path, keypair=args.keypair, dry_run=args.dry_run)
            if got is None:
                print("Nothing to anchor: every line is already under an anchor.")
            elif args.dry_run:
                print(f"Would anchor seq {got['first']}..{got['last']} ({got['count']} line(s)), root {got['root']}. Memo: {got['memo']}")
            else:
                pl = got["payload"]
                print(f"Anchored seq {pl['first']}..{pl['last']} ({pl['count']} line(s)) on {pl['cluster']}: root {pl['root']}, "
                      f"transaction {pl['tx']}, signed by {pl['signer']}. Anchor line seq {got['seq']}.")
            return 0
        if args.cmd == "journal":
            rows = [e for e in journal.entries(args.path) if (args.claim is None or e.get("claim") == args.claim)
                    and (args.kind is None or e.get("kind") == args.kind)]
            for e in rows:
                print(json.dumps(e, sort_keys=True) if args.json else
                      f"{e['seq']:>6} {e['ts']} {e['tier']:<9} {e['kind']:<12} {e.get('claim') or '-':<24} {e['hash'][:16]}")
            return 0
        if args.cmd == "search":
            from .search import search
            got = search(args.query, args.root, limit=args.limit)
            if args.json:
                print(json.dumps(got, indent=1, default=str))
            else:
                print(got["said"])
                for r in got["rows"]:
                    line = ((r.get("body") or {}).get("extra") or {}).get("record") if isinstance(r.get("body"), dict) else None
                    print("  " + (f"seq {line['seq']} {line['kind']} {line.get('claim') or '-'} {json.dumps(line.get('payload'), sort_keys=True)}"
                                  if isinstance(line, dict) and "seq" in line else json.dumps(r, sort_keys=True, default=str))[:300])
                st = got.get("store") or {}
                if st.get("pct_used") is not None:
                    print(f"Memory store: {st['db_size_bytes']} bytes, {100 * st['pct_used']:.1f}% of the {st['tier']} tier's soft cap.")
            return 0
        if args.cmd == "prove":
            print(json.dumps(_prove(args.path, args.seq), indent=1))
            return 0
    except (journal.RecordError, anc.AnchorError) as why:
        print(f"knos record {args.cmd}: {why}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
