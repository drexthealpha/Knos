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


# == the charter (docs/CHARTER.md) ==================================================================================
# Each right the charter calls "enforced" names one test below (or one elsewhere in tests/); the last two tests hold
# the page to that and to its own sha256.
PAY = PROGRAMS / "knos_pay" / "src"
CHARTER = ROOT / "docs" / "CHARTER.md"


def _fn(path: Path, name: str) -> str:
    """The body of one Rust function, from its signature to the closing brace at the start of a line."""
    parts = re.split(rf"pub fn {name}[<(]", path.read_text(encoding="utf-8"), maxsplit=1)
    assert len(parts) == 2, f"{path.name}: no function {name}"
    return parts[1].split("\n}\n", 1)[0]


def test_the_refund_needs_no_token_and_no_pause_can_stop_it():
    for path, name in ((PAY / "pay.rs", "refund"), (PAY / "order_pay.rs", "refund_order")):
        body = _fn(path, name)
        accounts = body.split("take(accounts)", 1)[0]
        assert "pause" not in body and "not_paused" not in body, f"{name} reads the pause"
        assert not re.search(r"\b(tok|key)\b", accounts), f"{name} takes a token or a signing key: {accounts.strip()}"
        assert "now > " in body, f"{name} waits for the deadline only"
    # the kill fee paid on the way out reads no pause either
    assert "pause" not in _fn(PAY / "order_pay.rs", "refund_first")
    # the pause is read only where new money comes in
    for path in PAY.glob("*.rs"):
        for n, code in _code(path):
            if "not_paused(" in code and "pub fn not_paused" not in code:
                fn = path.read_text(encoding="utf-8").splitlines()[:n]
                head = next(line for line in reversed(fn) if line.startswith("pub fn "))
                assert re.match(r"pub fn (fund|faucet|top_up|open|order_fund)\w*\(", head), f"{path.name}:{n}: {head}"


def test_the_fee_never_exceeds_the_rate_or_its_floor():
    lib = (PAY / "lib.rs").read_text(encoding="utf-8")
    assert "pub const FEE_BPS: u64 = 30;" in lib and "pub const FEE_MIN: u64 = 50_000;" in lib
    for amount in (1, 49_999, 50_000, 5 * 10**6, 16_666_666, 16_666_667, 100 * 10**6, 10**9, 5_000 * 10**6, 100_000 * 10**6):
        cap = max(amount * 30 // 10_000, 50_000)
        assert pay.order_fee(amount) <= cap and pay.fee_of(amount) <= min(cap, amount), amount
        assert pay.order_fee(amount, 10) <= pay.order_fee(amount), amount       # a Plan only lowers it


def test_an_orders_fee_is_paid_on_top_and_never_taken_from_its_payees():
    fund, order, paid = ((PAY / f).read_text(encoding="utf-8") for f in ("fund.rs", "order.rs", "order_pay.rs"))
    assert "f.amount + order_fee(f.amount, FEE_BPS, m.decimals)" in fund                          # the faucet's order
    assert "f.amount.checked_add(order_fee(f.amount, bps, m.decimals))" in order                  # a wallet's or a Balance's
    # the payees share `due`, a part of the amount; the fee is the order's stored fee, paid apart
    assert "let share = if k + 1 == payees.len() { due - sent } else { bps_of(due, payee.bps) };" in paid
    assert "let fee_before = (o.fee as u128 * o.paid as u128 / o.amount as u128) as u64;" in paid
    # the exception the charter names: a job (the older path) takes its fee out of its amount
    assert "let net = j.amount - fee;" in (PAY / "pay.rs").read_text(encoding="utf-8")


def test_an_open_order_keeps_the_rate_it_was_funded_at():
    order = (PAY / "order.rs").read_text(encoding="utf-8")
    # a top-up charges the rate stored in the order, never more than today's, and never less than the fee it holds
    assert "let fee = order_fee(amount, (o.fee_bps as u64).min(FEE_BPS), m.decimals).max(o.fee);" in order
    # a payment pays out the fee the order holds: nothing reads today's rate after the funding
    assert "order_fee(" not in _fn(PAY / "order_pay.rs", "pay_order") and "FEE_BPS" not in (PAY / "order_pay.rs").read_text(encoding="utf-8")


def _charter_lines() -> list[str]:
    return [line for line in CHARTER.read_text(encoding="utf-8").splitlines() if line.startswith("| ") and "Enforced" in line]


def _test_exists(ref: str) -> bool:
    path, _, name = ref.partition("::")
    file = ROOT / path
    if not file.is_file():
        return False
    tree = ast.parse(file.read_text(encoding="utf-8"))
    return any(isinstance(n, ast.FunctionDef) and n.name == name and name.startswith("test_") for n in ast.walk(tree))


def test_every_enforced_right_of_the_charter_names_a_test_that_exists():
    lines = _charter_lines()
    assert len(lines) >= 6, lines
    for line in lines:
        refs = re.findall(r"`(tests/[\w/]+\.py::\w+)`", line)
        assert refs, f"an enforced right names no test: {line}"
        for ref in refs:
            assert _test_exists(ref), f"{ref} is not a test: {line}"
    promises = [line for line in CHARTER.read_text(encoding="utf-8").splitlines() if "Promise, not yet enforced" in line]
    assert promises, "the charter says which rights are promises only"
    for line in promises:
        assert not re.search(r"`tests/", line), f"a promise names a test as if it were enforced: {line}"


def test_the_charter_footer_is_the_sha256_of_the_text_above_it():
    import hashlib
    import subprocess
    import sys
    text = CHARTER.read_bytes()
    marker = b"\n---\n\nsha256 of everything above this line: `"
    assert text.count(marker) == 1, "the footer is written by scripts/charter_hash.py"
    body, foot = text.split(marker)
    assert foot[:64].decode() == hashlib.sha256(body + b"\n").hexdigest(), "run python scripts/charter_hash.py"
    got = subprocess.run([sys.executable, str(ROOT / "scripts" / "charter_hash.py"), "--check"], capture_output=True, encoding="utf-8", timeout=60)
    assert got.returncode == 0, got.stdout + got.stderr
