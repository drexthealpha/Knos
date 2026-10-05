"""Load: many funded orders open at once, every one settled once, and what that costs.

    python scripts/load.py --local 1000 --write                      # here: the simulator, the committed test builds
    python scripts/load.py --devnet 1000 --issuer-key issuer.pem --wallet ~/.config/solana/id.json --write   # at release

Two tiers, written to docs/load.json and rendered into docs/LOAD.md (`--write`; without it the result is printed).

  --local N   The test builds of knos_oidc 2.2 and knos_pay 2.1 (tests/fixtures) in LiteSVM, through the tests' own
              harness. N orders on N repositories are funded from one Balance and are all open at once; then they are
              paid in a shuffled order, every 10th token is sent twice and every 50th again after its order closed.
              At the end: every order paid exactly once, paid + fees + refunds == funded, nothing left in any order's
              account, no single-use marker missing. Every transaction's compute units and bytes are recorded per
              stage, and from those and Solana's limits (LIMITS, sourced in docs/LOAD.md) the time 1,000 orders take on
              a cluster with 1, 4 and 16 relayers is derived. Compute units are exact; cluster time is arithmetic.

  --devnet N  Against a cluster, by the operator. GitHub will not sign N tokens on demand, so a test issuer signs
              them: its RSA key (`--issuer-key`, PEM) is registered as a PRIVATE key of the wallet (knos_oidc's
              RegisterPrivateKey: any wallet, usable at once). What that reaches:
                verify   exercised: N tokens written and verified on chain under that key
                fund     exercised: N orders funded by the wallet (FundOrderWallet takes no token), in a mint the
                         script creates, with the shortest work time
                refund   exercised: each order refunded after its deadline, each token account closed
                pay      NOT exercised. knos_pay takes a token GitHub did not sign in one case only: PayOrder on a
                         PRIVATE order funded from a Balance, under a key registered by the wallet that opened that
                         Balance (programs-v2/knos_pay/src/order_judge.rs `token`). Such an order is funded by
                         FundOrderBalance, which takes GitHub's tokens only, one per order. So no test issuer can
                         fund and pay N orders; PayOrder's cost is measured in the simulator.
                meter    NOT exercised: knos_meter takes GitHub's tokens only (programs-v2/knos_meter/src/gh.rs).
              K senders work side by side with one fee-paying wallet. Recorded per stage: transactions, failures,
              retries, and seconds from the first submission to `finalized` (p50/p95/p99), per transaction and per
              unit (one token, one order). The run is appended to docs/load.json marked `cluster: devnet`.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import math
import random
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from solders.hash import Hash  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.system_program import CreateAccountParams, create_account  # noqa: E402

from knos import chain, terms  # noqa: E402
from knos.settle.v2 import oidc, pay  # noqa: E402

JSON, DOC = ROOT / "docs" / "load.json", ROOT / "docs" / "LOAD.md"
SEED = 314
# Solana's limits, as docs/LOAD.md sources them. `block_cu_before`: the block limit until SIMD-0286 raised it.
LIMITS = {"block_cu": 100_000_000, "block_cu_before": 60_000_000, "account_cu": 12_000_000, "tx_cu": chain.MAX_COMPUTE_UNITS,
          "tx_bytes": chain.MAX_TX_BYTES, "slot_s": 0.4}
RELAYERS = (1, 4, 16)
STAGES = ("verify", "fund", "pay")
COMPUTE_BUDGET = Pubkey.from_string("ComputeBudget111111111111111111111111111111")


def pct(values, p: float):
    """The nearest-rank percentile: the smallest value that at least p% of the values do not exceed."""
    v = sorted(values)
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)] if v else None


# == the local tier ====================================================================================================
@dataclass
class Row:
    stage: str              # verify | fund | pay | other
    phase: str              # what the driver was doing: fund, pay, replay
    order: int
    ok: bool
    cu: int                 # what the whole transaction consumed, as the runtime reports it
    size: int               # the signed transaction's bytes
    writable: tuple


class Meter:
    """Stands where the harness keeps its LiteSVM and passes everything through, noting of every transaction sent: the
    stage it belongs to, whether it succeeded, the compute units it consumed, its bytes and the accounts it locks for
    writing. The harness builds and sends every instruction; this only watches."""
    def __init__(self, svm):
        self._svm, self.rows, self.phase, self.order = svm, [], "setup", -1

    def __getattr__(self, name):
        return getattr(self._svm, name)

    def send_transaction(self, tx):
        r = self._svm.send_transaction(tx)
        ok = "Failed" not in type(r).__name__
        cu = (r if ok else r.meta()).compute_units_consumed
        m = tx.message
        keys, h = list(m.account_keys), m.header
        signed, n = h.num_required_signatures, len(keys)
        writable = tuple(k for i, k in enumerate(keys) if (i < signed - h.num_readonly_signed_accounts if i < signed
                                                           else i < n - h.num_readonly_unsigned_accounts))
        ix = next(i for i in m.instructions if keys[i.program_id_index] != COMPUTE_BUDGET)
        program, tag = keys[ix.program_id_index], bytes(ix.data)[:1]
        stage = "verify" if program == oidc.OIDC_ID else {b"\x10": "fund", b"\x11": "pay"}.get(tag, "other") if program == pay.PAY_ID else "other"
        self.rows.append(Row(stage, self.phase, self.order, ok, cu() if callable(cu) else cu, len(bytes(tx)), writable))
        return r


def fast_signer() -> None:
    """The harness signs test tokens with Python's own pow, a tenth of a second each. The same key through
    `cryptography` gives the same bytes (PKCS#1 v1.5 is deterministic) in a millisecond, and a thousand orders need
    two thousand tokens. Only the signing changes: the key, the claims and the harness's helpers are as they were."""
    from _settle import SeedKey, signing_key
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    k = signing_key()
    if not isinstance(k, SeedKey) or len(k.primes) != 2 or "sign" in vars(k):
        return
    p, q = k.primes
    d = pow(65537, -1, (p - 1) * (q - 1))
    key = rsa.RSAPrivateNumbers(p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p), rsa.RSAPublicNumbers(65537, k.n)).private_key()
    slow = type(k).sign
    probe = b"knos load"
    assert key.sign(probe, padding.PKCS1v15(), hashes.SHA256()) == slow(k, probe)
    k.sign = lambda data: key.sign(data, padding.PKCS1v15(), hashes.SHA256())


def fixtures() -> dict:
    return {f: hashlib.sha256((ROOT / "tests" / "fixtures" / f).read_bytes()).hexdigest() for f in ("knos_oidc_v2_test.so", "knos_pay_v2_test.so")}


