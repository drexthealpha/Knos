"""Knos is paid on acceptance and does not decide it (docs/DISPUTES.md, "Knos is paid on acceptance, and does not
decide it"). Three things are checked on the source itself, with no network:

- in the programs, Knos's fee account (FEE_OWNER) only receives fees and signs SetPlan, which lowers a rate: no
  line lets it sign a verdict, pick a payee or move an order; the verifier and the passkey wallet never name it;
- the modules that make verdicts import nothing that knows a fee, a price or Knos's account;
- the fee function takes the amount and the rate only, in the program and in the Python model: the same for every
  accepted dollar, whoever accepted it.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from knos.settle.v2 import pay

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / "programs-v2"
# every way a line of program code may name FEE_OWNER: declare it, check that a token account it receives fees in is
# FEE_OWNER's, check that SetPlan's signer is FEE_OWNER, or assert at compile time that it is not a counted mint
ALLOWED = [
    re.compile(r"pub const FEE_OWNER: Pubkey = pubkey!\(\"\w+\"\);"),
    re.compile(r"is_owned\((a\.)?fee_tok, [\w.]+, &\w\.mint, &FEE_OWNER\)"),
    re.compile(r"\*fee_owner\.key != FEE_OWNER"),
    re.compile(r"!counted\(&FEE_OWNER\)"),
]
VERDICT_MODULES = ["judge", "accept", "policy", "verdict_gate", "host_judge"]
FEE_MODULES = {"fees", "billing", "settle", "price", "pricing", "meter", "netting", "advance", "rails", "statement"}


def _code(path: Path) -> list[tuple[int, str]]:
    """The lines of a Rust file without their comments."""
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        code = line.split("//", 1)[0]
        if code.strip():
            out.append((n, code))
    return out


def test_knos_fee_account_only_receives_fees_and_lowers_a_rate():
    named = []
    for path in sorted(PROGRAMS.glob("*/src/**/*.rs")):
        for n, code in _code(path):
            if not re.search(r"(?<![\w])FEE_OWNER(?![\w])", code):
                continue
            rel = f"{path.relative_to(ROOT)}:{n}"
            named.append(rel)
            rest = code
            for allowed in ALLOWED:
                rest = allowed.sub("", rest)
            assert not re.search(r"(?<![\w])FEE_OWNER(?![\w])", rest), f"{rel}: FEE_OWNER is used for something else: {code.strip()}"
            assert path.parts[-3] in ("knos_pay", "knos_meter"), f"{rel}: only the escrow and the meter name Knos's account"
    # it is named where fees are received (jobs, orders, the holdback's release, the meter) and where a Plan is set
    assert len(named) >= 6, named
    for program in ("knos_oidc", "knos_passkey"):
        for path in (PROGRAMS / program / "src").rglob("*.rs"):
            assert "FEE_OWNER" not in path.read_text(encoding="utf-8"), path


def test_set_plan_only_lowers_the_rate():
    lib = (PROGRAMS / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    fund = (PROGRAMS / "knos_pay" / "src" / "fund.rs").read_text(encoding="utf-8")
    low = int(re.search(r"pub const PLAN_BPS_MIN: u64 = (\d+);", lib).group(1))
    rate = int(re.search(r"pub const FEE_BPS: u64 = (\d+);", lib).group(1))
    assert 0 < low <= rate
    plan = fund.split("pub fn set_plan(")[1].split("\n}\n")[0]
    assert "!(PLAN_BPS_MIN..=FEE_BPS).contains(&(bps as u64))" in plan, "SetPlan refuses a rate above FEE_BPS"
    assert "(u16_at(&d, P_BPS) as u64).clamp(PLAN_BPS_MIN, FEE_BPS)" in fund, "a Plan is read back clamped to FEE_BPS"


def _imports(module: str) -> set[str]:
    tree = ast.parse((ROOT / "src" / "knos" / f"{module}.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            found.add(base)
            found |= {f"{base}.{a.name}".strip(".") for a in node.names}
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r"knos(\.\w+)+", node.value):
            found.add(node.value)
    return found


def test_the_modules_that_make_verdicts_know_no_fee_and_no_account_of_knos():
    for module in VERDICT_MODULES:
        source = (ROOT / "src" / "knos" / f"{module}.py").read_text(encoding="utf-8")
        for name in _imports(module):
            parts = set(name.replace("knos.", "").split("."))
            assert not parts & FEE_MODULES, f"knos.{module} imports {name}"
        for word in ("FEE_OWNER", "fee_owner", "order_fee", "fee_of", "FEE_BPS"):
            assert word not in source, f"knos.{module} names {word}"


def test_the_fee_reads_the_amount_and_the_rate_only():
    assert list(inspect.signature(pay.order_fee).parameters) == ["amount", "bps", "decimals"]
    assert list(inspect.signature(pay.fee_of).parameters) == ["amount", "decimals"]
    lib = (PROGRAMS / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "pub fn order_fee(amount: u64, bps: u64, decimals: u8) -> u64" in lib
    assert "pub fn fee_of(amount: u64, decimals: u8) -> u64" in lib
    # the same rate for every accepted dollar: twice the amount is twice the fee above the floor
    amount = 1_000 * 10**6
    assert pay.order_fee(2 * amount) == 2 * pay.order_fee(amount)


def test_the_page_says_what_the_test_checks():
    page = " ".join((ROOT / "docs" / "DISPUTES.md").read_text(encoding="utf-8").split())
    section = page.split("## Knos is paid on acceptance, and does not decide it")[1].split(" ## ")[0]
    assert "tests/test_neutrality.py" in section and "No key of Knos's signs a verdict." in section
    for module in VERDICT_MODULES:
        assert f"`knos.{module}`" in section, module
    assert "there is no default" in section and "48-hour" in section
