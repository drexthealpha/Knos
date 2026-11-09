"""Lock pre-orders: one Knos devnet pre-order vault per demand report, built with Knos's own graduation code.

A demand report is evidence that people may want a product; a pre-order is a buyer putting test money where that
evidence points. Each report opens a pre-order POOL in the sense of `knos.graduation` (Knos 0.3.29): the order scope,
private salted options and terms come from `knos.graduation.scope / options / terms`, every order is built by
`knos.graduation.preorder_ix` (a knos_pay FundOrderWallet), and the pool is read back with `knos.graduation.pool`.
The terms carry the report's sha256 as the spec hash, so the money is locked against that exact report.

What a pre-order is, on chain: the buyer's test units plus the knos_pay fee leave the buyer's token account into the
knos_pay program; they are paid to the maker only through Knos's judge workflow on delivery, and are refunded to the
buyer after the deadline otherwise (anyone may send RefundOrder). This app never pays anyone out.

Devnet only (knos.chain refuses mainnet). Test money: a test mint this app creates (6 decimals, no freeze authority).
Who signs:
  wallet mode  the buyer's own browser wallet signs; the server only builds the unsigned transaction and relays it.
  passkey      the buyer's own passkey signs (knos_wanted.wallets). The app's devnet TEST wallet (KNOS_WANTED_DEVNET_KEYPAIR)
               only pays fees and mints test units (the faucet); it never buys for anyone (the demo buyer is removed).
`knos` is an optional dependency (`pip install "./apps/wanted[escrow]"`); without it the report still works and the button
says the vault is unavailable.
"""
from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path

UNIT = 1_000_000
MINT_LEN = 82
DEFAULT_JUDGE_REPO = 1401439243        # drexthealpha/knos-e2e: the judge repository of Knos's devnet demos
DEFAULT_MAKER_GITHUB_ID = 142920951    # drexthealpha: the maker paid on delivery (set KNOS_WANTED_MAKER_GITHUB_ID)
POOL_DAYS = 14
CLAIM_PREFIX = "knos-demand:"     # the pre-order pool of one demand report (Knos 0.3.31 used "knos-wanted:")
FAUCET_UNITS = 20
_lock = threading.Lock()


class EscrowUnavailable(RuntimeError):
    pass


def knos():
    try:
        from knos import chain, graduation
        from knos.settle.v2 import pay
    except Exception as why:  # noqa: BLE001 - knos missing or broken: the vault is off, the report is not
        raise EscrowUnavailable(f"the knos package is not installed ({type(why).__name__}); pip install './apps/wanted[escrow]'") from None
    return chain, graduation, pay


def available() -> bool:
    try:
        knos()
        return True
    except EscrowUnavailable:
        return False


DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
_genesis_ok: dict[str, bool] = {}


def ledger():
    chain, _, _ = knos()
    led = chain.ledger()
    if not any(x in led.url for x in ("devnet", "127.0.0.1", "localhost")):
        raise EscrowUnavailable("devnet only")
    if "devnet" in led.url and led.url not in _genesis_ok:
        # an endpoint named devnet is believed only when its first block is devnet's (a reset or a wrong URL is refused)
        try:
            got = chain.call(led.url, "getGenesisHash", [])
        except Exception:  # noqa: BLE001 - unreachable now: checked again on the next call
            got = None
        if got is not None:
            _genesis_ok[led.url] = got == DEVNET_GENESIS
    if _genesis_ok.get(led.url) is False:
        raise EscrowUnavailable("refused: the RPC endpoint's genesis hash is not devnet's")
    return led


def claim_id(report_hash: str) -> str:
    return CLAIM_PREFIX + report_hash[:40]