def stage_stats(rows: list[Row], n: int, roles: dict) -> dict:
    """One stage's successful transactions, grouped by order."""
    per: dict[int, list[Row]] = {}
    for r in rows:
        per.setdefault(r.order, []).append(r)
    cu, txs, size = ([sum(getattr(r, f) for r in g) for g in per.values()] for f in ("cu", "ok", "size"))
    every = set(rows[0].writable).intersection(*(r.writable for r in rows)) if rows else set()
    return {"orders": len(per), "transactions": len(rows), "tx_per_order": {"p50": pct(txs, 50), "max": max(txs)},
            "cu_per_order": {"p50": pct(cu, 50), "p95": pct(cu, 95), "max": max(cu), "mean": round(sum(cu) / n)},
            "cu_per_tx_max": max(r.cu for r in rows), "bytes_per_order": {"p50": pct(size, 50), "max": max(size)},
            "bytes_per_tx_max": max(r.size for r in rows),
            "written_by_every_tx": sorted(roles.get(k, {"role": str(k), "one_per": "?"})["role"] + " (one per " + roles.get(k, {"one_per": "?"})["one_per"] + ")"
                                          for k in every)}


def derive(stages: dict, orders: int = 1000, block_cu: int = LIMITS["block_cu"]) -> dict:
    """What the measured compute units allow on a cluster, by arithmetic. Three ceilings apply to a block: the whole
    block's compute; 12M for the transactions that write one account, so 12M per relayer (its fee-paying account is
    written by everything it sends), 12M for the orders funded from one Balance, and 12M for PayOrder as a whole (every
    one writes the one fee account); and nothing else is in the block. The slowest ceiling sets the number of blocks."""
    acc, slot = LIMITS["account_cu"], LIMITS["slot_s"]
    cu = {s: stages[s]["cu_per_order"]["mean"] for s in STAGES}
    total = sum(cu.values())
    out = {"orders": orders, "block_cu": block_cu, "cu_per_order": total,
           "one_relayer_orders_per_second": round(acc / total / slot, 2),
           "fee_account_orders_per_second": round(acc / cu["pay"] / slot, 1),
           "one_balance_orders_per_second": round(acc / cu["fund"] / slot, 1), "relayers": {}}
    for r in RELAYERS:
        ceilings = {"the block": orders * total / block_cu, "the relayers' own accounts": orders * total / (r * acc),
                    "the Balance": orders * cu["fund"] / acc, "the fee account": orders * cu["pay"] / acc}
        slots = math.ceil(max(ceilings.values()))
        out["relayers"][str(r)] = {"blocks": slots, "seconds": round(slots * slot, 1), "bound_by": max(ceilings, key=ceilings.get),
                                   "orders_per_second": round(orders / (slots * slot), 1), "under_a_minute": slots * slot < 60}
    return out


