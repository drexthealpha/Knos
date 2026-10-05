"""The terms of each example and the line its evaluation adds to the meter's ledger.

    python examples/outcomes/evaluation.py            prints both for every example
    python examples/outcomes/evaluation.py --write    writes <example>/terms.json and <example>/evaluations.jsonl

Nothing here is new machinery. The terms are `knos.terms` terms in tests mode whose `accept` is the hash of the
black-box bundle (`knos.judge.checks_hash`), so the suite is fixed when the order is funded. An evaluation is a
`knos.ledger.Evaluation`: its id is sha256(order || artifact || policy || milestone), the same four fields whatever
the deliverable is. Two lines per example: the honest submission (accepted) and the cheating one (rejected; a
rejection is an evaluation too, and has its own id because its artifact differs).

What is a sample here and would be real in an order: the buyer and seller ids, the work order (a hash of the
example's name) and the artifact. The meter's artifact field holds 40 characters, the size of a commit id; a
deliverable that is a file reaches the judge in a commit, and that commit is the artifact. These folders are not
commits, so the first 40 hex characters of the hash of the submission's files stand in."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from knos import judge, ledger, terms  # noqa: E402

BUYER, SELLER, MILESTONE = 424242, 555000, 0
EXAMPLES = {       # name: (rate in millionths of a test USDC, the cheating submission, the terms in one sentence)
    "data-labelling": (40_000_000, "cheats/special_cases_visible",
                       "Pays 40 test USDC when labels.csv labels every item of data/items.csv, at least 90% of the 120 held-out gold items "
                       "carry the gold label, no class has recall below 80% on them, and the 40 visible examples do not score more than "
                       "10 points above them; refund after 14 days"),
    "data-transformation": (150_000_000, "cheats/special_cases_visible",
                            "Pays 150 test USDC when transform.sql turns each of 40 seeded, unseen pairs of tables into a ledger with one row "
                            "per customer, every distinct charge counted once, and gross, refunds and net equal to the input's totals to "
                            "the cent; refund after 14 days"),
    "reproducible-research": (90_000_000, "cheats/pasted_result",
                              "Pays 90 test USDC when analysis.py, run again with seed 20261005 on the trial's rows, prints the estimate "
                              "claimed in RESULT.json within 0.000001 minutes, and the estimate moves with the treatment arm when the arm "
                              "is moved; refund after 14 days"),
}


def the_terms(name: str) -> dict:
    return {"accept": judge.checks_hash(HERE / name / "base" / ".knos" / "acceptance" / "1"), "checks": [],
            "deny": [".github/**", ".knos/**"], "mode": "tests", "paths": [], "reserve": 7, "v": 1}


def terms_file(name: str) -> dict:
    t = the_terms(name)
    return {"name": f"outcome-{name}", "sentence": EXAMPLES[name][2],
            "comment": f"/knos fund {EXAMPLES[name][0] // 1_000_000} checks: none",      # what `knos terms show <name>` gives
            "where": "an issue that has this example's .knos/acceptance/<issue>/ on the default branch (bundle 1 here)",
            "terms": t, "terms_json": terms.canonical(t).decode(), "terms_hash": terms.terms_hash(t)}


def order(name: str) -> str:
    return hashlib.sha256(f"knos example work order: outcomes/{name}".encode()).hexdigest()


def artifact(folder: Path) -> str:
    return judge.checks_hash(folder)[:40]


def evaluations(name: str) -> list[ledger.Evaluation]:
    """[the honest submission's, accepted; the cheating one's, rejected], under this example's order and policy."""
    rate, cheat, _ = EXAMPLES[name]
    policy = terms.terms_hash(the_terms(name))
    return [ledger.Evaluation(BUYER, SELLER, order(name), artifact(HERE / name / folder), policy, MILESTONE, accepted, rate)
            for folder, accepted in (("solution", True), (cheat, False))]


def lines(name: str) -> str:
    return "".join(e.line() + "\n" for e in evaluations(name))


def main(argv: list[str]) -> int:
    for name in EXAMPLES:
        if "--write" in argv:
            (HERE / name / "terms.json").write_text(json.dumps(terms_file(name), indent=2) + "\n", encoding="utf-8", newline="\n")
            (HERE / name / "evaluations.jsonl").write_text(lines(name), encoding="utf-8", newline="\n")
        print(f"## {name}\n{EXAMPLES[name][2]}\nterms {terms.terms_hash(the_terms(name))}\n{lines(name)}", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
