"""web/buyer_templates.json: the five terms templates as the Buy page shows them, written from src/knos/terms_templates.py.

    python scripts/buyer_templates.py            write web/buyer_templates.json
    python scripts/buyer_templates.py --check    exit 1 when the file is not what this would write

For each template: its sentence and comment (knos.terms_templates), the parts they are made of (so the page can put
the buyer's own amount, days, checks and paths in, with web/buyer.js's sentenceOf and commentOf; tests hold those two
to this file's sentence and comment), how it is judged (in-process, black-box or hermetic: knos.terms.ASSURANCE) and
what a buyer still has to trust in that mode (knos.receipt.trust_of, the list a paid order's receipt ends with).
`passkey` says whether the page can fund it from a passkey wallet: only a merge-mode order with no vendor and no
policy, because its terms need no fact of the repository that a browser cannot read.

`procurement` is what the console's Offers, Budgets, Approvals and Invoice screens start from: where the files live
in a buyer's repository, the hash of each published terms template (what a rate card must cite), and one made-up
organisation's files, approvals and one deliverable (knos.controls.sample, knos.approvals), shown until a repository
is named.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knos import approvals, commands, controls, receipt, terms_templates as tt  # noqa: E402
from knos.terms import ASSURANCE  # noqa: E402

OUT = ROOT / "web" / "buyer_templates.json"
TITLES = {"bugfix": "A bug fix", "feature-blackbox": "A feature, checked black-box", "milestone": "A milestone with a warranty",
          "standing-rate": "A rate per accepted pull request", "private-attested": "Work in a private repository"}
# what the acceptance itself leaves to trust, before the list every receipt carries
_MERGE = ("The named checks are your repository's own CI. Plain CI passed 56 of 63 cheating pull requests in Knos's tamper suite "
          "(docs/TAMPER.md), so the checks alone are not the acceptance: a maintainer's merge is.")
_NOT_PASSKEY = {"tests": "its terms carry the hash of your acceptance suite, which this page cannot read from your repository",
                "vendor": "a standing offer is funded from the organisation's Balance, by comment",
                "policy": "a private order is funded by the organisation's attestor repository, by comment"}


def one(name: str) -> dict:
    t = tt.get(name)
    cmd, tm, ex = tt.command(t), tt.terms_of(t), tt.export(name)
    offer = isinstance(cmd, commands.Offer)
    mode = "black-box" if tm["mode"] == "tests" else "in-process"
    why = _NOT_PASSKEY["tests"] if tm["mode"] == "tests" else _NOT_PASSKEY["vendor"] if offer else _NOT_PASSKEY["policy"] if t.policy else ""
    parts = {"kind": "offer" if offer else "fund", "mode": tm["mode"], "checks": list(cmd.checks or ()), "paths": list(cmd.paths or ()),
             "amount": commands.amount(cmd.budget if offer else cmd.units), "rate": commands.amount(cmd.rate) if offer else "",
             "vendor": cmd.vendor if offer else "", "holdback": int(getattr(cmd, "holdback", None) or 0), "warranty": int(getattr(cmd, "warranty", None) or 0),
             "days": cmd.days, "private": bool(t.policy)}
    return {"name": name, "title": TITLES[name], "sentence": ex["sentence"], "comment": ex["comment"], "where": ex["where"], "parts": parts,
            "assurance": mode, "trusted": [ASSURANCE[mode] if mode != "in-process" else _MERGE, *receipt.trust_of("github", tm["mode"], "repository")],
            "passkey": not why, "passkey_why_not": why}


def build() -> str:
    doc = {"note": "Written by scripts/buyer_templates.py from src/knos/terms_templates.py. Do not edit by hand.", "money": commands.MONEY,
           "default_days": 14, "assurance": dict(ASSURANCE), "templates": [one(name) for name in tt.TEMPLATES],
           "procurement": {"directory": controls.PROCUREMENT, "files": dict(controls.FILES), "terms": controls.published_terms(),
                           "sample": {**controls.sample(), "approvals": approvals.sample_events(), "deliverable": approvals.sample_deliverable()}}}
    return json.dumps(doc, indent=1, ensure_ascii=True) + "\n"


if __name__ == "__main__":
    text = build()
    if "--check" in sys.argv[1:]:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            raise SystemExit("web/buyer_templates.json is stale: run python scripts/buyer_templates.py")
    else:
        OUT.write_text(text, encoding="utf-8", newline="")