def plan(report_hash: str, *, repo_id: int | None = None, maker_github_id: int | None = None, pool_days: int = POOL_DAYS) -> dict:
    """The pre-order pool of one report, in the plan shape knos.graduation.preorder_ix and .pool read."""
    _, graduation, pay = knos()
    if not isinstance(report_hash, str) or len(report_hash) != 64 or any(ch not in "0123456789abcdef" for ch in report_hash):
        raise ValueError("report hash: 64 lowercase hex characters")
    repo_id = repo_id or int(os.environ.get("KNOS_WANTED_JUDGE_REPO_ID", DEFAULT_JUDGE_REPO))
    maker = maker_github_id or int(os.environ.get("KNOS_WANTED_MAKER_GITHUB_ID", DEFAULT_MAKER_GITHUB_ID))
    cid = claim_id(report_hash)
    shares = [("researcher", 10_000)]
    t = graduation.terms("preorder", cid, report_hash, 0, shares)
    work_s = max(pay.MIN_WORK, min(pay.MAX_WORK, pool_days * 86_400))
    return {"claim_id": cid, "repo_id": repo_id, "spec_hash": report_hash, "wf_repo": graduation.JUDGE_WF_REPO,
            "wf_sha": pay.IDS["claim_sha"], "program": str(pay.PAY_ID), "mode": pay.MERGE,
            "options": graduation.options(repo_id).hex(), "payees": [(maker, 10_000, None)],
            "pool": {"scope": graduation.scope(cid, repo_id, graduation.POOL_ISSUE).hex(), "terms": t.decode(),
                     "terms_hash": pay.terms_hash(t).hex(), "work_s": work_s, "min_buyers": 1, "min_locked": 0},
            "cluster": "devnet", "money": "test units of this app's own devnet test mint"}


# -- keys and the test mint ----------------------------------------------------------------------------------------
def _state_dir() -> Path:
    d = Path(os.environ.get("KNOS_WANTED_STATE") or ".cache/state")
    d.mkdir(parents=True, exist_ok=True)
    return d


def demo_key():
    """The app's devnet TEST wallet: KNOS_WANTED_DEVNET_KEYPAIR (a path, or the JSON byte array). Never a founder key."""
    from solders.keypair import Keypair
    v = os.environ.get("KNOS_WANTED_DEVNET_KEYPAIR")
    if not v:
        raise EscrowUnavailable("no devnet test wallet configured (KNOS_WANTED_DEVNET_KEYPAIR)")
    text = v if v.strip().startswith("[") else Path(v).expanduser().read_text(encoding="utf-8")
    return Keypair.from_bytes(bytes(json.loads(text)))


def mint(led=None, create: bool = True):
    """The test mint (address from KNOS_WANTED_MINT or the state file); created once, authority = the demo wallet."""
    from solders.instruction import AccountMeta, Instruction
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.system_program import CreateAccountParams, create_account
    chain, _, pay = knos()
    v = os.environ.get("KNOS_WANTED_MINT")
    f = _state_dir() / "mint.txt"
    if not v and f.exists():
        v = f.read_text(encoding="utf-8").strip()
    if v:
        return Pubkey.from_string(v)
    if not create:
        raise EscrowUnavailable("no test mint yet")
    led = led or ledger()
    payer = demo_key()
    m = Keypair()
    rent = chain.call(led.url, "getMinimumBalanceForRentExemption", [MINT_LEN])
    init = Instruction(pay.TOKEN, bytes([20, 6]) + bytes(payer.pubkey()) + b"\x00", [AccountMeta(m.pubkey(), False, True)])
    led.send([create_account(CreateAccountParams(from_pubkey=payer.pubkey(), to_pubkey=m.pubkey(), lamports=rent, space=MINT_LEN,
                                                 owner=pay.TOKEN)), init], payer, [m])
    f.write_text(str(m.pubkey()), encoding="utf-8")
    return m.pubkey()


def _mint_to_ix(mint_pk, ata, authority, units: int):
    from solders.instruction import AccountMeta, Instruction
    _, _, pay = knos()
    return Instruction(pay.TOKEN, bytes([7]) + (units * UNIT).to_bytes(8, "little"),
                       [AccountMeta(mint_pk, False, True), AccountMeta(ata, False, True), AccountMeta(authority, True, False)])


def _token_units(led, ata) -> int:
    chain, _, _ = knos()
    try:
        return int(chain.call(led.url, "getTokenAccountBalance", [str(ata)])["value"]["amount"])
    except Exception:  # noqa: BLE001 - no account yet
        return 0


def _next_seq(led, p: dict, buyer) -> int:
    _, graduation, _ = knos()
    for seq in range(0, 64):
        if led.account(graduation.address(p, "pool", buyer, seq)) is None:
            return seq
    raise EscrowUnavailable("this buyer already has 64 pre-orders in this pool")


