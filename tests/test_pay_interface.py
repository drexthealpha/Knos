"""crates/knos-pay-interface: what another program funds and reads an order with. Its fixture is what the Python
client and the test build of knos_pay write now, its ids are the deployed program's, it depends on solana-program and
nothing else, and (where cargo is installed) its own tests pass against that fixture."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "crates" / "knos-pay-interface"
FIXTURE = CRATE / "tests" / "fixtures" / "pay_interface.json"


def test_the_fixture_is_what_the_python_client_and_knos_pay_write():
    pytest.importorskip("solders.litesvm")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pay_interface_fixture.py"), "--check"], capture_output=True, text=True, check=False,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    assert r.returncode == 0, r.stderr or r.stdout
    from knos.settle.v2 import pay
    f = json.loads(FIXTURE.read_text(encoding="utf-8"))
    o = pay.read_order(bytes.fromhex(f["order"]["data"]))
    assert o is not None and str(o.address()) == f["order"]["address"] == f["addresses"]["order"]
    assert (o.amount, o.fee, o.state, str(o.source)) == (f["amount"], pay.order_fee(f["amount"]), "open", f["funder"])
    assert {i["name"] for i in f["instructions"]} == {"fund_order_wallet", "fund_order_wallet_private", "top_up", "top_up_from", "refund_order",
                                                      "refund_order_to"}
    assert [bytes.fromhex(i["data"])[0] for i in f["instructions"]] == [15, 15, 23, 23, 22, 22]


def test_the_crate_names_the_deployed_program_and_depends_on_solana_program_only():
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    lib = (CRATE / "src" / "lib.rs").read_text(encoding="utf-8")
    assert f'pub const ID: Pubkey = pubkey!("{ids["knos_pay"]}");' in lib and f'pub const ID_STR: &str = "{ids["knos_pay"]}";' in lib
    assert f'pub const FEE_OWNER: Pubkey = pubkey!("{ids["fee_owner"]}");' in lib
    manifest = (CRATE / "Cargo.toml").read_text(encoding="utf-8")
    deps = [line.split("=")[0].strip() for line in manifest.split("[dependencies]")[1].split("[dev-dependencies]")[0].splitlines()
            if line.strip() and not line.startswith("#")]
    assert deps == ["solana-program"], deps
    # released with the Python package, under its version; the install line names that tag
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    assert re.search(r'^version = "([^"]+)"', manifest, re.M).group(1) == version
    readme = (CRATE / "README.md").read_text(encoding="utf-8")
    assert re.search(r'git = "https://github.com/drexthealpha/Knos", tag = "v([^"]+)"', readme).group(1) == version
    assert ids["knos_pay"] not in readme or "ID" in readme
    # the program's own constants: a price here that is not the program's would quote a funder the wrong fee
    src = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    for name in ("FEE_BPS", "ORDER_FEE_MIN", "ORDER_FEE_MAX", "ORDER_MIN_AMOUNT", "MAX_AMOUNT", "MIN_WORK", "MAX_TERMS"):
        value = lambda text: re.search(rf"pub const {name}: \w+ = ([\d_]+);", text).group(1)  # noqa: E731
        assert value(lib) == value(src), name


def test_the_crates_own_tests_pass_against_the_fixture():
    cargo = shutil.which("cargo")
    if not cargo:
        pytest.skip("needs cargo")
    r = subprocess.run([cargo, "test", "--locked", "--quiet"], cwd=str(CRATE), capture_output=True, text=True, check=False)
    if r.returncode != 0 and ("failed to get" in r.stderr or "could not download" in r.stderr.lower()):
        pytest.skip("cargo could not fetch the crate's dependencies here")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "3 passed" in r.stdout
