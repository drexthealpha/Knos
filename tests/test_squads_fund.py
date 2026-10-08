"""scripts/squads_fund.mjs, offline: the instruction its dry run prints for a Squads vault is, byte for byte, the
FundOrderWallet the Python client builds with that vault as the funder (the instruction LiteSVM accepts from a wallet,
and from a PDA in tests/test_cpi_fund.py), and what it says the vault is debited is the program's arithmetic."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from knos import mainnet_check as mc
from knos.settle.v2 import oidc, pay

ROOT = Path(__file__).resolve().parents[1]
TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "mode": "merge", "v": 2})
MULTISIG, MINT = Pubkey.from_string(oidc.IDS["upgrade_multisig"]), pay.USDC_DEVNET
ARGS = ["--multisig", str(MULTISIG), "--repo-id", "987654321", "--issue", "77", "--amount", "20000000", "--mint", str(MINT), "--wf-repo", "drexthealpha/Knos",
        "--wf-sha", "c" * 40, "--seq", "2", "--work-days", "7"]


def _run(*args: str, terms: str, env: dict | None = None):
    node = shutil.which("node")
    if not node or not (ROOT / "scripts" / "node_modules" / "@sqds" / "multisig").is_dir():
        pytest.skip("needs Node 20 and the packages: npm ci --prefix scripts")
    return subprocess.run([node, "scripts/squads_fund.mjs", *args, "--terms", terms], cwd=ROOT, capture_output=True, text=True, timeout=120,
                          env=env if env is not None else {k: v for k, v in os.environ.items() if k != "KNOS_PROGRAM_IDS"})


def test_the_dry_run_prints_the_python_clients_instruction_for_the_vault(tmp_path):
    (tmp_path / "terms.json").write_text(TERMS.decode() + "\n", encoding="utf-8")
    done = _run(*ARGS, terms=str(tmp_path / "terms.json"))
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    vault = mc.vault_address(MULTISIG, Pubkey.from_string(oidc.IDS["squads_program"]))
    assert out["dry_run"] is True and out["vault"] == str(vault) == oidc.IDS["upgrade_authority"]
    want = pay.fund_order_wallet_ix(vault, pay.ata(vault, MINT), MINT, 987654321, 77, 20_000_000, "drexthealpha/Knos", "c" * 40, TERMS, pay.MERGE, 7 * 86_400, 2)
    assert out["instruction"] == {"program": str(pay.PAY_ID), "data": bytes(want.data).hex(),
                                  "accounts": [{"pubkey": str(a.pubkey), "signer": a.is_signer, "writable": a.is_writable} for a in want.accounts]}
    assert (out["order"], out["order_token"], out["vault_token"]) == (str(want.accounts[1].pubkey), str(want.accounts[2].pubkey), str(pay.ata(vault, MINT)))
    assert (out["amount"], out["fee"], out["debit"]) == ("20000000", str(pay.order_fee(20_000_000)), str(20_000_000 + pay.order_fee(20_000_000)))
    assert out["terms_sha256"] == pay.terms_hash(TERMS).hex() and out["refundable_after_seconds"] == 7 * 86_400
    # the terms given inline are the same order
    assert json.loads(_run(*ARGS, terms=TERMS.decode()).stdout)["instruction"] == out["instruction"]


def test_with_knos_program_ids_set_the_order_is_built_for_that_staging_knos_pay_and_nothing_else_can_change(tmp_path):
    """KNOS_PROGRAM_IDS as knos.settle.v2.load_ids reads it: the program addresses of that file replace the pinned ones
    (said on stderr); anything else it changes is refused; unset, the pinned deployment."""
    (tmp_path / "terms.json").write_text(TERMS.decode() + "\n", encoding="utf-8")
    pinned = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text())
    staging = str(Pubkey.new_unique())
    (tmp_path / "ids.json").write_text(json.dumps({**pinned, "knos_pay": staging, "staging": True}), encoding="utf-8")
    env = {**os.environ, "KNOS_PROGRAM_IDS": str(tmp_path / "ids.json")}
    done = _run(*ARGS, terms=str(tmp_path / "terms.json"), env=env)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    vault = Pubkey.from_string(out["vault"])
    staged = Pubkey.from_string(staging)
    assert out["instruction"]["program"] == staging and "STAGING" in done.stderr and staging in done.stderr
    order = Pubkey.find_program_address([b"ord", pay.scope_of(987654321, 77), bytes(vault), (2).to_bytes(4, "little")], staged)[0]
    assert out["order"] == str(order)                                  # its addresses are the staging program's too
    # the Python client, under the same file, builds the same instruction
    assert python_client_ix(tmp_path / "ids.json", vault) == out["instruction"]
    # a file that changes what the programs fix is refused, and nothing is printed as an order
    for change in ({"fee_owner": str(Pubkey.new_unique())}, {"knos_pay": "not an address"}):
        (tmp_path / "bad.json").write_text(json.dumps({**pinned, **change}), encoding="utf-8")
        bad = _run(*ARGS, terms=str(tmp_path / "terms.json"), env={**os.environ, "KNOS_PROGRAM_IDS": str(tmp_path / "bad.json")})
        assert bad.returncode != 0 and bad.stdout == "" and "KNOS_PROGRAM_IDS" in bad.stderr, (change, bad.stderr)
    # unset or empty: the pinned knos_pay
    plain = _run(*ARGS, terms=str(tmp_path / "terms.json"), env={**os.environ, "KNOS_PROGRAM_IDS": " "})
    assert json.loads(plain.stdout)["instruction"]["program"] == pinned["knos_pay"] and "STAGING" not in plain.stderr


def python_client_ix(ids: Path, vault: Pubkey) -> dict:
    """The FundOrderWallet the Python client builds for `vault` with KNOS_PROGRAM_IDS naming `ids` (its ids are read when
    knos.settle.v2 is imported, so in a process of its own), as the dry run prints one."""
    code = ("import json,sys; from solders.pubkey import Pubkey; from knos.settle.v2 import pay; v=Pubkey.from_string(sys.argv[1]);"
            "ix=pay.fund_order_wallet_ix(v, pay.ata(v, pay.USDC_DEVNET), pay.USDC_DEVNET, 987654321, 77, 20_000_000, 'drexthealpha/Knos', 'c'*40,"
            f" {TERMS!r}, pay.MERGE, 7*86_400, 2);"
            "print(json.dumps({'program': str(ix.program_id), 'data': bytes(ix.data).hex(), 'accounts': [{'pubkey': str(a.pubkey), 'signer': a.is_signer, 'writable': a.is_writable} for a in ix.accounts]}))")
    done = subprocess.run([sys.executable, "-c", code, str(vault)], capture_output=True, text=True, timeout=120, env={**os.environ, "KNOS_PROGRAM_IDS": str(ids)})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_what_cannot_be_an_order_is_refused_in_words():
    for change, said in (({"--wf-sha": "main"}, "--wf-sha is a commit"), ({"--work-days": "91"}, "--work-days is 1 to 90"), ({"--mint": "usdc"}, "--mint is not a Solana address"),
                         ({"--amount": "20.5"}, "--amount is a whole number"), ({"--wf-repo": "Knos"}, "--wf-repo is owner/name")):
        args = [a if i % 2 == 0 else change.get(ARGS[i - 1], a) for i, a in enumerate(ARGS)]
        bad = _run(*args, terms=TERMS.decode())
        assert bad.returncode == 1 and bad.stderr.startswith("refused: ") and said in bad.stderr, (change, bad.stderr)
    bad = _run(*ARGS, terms="not json")
    assert bad.returncode == 1 and "--terms is the terms JSON" in bad.stderr
    bad = _run(*ARGS, "stray", terms=TERMS.decode())
    assert bad.returncode == 1 and bad.stderr.startswith("refused: ") and "--help" in bad.stderr
    bad = _run(*ARGS, "--send", terms=TERMS.decode())
    assert bad.returncode == 1 and "--member FILE is needed" in bad.stderr            # nothing is sent without a member's key


def test_the_funding_the_dry_run_prints_is_refused_by_squads_without_the_threshold_and_by_the_vault_over_what_it_holds(tmp_path):
    """The dry run's instruction for a multisig made in the simulator, proposed through the deployed Squads v4 build
    (tests/_squads.py): one vote of two executes nothing; an amount over what the vault holds is refused when it
    executes; within it, two votes fund the order from the vault."""
    pytest.importorskip("solders.litesvm")
    sys.path.insert(0, str(ROOT / "tests"))
    import _squads as sq
    from _order import USDC
    from solders.instruction import AccountMeta, Instruction
    from solders.keypair import Keypair
    if not sq.available():
        pytest.skip("needs the Squads v4 program: python scripts/squads_program.py fetch")
    c = sq.SquadsChain()
    req, a1, a2, cfg = Keypair(), Keypair(), Keypair(), Keypair()
    for k in (req, a1, a2):
        c.svm.airdrop(k.pubkey(), 10 ** 9)
    ms = c.create([(req, sq.INITIATE), (a1, sq.VOTE | sq.EXECUTE), (a2, sq.VOTE | sq.EXECUTE)], 2, cfg.pubkey())
    vault = sq.vault_pda(ms)
    c.svm.airdrop(vault, 10 ** 9)
    c.mint_to(c.usdc, c.token_account(vault, c.usdc), 30 * USDC)

    def printed(amount: int, issue: int) -> Instruction:
        args = [a if i % 2 == 0 else {"--multisig": str(ms), "--mint": str(c.usdc), "--amount": str(amount), "--issue": str(issue)}.get(ARGS[i - 1], a)
                for i, a in enumerate(ARGS)]
        done = _run(*args, terms=TERMS.decode())
        assert done.returncode == 0, done.stderr
        out = json.loads(done.stdout)
        assert out["vault"] == str(vault)
        i = out["instruction"]
        return Instruction(Pubkey.from_string(i["program"]), bytes.fromhex(i["data"]),
                           [AccountMeta(Pubkey.from_string(a["pubkey"]), a["signer"], a["writable"]) for a in i["accounts"]])

    over = printed(40 * USDC, 78)
    n = c.propose(ms, req, [over])
    assert n is not None and c.approve(ms, n, a1), c.err
    assert not c.execute(ms, n, a1) and c.said_error() == "InvalidProposalStatus"            # one vote of two
    assert c.approve(ms, n, a2) and not c.execute(ms, n, a1)                                   # two votes, but over what the vault holds
    assert c.order(over.accounts[1].pubkey) is None
    fits = printed(20 * USDC, 79)
    n = c.propose(ms, req, [fits])
    assert n is not None and c.approve(ms, n, a1) and c.approve(ms, n, a2) and c.execute(ms, n, a2), c.err
    o = c.order(fits.accounts[1].pubkey)
    assert o is not None and o.source == vault and o.amount == 20 * USDC
