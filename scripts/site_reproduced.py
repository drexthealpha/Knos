"""L16: which papers' results Knos has reproduced, as docs/data/reproduced.json, the file the Papers page (papers/) is built
from. A paper's result counts as reproduced when the public record holds a paid run of its locked test: the claim board
of the hosted server (GET /api/near/claims, read from NEAR testnet) shows a last proof, or at least one payment that the
jobs contract makes only for a passing output (`proofs`). Nothing is typed by hand; with no answer the file is not
rewritten.

    python scripts/site_reproduced.py            # read the board and write docs/data/reproduced.json
    python scripts/site_reproduced.py --board f  # the same from a saved answer of /api/near/claims
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "reproduced.json"
BOARD = "https://knos.onrender.com/api/near/claims"


def from_board(board: dict) -> dict:
    claims = json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
    seen = board.get("claims") or {}
    rows = {}
    for c in claims:
        b = seen.get(c["name"]) or {}
        proofs = int(b.get("proofs") or 0)
        rows[c["name"]] = {"reproduced": bool(proofs > 0 or b.get("last_proof")), "paid_runs": proofs, "last_proof": b.get("last_proof")}
    return {"_": "Written by scripts/site_reproduced.py from the claim board of the hosted server, read from NEAR testnet. "
                 "reproduced: a paid run of the claim's locked test is on the public record (a last proof, or paid_runs above 0).",
            "source": BOARD, "read_at": board.get("read_at"), "claims": rows}


def main(argv: list[str]) -> int:
    if argv[:1] == ["--board"]:
        board = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    else:
        try:
            with urllib.request.urlopen(BOARD, timeout=90) as r:
                board = json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError) as e:
            print(f"the board did not answer ({e}); docs/data/reproduced.json is kept")
            return 1
    if not board.get("claims"):
        print("the board holds no claims; docs/data/reproduced.json is kept")
        return 1
    data = from_board(board)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"reproduced: {sum(v['reproduced'] for v in data['claims'].values())} of {len(data['claims'])}, read {data['read_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
