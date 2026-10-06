"""An outside application decides something from a Knos receipt: show the "Knos-verified" badge, or do not.

    pip install knos
    python show_badge.py receipt.json [--digest <sha256 the receipt was published under>] [--out badge.svg]

It prints one JSON line and exits 0 when the badge may be shown, 1 when it may not. Nothing is asked of Knos and no
network is used: the receipt is checked against its own rules (docs/RECEIPT.md), and the badge is drawn only when
every rule holds and the verdict is `accepted`. A receipt that does not check is `insufficient evidence`, not a
rejection. The badge cannot be bought: this function is the only way to get one.

Your application does the same in four lines:

    from knos import badge
    v = badge.verified(receipt, digest=published_digest)
    if v["issued"]:
        page.add(badge.verified_svg(v), links=[e["url"] for e in v["evidence"]])
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from knos import badge


def decide(receipt: object, digest: str | None = None) -> dict:
    """What to show for one deliverable: {show, verdict, why, receipt, evidence}."""
    v = badge.verified(receipt, digest=digest)
    return {"show": v["issued"], "verdict": v["words"], "why": v["why"], "receipt": v["digest"],
            "evidence": [e["url"] for e in v["evidence"]], "note": v["note"], "_v": v}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Show the Knos-verified badge only for a receipt that checks and says accepted.")
    ap.add_argument("receipt", type=Path, help="an acceptance receipt, as JSON")
    ap.add_argument("--digest", help="the digest the receipt was published under; a receipt that does not hash to it gets no badge")
    ap.add_argument("--out", type=Path, help="where to write the badge (an SVG), when there is one")
    a = ap.parse_args(argv)
    try:
        receipt = json.loads(a.receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        receipt = None
        print(f"cannot read {a.receipt}: {e}", file=sys.stderr)
    d = decide(receipt, a.digest)
    v = d.pop("_v")
    if d["show"] and a.out:
        a.out.write_text(badge.verified_svg(v), encoding="utf-8", newline="\n")
    print(json.dumps(d, sort_keys=True))
    return 0 if d["show"] else 1


if __name__ == "__main__":
    sys.exit(main())
