"""What the site's "Fund any issue" card (web/anyissue.js) is held to: the terms it fixes and the instruction it asks the client for.

Python is the reference. The terms are made by src/knos/terms.py (`canonical`, `terms_hash`, `describe`) from the names and globs as a
funder types them (src/knos/commands.py reads a list the same way), and the funding instruction by src/knos/settle/v2/pay.py
(`fund_order_wallet_ix`), for the wallet and the issue tests/web/site.mjs uses. tests/web/site.mjs gives the page the same boxes and
holds the terms it shows, their hash, the arguments it hands the client and the transaction its wallet is given to these answers.
Written by `python tests/test_fund_any_issue.py`; the test below fails when the file is not what this makes."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from solders.pubkey import Pubkey  # noqa: E402

from knos import commands, terms as T  # noqa: E402
from knos.settle.v2 import pay as P  # noqa: E402

RECORDED = ROOT / "tests" / "web" / "recorded" / "fund_any_issue.json"
IDS = json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text(encoding="utf-8"))
PAY = Pubkey.from_string(IDS["knos_pay"])
USDC = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
WF_REPO, WF_SHA = "drexthealpha/knos-workflows", "a" * 40            # the pin tests/web/site.mjs stamps into the page's workflow file
REPO_ID, ISSUE, AMOUNT, WORK_S = 5550001, 7, 20_000_000, 14 * 86_400

NOTE = ("Made by tests/test_fund_any_issue.py: the terms from src/knos/terms.py for the boxes as a funder types them, and the funding instruction "
        "from src/knos/settle/v2/pay.py fund_order_wallet_ix, for the wallet and the issue tests/web/site.mjs uses (unique(1), octo/widgets#7). "
        "tests/web/site.mjs holds web/anyissue.js to these answers. Written by `python tests/test_fund_any_issue.py`.")

# what a funder types in the two boxes, and what the page must make of each
CASES = [
    ("no check, no path", "", ""),
    ("two named checks, two paths", "test, lint", "src/**, docs/*.md"),
    ("a comma inside brackets belongs to the name; a quoted name is taken whole", "test (ubuntu, 3.12), `quoted, name`, lint", "./src/**, /docs/"),
    ("a name with letters outside ASCII, and one outside the BMP, and a repeat", "tést, build \U0001F600, tést", "src/ünï/**"),
    ("a check that is not Knos's own but starts like it", "knowledge base", ""),
]


def wallet(n: int) -> Pubkey:
    """tests/web/site.mjs `unique(n)`"""
    return Pubkey.from_bytes(bytes((n * 31 + i * 5) % 256 for i in range(32)))


def names_of(text: str) -> list[str]:
    items, _ = commands._list(text, 0)
    return items


def globs_of(text: str) -> list[str]:
    import re
    items, _ = commands._list(text, 0)
    return list(dict.fromkeys(T.valid_glob(re.sub(r"^(?:\./|/)+", "", g)) for g in items))


def terms_for(checks: list[str], paths: list[str]) -> dict:
    return {"accept": "", "checks": [{"app": T.ANY, "name": n} for n in checks], "deny": list(T.DENY), "mode": "merge", "paths": paths, "reserve": 0, "v": 1}


def ix_json(ix) -> dict:
    return {"program": str(ix.program_id), "data": bytes(ix.data).hex(),
            "accounts": [{"pubkey": str(a.pubkey), "signer": a.is_signer, "writable": a.is_writable} for a in ix.accounts]}


def recorded() -> dict:
    cases = []
    for name, checks_text, paths_text in CASES:
        checks, paths = names_of(checks_text), globs_of(paths_text)
        terms = terms_for(checks, paths)
        data = T.canonical(terms)
        cases.append({"name": name, "checks_text": checks_text, "paths_text": paths_text, "checks": checks, "paths": paths, "text": data.decode("ascii"),
                      "sha256": hashlib.sha256(data).hexdigest(), "describe": T.describe(T.parse(data), "funder")})
    funder, funder_token = wallet(1), P.ata(wallet(1), USDC)
    terms = T.canonical(terms_for(["test"], ["src/**"]))
    options = P.opts(flags=P.F_NEUTRAL)
    orders, ixs = {}, {}
    for seq in (0, 1):
        ix = P.fund_order_wallet_ix(funder, funder_token, USDC, REPO_ID, ISSUE, AMOUNT, WF_REPO, WF_SHA, terms, mode=P.MERGE, work_s=WORK_S, seq=seq, options=options, program=PAY)
        ixs[str(seq)] = ix_json(ix)
        orders[str(seq)] = str(P.order_pda(P.scope_of(REPO_ID, ISSUE), funder, seq, PAY))
    return {"note": NOTE, "terms": cases,
            "order": {"args": {"funder": str(funder), "funderToken": str(funder_token), "mint": str(USDC), "repoId": REPO_ID, "issue": ISSUE, "amount": AMOUNT, "wfRepo": WF_REPO,
                               "wfSha": WF_SHA, "terms": terms.decode("ascii"), "mode": P.MERGE, "workS": WORK_S, "options": options.hex()},
                     "scope": P.scope_of(REPO_ID, ISSUE).hex(), "orders": orders, "ix": ixs,
                     "fee": P.order_fee(AMOUNT), "terms_checks": ["test"], "terms_paths": ["src/**"], "terms_sha256": hashlib.sha256(terms).hexdigest(),
                     "describe": T.describe(T.parse(terms), "funder")}}


def test_the_recorded_answers_are_what_the_python_reference_makes():
    got = recorded()
    assert json.loads(RECORDED.read_text(encoding="utf-8")) == json.loads(json.dumps(got)), "regenerate: python tests/test_fund_any_issue.py"
    by = {c["name"]: c for c in got["terms"]}
    assert by["no check, no path"]["text"] == '{"accept":"","checks":[],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":0,"v":1}'
    assert by["a comma inside brackets belongs to the name; a quoted name is taken whole"]["checks"] == ["test (ubuntu, 3.12)", "quoted, name", "lint"]
    assert by["a comma inside brackets belongs to the name; a quoted name is taken whole"]["paths"] == ["src/**", "docs/"]
    assert by["a name with letters outside ASCII, and one outside the BMP, and a repeat"]["checks"] == ["tést", "build \U0001F600"]
    assert "\\ud83d\\ude00" in by["a name with letters outside ASCII, and one outside the BMP, and a repeat"]["text"]
    assert got["order"]["ix"]["0"]["data"][:2] == "0f" and got["order"]["fee"] == 500_000


if __name__ == "__main__":
    RECORDED.write_text(json.dumps(recorded(), indent=1) + "\n", encoding="utf-8")
    print("wrote", RECORDED)
