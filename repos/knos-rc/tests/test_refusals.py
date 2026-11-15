"""Every refusal has its two sentences (knos.ghwords.REFUSALS): one saying what happened, one saying what to do.

The codes are found where the refusals are made: the programs' error tables (the ones the relay and the site's client
word), the terms' reasons, the payee rule's kinds, the comment parser's outcomes, and every reason the judge and the
neutral re-execution write, read out of their source. A new refusal anywhere without its row fails here.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from knos import ghwords, terms

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "knos"


def _program_codes() -> set[str]:
    from knos.settle import pay as pay1
    from knos.settle.v2 import meter, passkey, passkey_fund, pay, relay
    tables = {"pay": pay.ERRORS, "pay1": pay1.ERRORS, "oidc": relay._VERIFIER, "meter": meter.ERRORS,
              "passkey": {**passkey.ERRORS, **passkey_fund.ERRORS}}
    return {f"{name}.{n}" for name, table in tables.items() for n in table}


def _sdk_codes() -> set[str]:
    """The numbers the site's client words (sdk/settle/index.js `const ERRORS = {`, served as settle.js)."""
    text = (ROOT / "sdk" / "settle" / "index.js").read_text(encoding="utf-8")
    block = text[text.index("const ERRORS = {"):]
    block = block[:block.index("};")]
    return {f"pay.{n}" for n in re.findall(r"^\s*(\d+):", block, re.M)}