def run_local(n: int, seed: int = SEED) -> dict:
    from _order import MAINT, OWNER, REPO, USDC, OrderChain, issue, user
    assert MAINT and OWNER
    fast_signer()
    began = time.monotonic()
    c = OrderChain()
    meter = c.svm = Meter(c.svm)
    rng = random.Random(seed)
    me = c.payer.pubkey()
    roles = {me: {"role": "the relayer's own account, which pays the transaction fee", "one_per": "relayer"},
             c.tip: {"role": "the relayer's token account, where its tip arrives", "one_per": "relayer"},
             c.bal: {"role": "the funder's Balance", "one_per": "funder"},
             pay.baltok_pda(c.bal): {"role": "the Balance's token account", "one_per": "funder"},
             pay.balx_pda(c.bal): {"role": "the Balance's side account", "one_per": "funder"},
             c.fee: {"role": "the fee account (FEE_OWNER's token account of the mint)", "one_per": "mint, for every relayer and funder"}}
    baltok = pay.baltok_pda(c.bal)
    start = {"balance": c.balance(baltok), "fee": c.balance(c.fee), "tip": c.balance(c.tip)}

    def refused(ix: Instruction, order: int) -> bool:
        meter.phase, meter.order = "replay", order
        return not c.send([ix])

    # -- fund: n orders, n repositories, one Balance; every 10th fund token sent a second time at once ---------------
    orders, sent_twice, sent_late = [], 0, 0
    for i in range(n):
        meter.phase, meter.order = "fund", i
        repo, num, amount = REPO + 1 + i, issue(), (5 + rng.randrange(40)) * USDC
        tok = c.fund_token(num, amount, repository_id=repo)
        ix = c.fund_balance_ix(tok, num, repo=repo)
        assert c.send([ix]), f"order {i} was not funded: {c.err}"
        address = pay.order_pda(pay.scope_of(repo, num), c.bal)
        o = c.order(address)
        assert o is not None and (o.state, o.amount, o.repo_id, o.issue) == ("open", amount, repo, num), f"order {i} is not as it was funded"
        orders.append({"address": address, "o": o, "fund_ix": ix, "fund_sig": pay.sig_hash(c.data(tok))})
        if i % 10 == 0:
            assert refused(ix, i), f"fund token {i} was accepted twice"
            sent_twice += 1
    after_fund = c.balance(baltok)
    funded = start["balance"] - after_fund
    held = sum(c.held(x["address"]) for x in orders)
    open_at_once = sum(1 for x in orders if (o := c.order(x["address"])) is not None and o.state == "open")
    assert open_at_once == n and held == funded == sum(x["o"].amount + x["o"].fee for x in orders), "the orders do not hold what left the Balance"

    # -- pay: in a shuffled order, one payee or two; every 10th pay token sent a second time at once ------------------
    turn = list(range(n))
    rng.shuffle(turn)
    for j, i in enumerate(turn):
        x = orders[i]
        meter.phase, meter.order = "pay", i
        wallets = [Keypair().pubkey() for _ in range(2 if i % 5 == 0 else 1)]
        payees = [(user(), 10_000 // len(wallets), w) for w in wallets]
        tok = c.pay_token(x["address"], payees, o=x["o"])
        ix = c.pay_ix(x["address"], tok, payees, o=x["o"])
        assert c.send([ix]), f"order {i} was not paid: {c.err}"
        x.update(wallets=wallets, pay_ix=ix, pay_sig=pay.sig_hash(c.data(tok)))
        if j % 10 == 0:
            assert refused(ix, i), f"pay token {i} was accepted twice"
            sent_twice += 1
    # -- every 50th token again, now that its order is closed: a fund token would fund it anew, a pay token pay it ----
    for i in range(0, n, 50):
        for ix in (orders[i]["pay_ix"], orders[i]["fund_ix"], orders[i]["pay_ix"]):
            assert refused(ix, i), f"a token of order {i} was accepted after the order closed"
            sent_late += 1

    # -- the invariants ----------------------------------------------------------------------------------------------
    got = [sum(c.balance(pay.ata(w, c.usdc)) for w in x["wallets"]) for x in orders]
    once = sum(1 for x, g in zip(orders, got) if g == x["o"].amount)
    paid = sum(got)
    fees = c.balance(c.fee) - start["fee"] + c.balance(c.tip) - start["tip"]
    refunds = c.balance(baltok) - after_fund
    left = sum(c.held(x["address"]) for x in orders) + c.balance(pay.vault_pda(c.usdc))
    still = sum(1 for x in orders if c.data(x["address"]) is not None)
    marked = {"fund": sum(1 for x in orders if c.data(pay.used_pda(x["fund_sig"])) is not None)}
    # PayOrder's marker: counted when this build's PayOrder takes one (the instruction the harness builds names it)
    # (the harness adds the marker's account when it sends, so the instruction is read as it was sent)
    if any(a.pubkey == pay.used_pda(orders[0]["pay_sig"]) for a in c.marked(orders[0]["pay_ix"]).accounts):
        marked["pay"] = sum(1 for x in orders if c.data(pay.used_pda(x["pay_sig"])) is not None)
    replay_rows = [r for r in meter.rows if r.phase == "replay"]
    inv = {"orders": n, "open_at_once": open_at_once, "paid_exactly_once": once, "paid_twice_or_short": n - once, "funded": funded, "paid": paid,
           "fees": fees, "refunds": refunds, "left_in_order_accounts_and_vault": left, "orders_still_open": still,
           "markers": marked, "markers_expected": n, "sent_twice": sent_twice, "sent_after_close": sent_late,
           "replays_refused": sum(1 for r in replay_rows if not r.ok), "replays_accepted": sum(1 for r in replay_rows if r.ok)}
    inv["ok"] = bool(once == n and paid + fees + refunds == funded and left == 0 and still == 0 and inv["replays_accepted"] == 0
                     and all(v == n for v in marked.values()))
    good = [r for r in meter.rows if r.ok and r.phase in ("fund", "pay")]
    stages = {s: stage_stats([r for r in good if r.stage == s], n, roles) for s in STAGES}
    stages["verify"]["tokens_per_order"] = 2
    return {"cluster": "local simulator (LiteSVM)", "date": datetime.date.today().isoformat(), "seed": seed, "fixtures": fixtures(),
            "simulator_seconds": round(time.monotonic() - began, 1), "invariants": inv, "stages": stages,
            "derived": derive(stages), "derived_before_simd_0286": derive(stages, block_cu=LIMITS["block_cu_before"])}


# == the devnet tier ===================================================================================================
class Rpc:
    """A cluster's JSON-RPC endpoint. A test hands `run_devnet` anything else with a `call`."""
    def __init__(self, url: str):
        self.url = url

    def call(self, method: str, params: list):
        """A public endpoint's rate limit (HTTP 429) that outlasts chain.call's own backoff is waited out here too: K
        senders polling one endpoint meet it, and it says nothing about the transactions, so it must not end the run."""
        for wait in (5, 10, 20, 30, None):
            try:
                return chain.call(self.url, method, params, timeout=30.0)
            except urllib.error.HTTPError as e:
                if e.code != 429 or wait is None:
                    raise
                time.sleep(wait)


@dataclass
class Sent:
    ok: bool
    signature: str | None
    submitted: float            # when it was first handed to the cluster
    retries: int = 0
    why: str | None = None
    finalized: float | None = None
    blockhash: str | None = None


@dataclass
class Sender:
    """Signs, submits and waits. A transaction that does not land before `within` seconds is signed over a new
    blockhash and sent again (a retry), `tries` times in all; one the cluster refuses is a failure, with its words."""
    rpc: object
    payer: Keypair
    tries: int = 4
    within: float = 60.0
    poll: float = 1.0
    clock: object = time.monotonic
    sleep: object = time.sleep
    lock: threading.Lock = field(default_factory=threading.Lock)

    def statuses(self, signatures: list[str]) -> list[dict | None]:
        return self.rpc.call("getSignatureStatuses", [signatures, {"searchTransactionHistory": True}])["value"]

    def blockhash(self, after: str | None) -> str:
        """A recent blockhash that is not `after`. The two steps that check a 2048-bit signature are the same
        instruction: signed over one blockhash they would be one transaction, and the second would never run."""
        end = self.clock() + self.within
        while True:
            got = self.rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
            if got != after or self.clock() >= end:
                return got
            self.sleep(self.poll / 2)

    def send(self, ixs, signers=(), after: str | None = None) -> Sent:
        """Lands one transaction (`confirmed`), so that the next one of the same token or order can build on it.
        `after`: the blockhash the transaction before it was signed over."""
        first, why, sig = self.clock(), None, None
        for attempt in range(self.tries):
            recent = self.blockhash(after)
            raw = base64.b64encode(bytes(chain.sign(ixs, self.payer, list(signers), Hash.from_string(recent)))).decode()
            try:
                sig = self.rpc.call("sendTransaction", [raw, {"encoding": "base64", "preflightCommitment": "confirmed", "maxRetries": 3}])
            except Exception as e:  # noqa: BLE001 - a refusal is a result here: it is counted and reported
                why = str(e)[:300]
                if "blockhash" in why.lower().replace(" ", "") and "notfound" in why.lower().replace(" ", ""):
                    continue                    # the endpoint has not seen that block yet, or it has aged out: sign again
                return Sent(False, sig, first, attempt, why, blockhash=recent)
            end = self.clock() + self.within
            while self.clock() < end:
                st = self.statuses([sig])[0]
                if st and st.get("err"):
                    return Sent(False, sig, first, attempt, f"failed on chain: {st['err']}", blockhash=recent)
                if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                    return Sent(True, sig, first, attempt, blockhash=recent)
                self.sleep(self.poll)
            why = f"not confirmed within {self.within:.0f}s"
        return Sent(False, sig, first, self.tries - 1, why)

    def finalize(self, sent: list[Sent]) -> None:
        """Waits until every landed transaction is `finalized` and notes when it was first seen so (to within `poll`).
        One that the cluster dropped after confirming it becomes a failure."""
        end = self.clock() + 2 * self.within
        waiting = [s for s in sent if s.ok]
        while waiting and self.clock() < end:
            for s, st in zip(waiting, self.statuses([s.signature for s in waiting])):
                if st and st.get("confirmationStatus") == "finalized":
                    s.finalized = self.clock()
            waiting = [s for s in waiting if s.finalized is None]
            if waiting:
                self.sleep(self.poll)
        for s in waiting:
            s.ok, s.why = False, "confirmed but not finalized in time"


def unit(sender: Sender, groups) -> list[Sent]:
    """One token or one order: its transactions in turn, each built on the one before; then all of them finalized."""
    sent: list[Sent] = []
    for ixs in groups:
        sent.append(sender.send(ixs, after=sent[-1].blockhash if sent else None))
        if not sent[-1].ok:
            break
    sender.finalize(sent)
    return sent


def stage(sender: Sender, units: list, senders: int) -> tuple[dict, list[bool]]:
    """Runs the units `senders` at a time. Returns the stage's record and, per unit, whether all of it finalized."""
    with ThreadPoolExecutor(max_workers=max(1, senders)) as pool:
        done = list(pool.map(lambda groups: unit(sender, groups), units))
    txs = [s for d in done for s in d]
    lat = [round(s.finalized - s.submitted, 2) for s in txs if s.ok]
    good = [len(d) == len(u) and all(s.ok for s in d) for d, u in zip(done, units)]
    whole = [round(max(s.finalized for s in d) - d[0].submitted, 2) for d, g in zip(done, good) if g]
    spread = lambda v: {"p50": pct(v, 50), "p95": pct(v, 95), "p99": pct(v, 99), "max": max(v, default=None)}  # noqa: E731
    return {"units": len(units), "units_finalized": sum(good), "transactions": len(txs), "failures": sum(1 for s in txs if not s.ok),
            "retries": sum(s.retries for s in txs), "tx_submit_to_finalized_s": spread(lat), "unit_submit_to_finalized_s": spread(whole),
            "first_failures": [s.why for s in txs if not s.ok][:5]}, good


NOT_EXERCISED = {
    "pay": "knos_pay takes a token GitHub did not sign only in PayOrder on a PRIVATE order funded from a Balance, under a key the Balance's own wallet "
           "registered; that order is funded by FundOrderBalance, which takes GitHub's tokens only, one per order. A test issuer cannot fund and pay "
           "N orders, so PayOrder was not sent on the cluster; its compute units are measured in the local simulator.",
    "fund from a Balance": "FundOrderBalance and the faucet take GitHub's tokens only. The orders were funded by a wallet (FundOrderWallet), in a "
                           "mint made for the run.",
    "meter": "knos_meter takes GitHub's tokens only.",
}
ISSUER_URL = "https://issuer.invalid/knos-load"    # names nothing real: a private key's URL is the registrant's own word
WF_REPO, WF_SHA = "drexthealpha/Knos", "c" * 40    # what the orders pin; nothing in this run is ever judged by it
# what the orders are funded with: terms in the canonical form knos.terms.parse reads, as a judge must read them to pay
TERMS = terms.canonical({"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge", "paths": [],
                         "reserve": 0, "v": 1})


def issuer_token(key, url: str, now: int, i: int, run: str) -> str:
    """A token as a CI issuer would sign it: RS256, the issuer's URL, five minutes of life, an audience of its own."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    claims = {"iss": url, "sub": f"load:{run}:{i}", "aud": f"knos-load:{run}:{i}", "iat": now, "nbf": now - 60, "exp": now + 300, "jti": f"{run}-{i}"}
    data = (b64(json.dumps({"typ": "JWT", "alg": "RS256", "kid": "load"}, separators=(",", ":")).encode()) + "."
            + b64(json.dumps(claims, separators=(",", ":")).encode())).encode()
    return data.decode() + "." + b64(key.sign(data, padding.PKCS1v15(), hashes.SHA256()))


def mint_ixs(payer: Pubkey, mint: Pubkey, rent: int, amount: int) -> list[Instruction]:
    """A plain SPL Token mint of six decimals, the wallet's token account of it, and `amount` minted there."""
    token = pay.ata(payer, mint)
    return [create_account(CreateAccountParams(from_pubkey=payer, to_pubkey=mint, lamports=rent, space=82, owner=pay.TOKEN)),
            Instruction(pay.TOKEN, bytes([20, 6]) + bytes(payer) + b"\x00", [AccountMeta(mint, False, True)]),
            pay.create_ata_ix(payer, payer, mint),
            Instruction(pay.TOKEN, b"\x07" + amount.to_bytes(8, "little"), [AccountMeta(mint, False, True), AccountMeta(token, False, True),
                                                                           AccountMeta(payer, True, False)])]


def accounts(rpc, addresses) -> list[bytes | None]:
    out: list[bytes | None] = []
    for i in range(0, len(addresses), 100):
        got = rpc.call("getMultipleAccounts", [[str(a) for a in addresses[i:i + 100]], {"encoding": "base64", "commitment": "finalized"}])["value"]
        out += [base64.b64decode(a["data"][0]) if a else None for a in got]
    return out


def chain_time(rpc) -> int:
    return int(rpc.call("getBlockTime", [rpc.call("getSlot", [{"commitment": "confirmed"}])]))


def token_balance(rpc, account: Pubkey) -> int:
    d = accounts(rpc, [account])[0]
    return int.from_bytes(d[64:72], "little") if d and len(d) >= 72 else 0


def run_devnet(rpc, wallet: Keypair, issuer_key, n: int, senders: int = 8, url: str = ISSUER_URL, amount: int = 5_000_000, work_s: int = 60,
               refund: bool = True, sender: Sender | None = None, name: str = "devnet") -> dict:
    s = sender or Sender(rpc, wallet)
    me, modulus = wallet.pubkey(), issuer_key.public_key().public_numbers().n
    run = hashlib.sha256(bytes(Keypair().pubkey())).hexdigest()[:10]      # tokens and orders of two runs never collide
    key = oidc.key_pda(url, modulus, registrant=me)
    out = {"cluster": name, "date": datetime.date.today().isoformat(), "orders": n, "senders": senders, "run": run, "wallet": str(me),
           "issuer": url, "key_account": str(key), "programs": {"knos_oidc": str(oidc.OIDC_ID), "knos_pay": str(pay.PAY_ID)},
           "stages": {}, "not_exercised": NOT_EXERCISED}

    # -- setup: the issuer's key as the wallet's PRIVATE key, and a mint of the wallet's own ---------------------------
    mint = Keypair()
    each = amount + 2 * pay.order_fee(amount) + 1_000_000        # room for the fee whatever tier this build charges
    rent = int(rpc.call("getMinimumBalanceForRentExemption", [82]))
    setup = [s.send([oidc.register_private_key_ix(me, url, modulus)]), s.send([oidc.key_params_ix(me, url, modulus, registrant=me)]),
             s.send(mint_ixs(me, mint.pubkey(), rent, n * each), [mint])]
    s.finalize(setup)
    out["mint"] = str(mint.pubkey())
    if not all(x.ok for x in setup):
        out["stopped"] = "setup failed: " + "; ".join(x.why or "ok" for x in setup)
        return out
    wallet_token = pay.ata(me, mint.pubkey())
    minted = token_balance(rpc, wallet_token)

    # -- verify: n tokens, each written and verified on chain ----------------------------------------------------------
    now = chain_time(rpc)
    jwts = [issuer_token(issuer_key, url, now, i, run) for i in range(n)]
    tids = [oidc.token_id(j) for j in jwts]
    plan = oidc.step_plan(modulus.bit_length())
    units = [[[ix] for ix in oidc.write_ixs(me, tid, jwt)] + [[oidc.step_ix(me, tid, key, sq)] for sq in plan] for jwt, tid in zip(jwts, tids)]
    out["stages"]["verify"], _ = stage(s, units, senders)
    seen = [oidc.token_issuer(d) for d in accounts(rpc, [oidc.token_pda(me, t) for t in tids])]
    out["stages"]["verify"]["verified_on_chain"] = sum(1 for t in seen if t is not None and t[1] == me and t[0] == oidc.issuer_hash(url))

    # -- fund: n orders on n repositories, by the wallet, with the shortest work time ---------------------------------
    base = 2_000_000_000 + int(run[:6], 16)
    places = [(base + i, 1 + i) for i in range(n)]
    orders = [pay.order_pda(pay.scope_of(repo, num), me) for repo, num in places]
    units = [[[pay.fund_order_wallet_ix(me, wallet_token, mint.pubkey(), repo, num, amount, WF_REPO, WF_SHA, TERMS, work_s=work_s)]] for repo, num in places]
    out["stages"]["fund"], funded = stage(s, units, senders)
    read = [pay.read_order(d) for d in accounts(rpc, orders)]
    out["stages"]["fund"]["open_on_chain"] = sum(1 for o in read if o is not None and o.state == "open" and o.amount == amount)
    held = minted - token_balance(rpc, wallet_token)
    out["checks"] = {"minted": minted, "held_by_orders": held, "held_equals_funded": held == sum(o.amount + o.fee for o in read if o is not None)}

    # -- refund: after the deadline every order gives back what it holds, and every token account is closed -----------
    if refund:
        last = max((o.deadline for o in read if o is not None), default=0)
        while chain_time(rpc) <= last:
            s.sleep(5.0)
        units = [[[pay.refund_order_ix(me, a, o, wallet_token)]] for a, o in zip(orders, read) if o is not None]
        out["stages"]["refund"], _ = stage(s, units, senders)
        closes = [[[oidc.close_ix(me, t)]] for t, v in zip(tids, seen) if v is not None]
        out["stages"]["close"], _ = stage(s, closes, senders)
        back = token_balance(rpc, wallet_token)
        out["checks"].update(orders_left=sum(1 for d in accounts(rpc, orders) if d is not None), returned=back, nothing_lost=back == minted)
    out["ok"] = bool(out["stages"]["verify"]["verified_on_chain"] == n and out["stages"]["fund"]["open_on_chain"] == n
                     and out["checks"]["held_equals_funded"] and (not refund or (out["checks"]["nothing_lost"] and out["checks"]["orders_left"] == 0)))
    return out


# == the documents =====================================================================================================
ABOUT = ("Load measurements; scripts/load.py writes this file and renders docs/LOAD.md from it. local: N orders through the committed test builds in "
         "LiteSVM (compute units exact, cluster time derived). runs: what an operator measured on a cluster with a test issuer, newest last.")


def usd(micro: int) -> str:
    return f"{micro / 1_000_000:,.2f}"


def render(doc: dict) -> str:
    L, loc = doc["limits"], doc.get("local")
    out = ["# Load: many orders open at once", "",
           "<!-- written by scripts/load.py from docs/load.json; change the numbers there by running it, not here -->", "",
           "The claim this page tests: 1,000 funded orders open at once, each settled in under a minute of submission, with no order paid twice "
           "and none lost. The second half (paid once, none lost) is measured. The first half (a minute) is derived from what was measured, and "
           "holds or does not hold depending on how many relayers carry the tokens; the table below says which.", "",
           "Everything in the first three sections was **measured in the local simulator** (LiteSVM, the same virtual machine a validator runs, "
           "with the test builds in `tests/fixtures`). **Compute units are exact**: a cluster charges the same program the same units. "
           "**Wall-clock time on a cluster is derived** from those units and Solana's published limits; it was not observed.", ""]
    if loc:
        i, st, d = loc["invariants"], loc["stages"], loc["derived"]
        pm = i["markers"].get("pay")
        out += [f"## 1. Paid once, none lost ({i['orders']:,} orders)", "",
                f"`python scripts/load.py --local {i['orders']}` on {loc['date']} (seed {loc['seed']}). {i['orders']:,} orders on {i['orders']:,} "
                "different repositories and issues were funded from one Balance by tokens the harness signs with the test key, and all were open "
                "before the first was paid. They were then paid in a shuffled order, four in five to one payee and one in five to two. Every "
                "10th fund token and every 10th pay token was sent a second time at once; every 50th order's fund token and pay token were sent "
                "again after the order had closed.", "",
                "| Check | Result |", "| --- | --- |",
                f"| Orders open at the same time | {i['open_at_once']:,} of {i['orders']:,} |",
                f"| Orders whose payees hold exactly the order's amount (paid once) | {i['paid_exactly_once']:,} of {i['orders']:,} |",
                f"| Orders paid twice or short | {i['paid_twice_or_short']} |",
                f"| Left the Balance (funded), test USDC | {usd(i['funded'])} |",
                f"| Reached payees, test USDC | {usd(i['paid'])} |",
                f"| Fees, the relayer's tips included | {usd(i['fees'])} |",
                f"| Came back to the Balance (refunds) | {usd(i['refunds'])} |",
                f"| paid + fees + refunds == funded | {'yes' if i['paid'] + i['fees'] + i['refunds'] == i['funded'] else 'NO'} |",
                f"| Left in any order's account or the shared vault | {usd(i['left_in_order_accounts_and_vault'])} |",
                f"| Order accounts still open | {i['orders_still_open']} |",
                f"| Single-use markers of fund tokens present | {i['markers']['fund']:,} of {i['markers_expected']:,} |",
                "| Single-use markers of pay tokens present | "
                + (f"{pm:,} of {i['markers_expected']:,} |" if pm is not None else "not counted: the PayOrder of the measured build takes no marker |"),
                f"| Tokens sent twice at once, accepted the second time | {i['sent_twice']} sent, 0 accepted |"
                if i["replays_accepted"] == 0 else f"| Replays accepted | {i['replays_accepted']} |",
                f"| Tokens sent again after their order closed, accepted | {i['sent_after_close']} sent, {i['replays_accepted']} accepted |", "",
                "The measured builds: " + ", ".join(f"`{f}` sha256 `{h[:16]}`" for f, h in loc["fixtures"].items()) + ".", "",
                "## 2. What one order costs", "",
                "| Stage | Transactions per order | Compute units per order p50 | p95 | max | Largest transaction (CU) | Bytes per order p50 | "
                "Largest transaction (bytes) |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        names = {"verify": "Token verification (knos_oidc), two tokens", "fund": "Fund (FundOrderBalance)", "pay": "Pay (PayOrder)"}
        for s in STAGES:
            x = st[s]
            out.append(f"| {names[s]} | {x['tx_per_order']['p50']} | {x['cu_per_order']['p50']:,} | {x['cu_per_order']['p95']:,} | "
                       f"{x['cu_per_order']['max']:,} | {x['cu_per_tx_max']:,} | {x['bytes_per_order']['p50']:,} | {x['bytes_per_tx_max']:,} |")
        out += ["", "What each number is:", "",
                "- **Stage.** An order needs two tokens, one that funds it and one that pays it. *Token verification* is every knos_oidc "
                "transaction for both: the token written into its account in pieces, then the RSA signature checked in steps. *Fund* and *Pay* "
                "are the one knos_pay transaction each token is then handed to.",
                "- **Transactions per order.** Successful transactions of that stage for one order. Refused duplicates are not counted here.",
                "- **Compute units per order.** The sum, over those transactions, of what the runtime reports each consumed (the whole "
                "transaction, the programs it calls included). p50, p95 and max are over the orders (nearest rank).",
                "- **Largest transaction.** The most one transaction of the stage consumed; a transaction may use "
                f"{L['tx_cu']:,}. And the most one weighed, signatures included; a cluster takes {L['tx_bytes']:,} bytes.",
                "- **Bytes per order.** The sum of the signed transactions' sizes.", "",
                "## 3. What that allows on a cluster (derived)", "",
                f"Solana's limits: a block holds {L['block_cu'] // 10 ** 6}M compute units ({L['block_cu_before'] // 10 ** 6}M until SIMD-0286; "
                f"mainnet has had the larger blocks since 29 July 2026, devnet since earlier), the transactions that write any one account may "
                f"use {L['account_cu'] // 10 ** 6}M of a block, and a block is produced every {int(L['slot_s'] * 1000)} ms. Sources: "
                + ", ".join(f"[{t}]({u})" for t, u in doc["sources"].items()) + ". The two sources disagree on one figure: Solana's page says the "
                "per-account limit stays at 12M, while the development branch of the Agave validator carries 24,000,000 for that constant (read "
                "on 4 October 2026). This page uses 12M, the published figure for the live clusters; with 24M the per-relayer, per-Balance and "
                "fee-account rates below double.", "",
                f"One order costs {d['cu_per_order']:,} compute units in all (the mean of the measured orders). The accounts that every "
                "transaction of a stage writes, and so the ones that cap it:", ""]
        for s in STAGES:
            out.append(f"- **{names[s]}**: " + "; ".join(st[s]["written_by_every_tx"]) + ".")
        out += ["", "So there are three points of contention, and the shared vault is not one of them: each order's money is in its own token "
                "account, which only that order's transactions write.", "",
                f"1. **A relayer's own account.** Everything a relayer sends writes the account that pays its fees, so one relayer fits "
                f"{L['account_cu'] // 10 ** 6}M units in a block: **{d['one_relayer_orders_per_second']} orders a second**, verification included. "
                "Verification is nearly all of it, and it is the only stage more relayers speed up.",
                f"2. **The fee account.** Every PayOrder of a mint writes the one fee account, whoever relays it: at most "
                f"**{d['fee_account_orders_per_second']} payments a second** in that mint, however many relayers there are.",
                f"3. **A Balance.** Every order funded from one Balance writes it: at most {d['one_balance_orders_per_second']} fundings a second "
                "per Balance. Orders funded from different Balances, or by wallets, do not share it.", "",
                f"Time for {d['orders']:,} orders submitted at once, all from one Balance, if the block held nothing else and was packed perfectly:", "",
                f"| Relayers | Blocks ({L['block_cu'] // 10 ** 6}M) | Seconds | Orders a second | Bound by | All settled within a minute | "
                f"Seconds with {L['block_cu_before'] // 10 ** 6}M blocks |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for r, x in d["relayers"].items():
            out.append(f"| {r} | {x['blocks']} | {x['seconds']} | {x['orders_per_second']} | {x['bound_by']} | {'yes' if x['under_a_minute'] else 'no'} | "
                       f"{loc['derived_before_simd_0286']['relayers'][r]['seconds']} |")
        out += ["", "How it is derived: blocks = the largest of (all compute / the block limit), (all compute / relayers x 12M), (fund compute / "
                "12M) and (pay compute / 12M), rounded up; seconds = blocks x 0.4. It is a floor on the time, not a forecast: it counts only the "
                "compute the transactions consumed (a cluster also charges signatures, write locks and data against the same limits), it assumes "
                "the relayers split the tokens evenly and that no other transaction is in the block, and it ignores that the transactions of one "
                "token must land one after another. With one relayer the claim of a minute does **not** hold for 1,000 orders arriving together; "
                "the table shows from how many relayers it does." if not d["relayers"]["1"]["under_a_minute"] else
                "How it is derived: blocks = the largest of (all compute / the block limit), (all compute / relayers x 12M), (fund compute / 12M) "
                "and (pay compute / 12M), rounded up; seconds = blocks x 0.4. It is a floor on the time, not a forecast: it counts only the compute "
                "the transactions consumed, assumes an otherwise empty block and an even split between relayers.", ""]
    out += ["## 4. On a cluster (devnet)", "",
            "`python scripts/load.py --devnet N --issuer-key issuer.pem --wallet <keypair> --write`, run by the operator at release. GitHub will "
            "not sign a thousand tokens on demand, so a test issuer signs them, and its key is registered as a private key of the operator's "
            "wallet (knos_oidc's RegisterPrivateKey). That decides what a cluster run can and cannot exercise:", "",
            "| Stage | On the cluster | Why |", "| --- | --- | --- |",
            "| Token verification | exercised | knos_oidc verifies any RS256 issuer's tokens under a registered key |",
            "| Fund | exercised, from a wallet | FundOrderWallet takes no token |",
            "| Refund and close | exercised | every order is refunded after its deadline and every token account closed, so the run leaves nothing behind |",
            f"| Pay | **not exercised** | {NOT_EXERCISED['pay']} |",
            f"| Fund from a Balance, the faucet | **not exercised** | {NOT_EXERCISED['fund from a Balance']} |",
            f"| Meter | **not exercised** | {NOT_EXERCISED['meter']} |", "",
            "Latency is seconds from a transaction's first submission until the script first saw it `finalized` (it asks once a second), per "
            "transaction and per unit (a token: all its transactions; an order: its one). A retry is a transaction signed again because it did "
            "not land in time; a failure is one the cluster refused or lost.", ""]
    runs = doc.get("runs") or []
    if not runs:
        out += ["**No cluster run is recorded yet.** The path is unit-tested against a simulated RPC (`tests/test_load.py`); it has not been "
                "run on devnet.", ""]
    for r in runs:
        out += [f"### {r['cluster']}, {r['date']}: {r['orders']:,} orders, {r['senders']} senders" + ("" if r.get("ok") else " (did not complete cleanly)"), "",
                "| Stage | Units finalized | Transactions | Failures | Retries | Transaction p50 s | p95 | p99 | Unit p50 s | p95 | p99 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for s, x in r["stages"].items():
            t, u = x["tx_submit_to_finalized_s"], x["unit_submit_to_finalized_s"]
            out.append(f"| {s} | {x['units_finalized']:,} of {x['units']:,} | {x['transactions']:,} | {x['failures']} | {x['retries']} | {t['p50']} | "
                       f"{t['p95']} | {t['p99']} | {u['p50']} | {u['p95']} | {u['p99']} |")
        out += ["", f"Wallet `{r['wallet']}`, key account `{r['key_account']}`, mint `{r.get('mint')}`." + (f" Stopped: {r['stopped']}." if r.get("stopped") else ""), ""]
    if doc.get("workflow"):
        out += render_workflow(doc["workflow"], runs)
    return "\n".join(out).rstrip() + "\n"


def render_workflow(w: dict, runs: list) -> list[str]:
    """Section 5, from docs/load.json's `workflow` section (scripts/capacity.py writes it): what one order costs outside
    the chain, and which limit a customer meets first."""
    L, c, rel, lat = w["limits"], w["counted"], w["relay"], w["latency"]
    own, pub, m2p = w["budget"]["own"], w["budget"]["public"], lat["merge_to_paid_s"]
    ways = {"own": "the job's own relay", "public": "the public worker"}
    out = ["## 5. The whole workflow", "",
           "A chain rate is not the system's capacity. An order is also two workflow jobs, the requests each makes of GitHub with a token "
           "GitHub rations, the comments it posts, a token GitHub signs, a relay that carries it and a statement someone reads back. This "
           "section counts those and asks which limit a customer meets first. `python scripts/capacity.py --write` wrote it; "
           "`python scripts/capacity.py -R <repositories> -N <deliverables a day>` answers for any customer.", "",
           "### What one word of the workflow asks of GitHub (counted)", "",
           "Counted by running `command`, `settle` and `attest` of `src/knos/flow.py` against the tests' stand-in for api.github.com "
           "(`tests/_flow.py`), on the simplest order: one issue, one pull request, one payee with a bound wallet. It is a count of the "
           "code's requests, exact for that case; an order with more payees, more closing issues or a policy file reads more. It was not "
           "counted on GitHub itself.", "",
           "| Word | Token carried by | Requests read | Requests written | Comments made | Tokens GitHub signs | Jobs |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for way in ("own", "public"):
        for x in c[way].values():
            out.append(f"| {x['word']} | {ways[way]} | {x['reads']} | {x['writes']} | {x['comments']} | {x['tokens_signed']} | {x['jobs']} |")
    out += ["", "The job's own relay is the job sending the transactions itself with a fee key the repository keeps (`KNOS_RELAY_KEY`). "
            "Without the key the token is posted as a comment and the public worker carries it; the job then reads the worker's log every "
            f"{rel['wait_every_s']:g} s for up to {rel['wait_at_most_s']} s. Those reads use the repository's own token and are not "
            "conditional, so each one counts.", "",
            "### The budget of one deliverable (funded by a comment, paid on its merge)", "",
            "| | The job's own relay | The public worker | Where the number is from |", "| --- | --- | --- | --- |",
            f"| Workflow jobs | {own['jobs']} | {pub['jobs']} | counted |",
            f"| GitHub requests with the repository's token, the work itself | {own['reads'] + own['writes']} | {pub['reads'] + pub['writes']} | counted |",
            f"| Reads of the relay log while waiting, at the median wait | 0 | {pub['poll_requests']['median']} | derived: one read every "
            f"{rel['wait_every_s']:g} s for the median of merge-to-paid, {m2p['median']} s |",
            f"| the same at the p95 wait ({m2p['p95']} s) | 0 | {pub['poll_requests']['p95']} | derived |",
            f"| the same when no relay answers ({rel['wait_at_most_s']} s) | 0 | {pub['poll_requests']['timeout']} | derived |",
            f"| Requests in all, at the p95 wait | {own['token_requests']['p95']} | {pub['token_requests']['p95']} | counted + derived |",
            f"| Comments made in the repository | {own['comments']} | {pub['comments']} | counted |",
            f"| Comments the public worker adds to its log | 0 | {pub['relay_log_comments']} | from the code (`ghrelay.once` logs a carried token at once) |",
            f"| Tokens GitHub signs (OIDC) | {own['tokens_signed']} | {pub['tokens_signed']} | counted |",
            f"| Solana transactions | {own['transactions']} | {pub['transactions']} | measured in the simulator (section 2) |",
            f"| Bytes of signed transactions | {own['bytes']:,} | {pub['bytes']:,} | measured in the simulator (p50) |",
            f"| Compute units | {own['cu']:,} | {pub['cu']:,} | measured in the simulator (mean) |",
            f"| Seconds from merge to paid | not timed apart | median {m2p['median']}, p95 {m2p['p95']} | recorded on devnet: {m2p['count']} "
            f"payments in the public relay's log, {lat['window']['from']} to {lat['window']['to']} (`docs/bench.json`) |",
            "| Actions minutes | not measured | not measured | a job's time on the runner was not recorded; standard runners are free in "
            "public repositories |",
            "| RPC requests to send the transactions | not measured | not measured | |", "",
            f"Runner queue time: {lat['stage_split']}.", "",
            "What the public worker itself spends: every pass (one every "
            f"{rel['pass_every_s']:g} s) reads at most {rel['repositories_read_per_pass_at_most']} repositories' newest comments, each a "
            "conditional request. GitHub does not count a conditional request it answers 304 when it carries an Authorization header, so a "
            f"pass that finds nothing new costs nothing against the worker's {L['github_token_requests_per_hour']:,} an hour; a repository "
            f"with a new token costs {rel['counted_reads_per_token']} counted read, and the token {rel['log_comments_per_token']} log comment. "
            f"The search for repositories it does not know runs every {rel['search_every_s']} s, under the search limit of "
            f"{L['search_per_minute']} a minute. A pass carries its tokens one at a time.", "",
            "### The meter's statement (derived from the code)", "",
            "`knos statement --meter` recomputes a month from the program's log lines: the month account's history "
            f"{w['meter']['rows_per_history_request']} rows a request, one `getTransaction` for every transaction in it, and the account "
            f"itself. It reads at most {w['meter']['statement_reads_at_most']:,} transactions. Solana's public endpoints take "
            f"{L['rpc_one_method_per_10s']} requests of one method per 10 seconds from one address, and say they are not for production.", "",
            "| Evaluations a day | RPC requests for a 30-day month, one transaction an evaluation | With one batch a day |", "| --- | --- | --- |"]
    for n, x in w["statement_requests"].items():
        out.append(f"| {int(n):,} | {x['one_by_one']:,} | {x['batched_daily']:,} |")
    out += ["", "### Which limit binds first", "",
            "For a customer with R repositories and N accepted deliverables a day, the work spread evenly over the repositories and over "
            "the day (an assumption: a busier hour lowers every figure in proportion; `--peak` sets it). \"Binds at\" is the N at which "
            "the limit is reached; the model is arithmetic on the numbers above and on the published limits, and none of these volumes was run. "
            "\"Binds first\" is among the limits on the work; the meter's statement is a limit on reading the count back, listed in the last column.", "",
            "| Repositories | Deliverables a day | Token carried by | Binds first | Binds at (a day) | This volume fits | Limits this volume is past |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for a in w["customers"]:
        out.append(f"| {a['repositories']:,} | {a['per_day']:,} | {ways[a['way']]} | {a['first']} | {a['at']:,} | {'yes' if a['fits'] else '**no**'} | "
                   f"{'; '.join(a['binding']) or 'none'} |")
    big = {a["way"]: a for a in w["customers"] if a["per_day"] == max(x["per_day"] for x in w["customers"])}
    at = {way: {r["limit"]: r["at"] for r in big[way]["bounds"]} for way in big}
    rows = []                           # a limit that is the same either way is one row; one that differs is a row for each way
    for way in ("own", "public"):
        other = at["public" if way == "own" else "own"]
        for r in big[way]["bounds"]:
            same = other.get(r["limit"]) == r["at"]
            if not (same and way == "public"):
                rows.append((r, "" if same else f" ({ways[way]})"))
    out += ["", f"Every limit, for the largest of the three ({big['own']['repositories']:,} repositories, {big['own']['per_day']:,} a day), soonest first:", "",
            "| Limit | Whose | Binds at (a day) | From | What lifts it without a program change |", "| --- | --- | --- | --- | --- |"]
    for r, way in sorted(rows, key=lambda x: x[0]["at"]):
        out.append(f"| {r['limit']}{way} | {r['scope']} | {r['at']:,} | {r['from']} | {r['lift']} |")
    out += ["", "What this says. The public worker is a convenience for small volumes. The reads of its log that a waiting job makes "
            "are what uses up a repository's hourly requests first, and its own two limits are shared by every repository it serves. A "
            "customer past them relays in its own job with its own fee key, which removes the token comment, the polling and both "
            "shared limits at once. After that the limits are GitHub's, per repository and per account, long before they are Solana's. "
            "The one bound here that configuration cannot move is the fee account of the mint; of all of them only a single Balance's "
            "is further away.", "",
            "### Measured, recorded, derived", "",
            "| What | How it is known |", "| --- | --- |",
            "| Compute units, transactions and bytes of an order; paid once, none lost | measured in the local simulator, 1,000 orders (sections 1 and 2) |"]
    for r in runs:
        fails = sum(x["failures"] for x in r["stages"].values())
        out.append(f"| Token verification, funding from a wallet, refund and close on a cluster | measured on {r['cluster']}, {r['date']}: "
                   f"{r['orders']:,} orders, {fails} failures (section 4). PayOrder, funding from a Balance and the meter were not sent in that run |")
    out += [f"| Seconds from merge to paid | recorded on devnet, {m2p['count']} payments (`docs/bench.json`) |",
            "| Requests, comments, tokens and jobs of a word | counted from the code against a stand-in for GitHub; not observed on GitHub |",
            "| Limits of GitHub and of Solana | published by them, read on " + w["read"] + " (links below); GitHub says its secondary limits "
            "may change without notice, and its page does not say whether the content limit is counted per repository for a workflow's "
            "token, which this page assumes |",
            "| Cluster rates, the relay log polling, statement requests, every \"binds at\" | derived |",
            "| Actions minutes, runner queue time apart from the rest, RPC requests per order, any GitHub limit actually being hit | not measured |", "",
            "Sources: " + "; ".join(f"[{t}]({u})" for t, u in w["sources"].items()) + ".", ""]
    return out


SOURCES = {"Solana: 100M CU blocks (SIMD-0286), which also states the 12M per-account limit": "https://solana.com/upgrades/100m-cu-blocks",
           "Agave's block cost limits (development branch)": "https://github.com/anza-xyz/agave/blob/master/cost-model/src/block_cost_limits.rs",
           "Solana: slots of 400 ms": "https://solana.com/docs/core/transactions/confirmation"}


def load() -> dict:
    doc = json.loads(JSON.read_text(encoding="utf-8")) if JSON.is_file() else {}
    doc.update(_about=ABOUT, limits=LIMITS, sources=SOURCES)
    doc.setdefault("runs", [])
    return doc


def write(doc: dict) -> None:
    JSON.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    DOC.write_text(render(doc), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Many funded orders at once: measured in the simulator, or against a cluster with a test issuer.")
    ap.add_argument("--local", type=int, metavar="N", help="N orders through the test builds in LiteSVM")
    ap.add_argument("--devnet", type=int, metavar="N", help="N tokens verified and N orders funded and refunded on a cluster")
    ap.add_argument("--issuer-key", help="the test issuer's RSA private key, PEM (openssl genrsa 2048)")
    ap.add_argument("--issuer-url", default=ISSUER_URL)
    ap.add_argument("--wallet", help="the keypair that pays, registers the key and funds (default: KNOS_WALLET_KEY)")
    ap.add_argument("--rpc", help="the cluster's endpoint (default: KNOS_RPC, else public devnet)")
    ap.add_argument("--senders", type=int, default=8, metavar="K", help="units in flight at once")
    ap.add_argument("--no-refund", action="store_true", help="leave the orders open (they can be refunded after a minute by anyone)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--write", action="store_true", help="write docs/load.json and docs/LOAD.md")
    ap.add_argument("--render", action="store_true", help="only render docs/LOAD.md again from docs/load.json")
    a = ap.parse_args(argv)
    doc = load()
    if a.render:
        write(doc)
        return 0
    if a.local:
        got = run_local(a.local, a.seed)
        doc["local"] = got
    elif a.devnet:
        if not a.issuer_key:
            ap.error("--devnet needs --issuer-key: the PEM file of the test issuer's RSA private key (make one with `openssl genrsa -out issuer.pem 2048`)")
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key = load_pem_private_key(Path(a.issuer_key).read_bytes(), password=None)
        ledger = chain.Ledger(a.rpc) if a.rpc else chain.ledger()
        got = run_devnet(Rpc(ledger.url), chain.wallet(a.wallet), key, a.devnet, a.senders, a.issuer_url, refund=not a.no_refund)
        doc["runs"].append(got)
    else:
        ap.error("say --local N or --devnet N")
    print(json.dumps(got, indent=1))
    if a.write:
        write(doc)
    return 0 if (got.get("invariants") or got).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