def _amount(units) -> int:
    _, _, pay = knos()
    if isinstance(units, bool) or not isinstance(units, int):
        raise ValueError("amount: whole test units")
    low, high = pay.units(pay.ORDER_MIN_AMOUNT) // UNIT, 1_000
    if not low <= units <= high:
        raise ValueError(f"amount: {low} to {high} test units")
    return units * UNIT


def explorer(sig_or_addr: str, kind: str = "tx") -> str:
    return f"https://explorer.solana.com/{kind}/{sig_or_addr}?cluster=devnet"


# -- wallet mode: the buyer's own wallet signs ----------------------------------------------------------------------
def faucet(owner: str) -> dict:
    """Test units (and a little devnet SOL for rent and fees) to a browser wallet, from the app's test wallet."""
    from solders.pubkey import Pubkey
    from solders.system_program import TransferParams, transfer
    chain, _, pay = knos()
    who = Pubkey.from_string(owner)
    with _lock:
        led = ledger()
        payer = demo_key()
        m = mint(led)
        ata = pay.ata(who, m)
        ixs = []
        if led.account(ata) is None:
            ixs.append(pay.create_ata_ix(payer.pubkey(), who, m))
        ixs.append(_mint_to_ix(m, ata, payer.pubkey(), FAUCET_UNITS))
        lamports = int(chain.call(led.url, "getBalance", [owner])["value"])
        if lamports < 10_000_000:
            ixs.insert(0, transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=who, lamports=20_000_000)))
        sig = led.send(ixs, payer)
    return {"signature": sig, "explorer": explorer(sig), "units": FAUCET_UNITS, "mint": str(m)}


def wallet_tx(report_hash: str, owner: str, units: int = 5) -> dict:
    """The unsigned transaction (base64, legacy) that the buyer's wallet signs: one knos graduation pre-order."""
    from solders.hash import Hash
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    chain, graduation, pay = knos()
    amount = _amount(units)
    led = ledger()
    who = Pubkey.from_string(owner)
    m = mint(led, create=False)
    p = plan(report_hash)
    seq = _next_seq(led, p, who)
    ix = graduation.preorder_ix(p, who, pay.ata(who, m), m, amount, seq=seq)
    bh = Hash.from_string(chain.call(led.url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
    tx = Transaction.new_unsigned(chain.message([ix], who, bh))
    return {"transaction": base64.b64encode(bytes(tx)).decode(), "order": str(graduation.address(p, "pool", who, seq)),
            "seq": seq, "mint": str(m), "amount_units": units, "fee_units": pay.order_fee(amount) / UNIT, "claim_id": p["claim_id"]}


def submit(signed_b64: str, expect_owner: str) -> dict:
    """Relay a transaction the buyer's wallet signed: only a single knos_pay pre-order by that buyer is relayed."""
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction
    chain, _, pay = knos()
    raw = base64.b64decode(signed_b64, validate=True)
    if len(raw) > 1232:
        raise ValueError("transaction too large")
    tx = Transaction.from_bytes(raw)
    msg = tx.message
    keys = msg.account_keys
    if keys[0] != Pubkey.from_string(expect_owner):
        raise ValueError("the fee payer is not the connected wallet")
    progs = {str(keys[ix.program_id_index]) for ix in msg.instructions}
    allowed = {str(pay.PAY_ID), str(chain.COMPUTE_BUDGET)}
    if not progs <= allowed or str(pay.PAY_ID) not in progs:
        raise ValueError("only a knos_pay pre-order is relayed")
    led = ledger()
    sig = led._submit(tx)
    chain.wait(led.url, sig, 60.0, "confirmed")
    return {"signature": sig, "explorer": explorer(sig)}


def pool(report_hash: str) -> dict:
    _, graduation, _ = knos()
    led = ledger()
    m = mint(led, create=False)
    p = plan(report_hash)
    s = graduation.pool(led, p, str(m))
    return {"claim_id": p["claim_id"], "buyers": s["buyers"], "locked_units": s["locked"] / UNIT, "orders": len(s["orders"]),
            "ignored": len(s["ignored"]), "mint": str(m), "scope": p["pool"]["scope"], "program": p["program"]}