def _said(node) -> str | None:
    """A string a refusal is written with, as text: the leftmost literal of a concatenation, an f-string with its
    values as X."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _said(node.left)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
    if isinstance(node, ast.Tuple) and node.elts:       # a parenthesised conditional's first arm
        return _said(node.elts[0])
    if isinstance(node, ast.IfExp):
        return _said(node.body)
    return None


def _reasons(path: Path, functions: tuple[str, ...]) -> list[str]:
    """Every literal reason in `functions`: what is appended to `reasons`, listed in a `verdict(...)`, returned as a
    sentence, or handed over as `why=`."""
    found: list[str] = []
    for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(fn, ast.FunctionDef) or fn.name not in functions:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name == "append" and getattr(getattr(node.func, "value", None), "id", "") == "reasons":
                    found += [_said(a) for a in node.args]
                if name == "verdict" and len(node.args) == 2 and isinstance(node.args[1], (ast.List, ast.ListComp)):
                    items = node.args[1].elts if isinstance(node.args[1], ast.List) else [node.args[1].elt]
                    found += [_said(a) for a in items]
                found += [_said(k.value) for k in node.keywords if k.arg == "why"]
            if isinstance(node, ast.Return) and fn.name in ("_funded_bundle", "_rerun_holds") and node.value is not None:
                for part in ([node.value.body, node.value.orelse] if isinstance(node.value, ast.IfExp) else [node.value]):
                    found.append(_said(part))
    return [f for f in found if f and len(f) > 8]


def test_every_program_error_has_a_row_and_no_row_names_an_error_that_is_gone():
    want = _program_codes() | _sdk_codes()
    have = {c for c in ghwords.REFUSALS if c.split(".")[0] in ("pay", "pay1", "oidc", "meter", "passkey")}
    assert want - have == set(), f"errors with no two sentences: {sorted(want - have)}"
    assert have - want == set(), f"rows for errors no program has: {sorted(have - want)}"
    assert ghwords.program_code("pay", 83) == "pay.83" and ghwords.program_code("pay", 79) is None


def test_every_reason_the_terms_the_payee_rule_and_the_comment_parser_give_has_a_row():
    for state in terms._WHY:
        assert ghwords.code_of_reason(f"terms: required check `unit` {terms._WHY[state]}") == f"terms.check-{state}"
    t = {"accept": "", "checks": [], "deny": [".github/**"], "mode": "merge", "paths": ["src/**"], "reserve": 0, "v": 1}
    assert [ghwords.code_of_reason(r) for r in terms.scope(t, [".github/x.yml", "docs/a.md"])] == ["terms.denied-path", "terms.out-of-scope"]
    assert ghwords.code_of_reason(terms.scope(t, None)[0]) == "terms.files-unread"
    assert ghwords.code_of_reason(terms.scope(t, [f"docs/{i}.md" for i in range(12)])[-1]) == "terms.out-of-scope"
    who = (SRC / "who.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'nobody\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*?,\s*"([a-z]+)"\)', who, re.S)) | {"payee"}   # each nobody(...)'s last argument; payee is its default
    assert {"payee", "assigned", "issue", "unmerged", "unread", "rejected"} <= kinds
    for kind in kinds:
        assert ghwords.code_of_reason(f"{kind}: nobody is paid") == f"who.{kind}", kind
    outcomes = set(re.findall(r'if kind == "([a-z_]+)"', (SRC / "commands.py").read_text(encoding="utf-8"))) - {"understood"}
    assert outcomes and {f"command.{k}" for k in outcomes} <= set(ghwords.REFUSALS), outcomes


def test_every_reason_the_judge_and_the_neutral_re_execution_write_has_a_row():
    judged = _reasons(SRC / "judge.py", ("judge", "_funded_bundle"))
    rerun = _reasons(SRC / "flow.py", ("_rerun_holds", "_rerun_judge"))
    assert len(judged) >= 12 and len(rerun) >= 6, (judged, rerun)          # the reader finds them: an empty list proves nothing
    # a protected path is refused with the words of judge.REFUSALS: every code there has a row of its own here
    from knos import judge
    assert "touches protected path X: X" in judged and len(judge.REFUSALS) == 6
    for code, words in judge.REFUSALS.items():
        assert ghwords.code_of_reason(f"touches protected path tests/x.py: {words}") == ghwords.judge_code(code) and ghwords.judge_code(code) in ghwords.REFUSALS, code
    missing = [r for r in judged + rerun if ghwords.code_of_reason(r) is None]
    assert missing == [], f"reasons with no two sentences: {missing}"
    assert ghwords.code_of_reason("repo rule: CONTRIBUTING.md line 4") == "judge.repo-rule"
    assert ghwords.code_of_reason("touches protected path tests/conftest.py") == "judge.test-config"
    assert ghwords.code_of_reason("touches protected path tests/test_a.py") == "judge.protected-path"
    assert ghwords.code_of_reason("touches protected path pyproject.toml (pytest section)") == "judge.test-config"
    assert ghwords.code_of_reason("no acceptance checks in /w/.knos/acceptance/3") == "judge.no-bundle"
    assert ghwords.code_of_reason("something nobody wrote a row for") is None
    assert ghwords.explain("something nobody wrote a row for")["code"] == "unknown"


def test_each_row_is_two_sentences_of_twelve_words_at_most_and_every_pattern_names_a_row():
    for code, row in ghwords.REFUSALS.items():
        assert re.fullmatch(r"[a-z0-9]+\.[a-z0-9_-]+|unknown", code), code
        assert isinstance(row, tuple) and len(row) == 2, code
        for sentence in row:
            assert sentence and sentence[0].isupper() and sentence.endswith("."), (code, sentence)
            assert len(sentence.split()) <= 12, (code, sentence)
            assert len(re.findall(r"[.!?](?= [A-Z])", sentence)) == 0, f"{code}: one sentence, not two: {sentence}"
    for _pattern, code in ghwords._REASONS:
        assert "\\" in code or code in ghwords.REFUSALS, code
    assert ghwords.said("pass-to-pass broken: tests/test_a.py::test_x") == \
        "A test that passed before your change now fails. Fix the regression the reason names. (`judge.pass-to-pass`)"


def test_the_document_and_the_site_print_the_table_from_the_module():
    doc = (ROOT / "docs" / "reference" / "SUPPLIER.md").read_text(encoding="utf-8")
    assert ghwords.refusal_table() in doc, "docs/reference/SUPPLIER.md is behind the table: python scripts/supplier_docs.py"
    site = json.loads((ROOT / "web" / "refusals.json").read_text(encoding="utf-8"))
    assert site["rows"] == ghwords.refusal_rows(), "web/refusals.json is behind the table: python scripts/supplier_docs.py"


@pytest.mark.parametrize("code", ["judge.protected-path", "pay.83", "appeal.nothing"])
def test_a_code_gives_its_pair_and_an_unknown_code_says_so(code):
    assert ghwords.refusal(code) == ghwords.REFUSALS[code]
    assert ghwords.refusal("nope.1") == ghwords.REFUSALS["unknown"]


def test_a_run_that_could_not_decide_is_said_with_its_row():
    """The third verdict has a row, and the workflow's own sentences about it are that row's first one, not a copy."""
    from knos import flow
    happened, do = ghwords.REFUSALS["rerun.insufficient-evidence"]
    assert happened == "This run could not decide (insufficient evidence)." and "again" in do and "nothing is paid" in do
    assert flow.UNDECIDED == happened[0].lower() + happened[1:-1]
    v = {k: 1 for k in ("order", "repository", "pull", "issue", "head", "base", "accept")} | {"passed": False, "verdict": "insufficient_evidence", "reason": "the suite timed out", "reasons": []}
    why = flow._rerun_holds(v, dict(v))
    assert why.startswith(f"{flow.UNDECIDED}: the suite timed out. ") and ghwords.code_of_reason(why) == "rerun.insufficient-evidence"
    assert ghwords.said(why) == f"{happened} {do} (`rerun.insufficient-evidence`)"
