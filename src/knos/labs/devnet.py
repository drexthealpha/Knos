"""The lab vault on Solana devnet: the LAB verdict pays the lab, the OUTCOME verdict (science failed) does not pay
the researcher. Real devnet transactions, a test mint of the demo's own (TEST money), lab replies from FIXTURES.

    python -m knos.labs.devnet --wallets DIR --referees RDIR --out web/labs_devnet.json [--fields proteins,electronics,materials,chemistry,robotics]

DIR holds the demo's own devnet keys and is never printed: payer.json (funded beforehand), and the files the demo
makes: mint, the 2-of-3 SPL Token multisig's address, and per field a lab, a researcher and two pots. The three referee
keys live in RDIR, never in the buyer's DIR (refused otherwise). The output file is written after every field.

Per field, each step once:
  1. quote from the lab adapter (fixture), plan: price + 3% Knos lab order fee (config/fees.yaml) + researcher reward
  2. two pots (SPL token accounts owned by the referees' 2-of-3 multisig), funded by the funder in one transaction
  3. order -> status -> results (fixture), LAB verdict and OUTCOME verdict, each signed by 2 of 3 referees (ed25519)
  4. LAB PASS: the multisig releases the price to the lab and the fee to the Knos treasury (memo: the verdict digest)
     proteins: straight to the lab's address (Adaptyv itself bills over x402 on Base: the Base Sepolia payment is
               built and checked, and shown to the public testnet facilitator's /verify, which moves no money)
     electronics: through x402 `exact` on Solana devnet: the release goes to a one-time payment wallet that pays
               the lab's 402 through the public x402.org facilitator, which settles it on devnet
  5. OUTCOME FAIL: the multisig returns the reward to the funder (memo: the verdict digest); the researcher gets 0
  6. the emptied pots are closed (rent back); the public Knos Record line holds hashes, timing and the two verdicts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account

from .. import chain, leitner
from ..money import fees_config
from ..settle.v2 import pay
from . import Spec, escrow, get, privacy, verdicts, x402pay

if TYPE_CHECKING:
    from .electronics import PCBWay
    from .robotics import PyLabRobot

UNIT = 1_000_000
DECIMALS = 6
M = 2


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _key(path: Path) -> Keypair:
    if not path.exists():
        kp = Keypair()
        path.write_text(json.dumps(list(bytes(kp))), encoding="utf-8")
        path.chmod(0o600)
    return Keypair.from_bytes(bytes(json.loads(path.read_text(encoding="utf-8"))))


FIELDS = {"proteins": "adaptyv", "electronics": "pcbway", "materials": "materials_project", "chemistry": "b12_selenium",
          "robotics": "pylabrobot"}


def field_case(field: str) -> dict:
    """The adapter, spec and claim of one field's demo order (fixtures). Every field in FIELDS runs; another is refused."""
    if field not in FIELDS:
        raise ValueError(f"no demo for field {field!r}: one of {', '.join(FIELDS)}")
    if field == "proteins":
        fx = json.loads((Path(__file__).parent / "fixtures" / "adaptyv.json").read_text(encoding="utf-8"))
        spec = Spec("proteins", fx["spec"], qc={"protocol_keys": ["experiment_type", "method", "target_id"], "runs": 3,
                                                 "checks": [{"metric": "positive_control_kd_nm", "op": "<=", "value": 50, "over": "qc"}]},
                    claim={"metric": "kd_nm", "op": "<=", "value": 100, "agg": "min"}, title="Knos demo: two binder designs (fixture)")
        return {"lab": "adaptyv", "spec": spec, "reward": 50 * UNIT, "pay": "direct"}
    if field == "electronics":
        fx = json.loads((Path(__file__).parent / "fixtures" / "pcbway.json").read_text(encoding="utf-8"))
        spec = Spec("electronics", fx["spec"], qc=fx["qc"], claim=fx["claim"], title="Knos demo: a sensor board (fixture)")
        return {"lab": "pcbway", "spec": spec, "reward": 20 * UNIT, "pay": "x402-solana", "bench": fx["bench"]}
    from .contract import adapters
    lab = FIELDS[field]
    return {"lab": lab, "spec": adapters()[lab].example, "reward": 5 * UNIT, "pay": "direct"}


def _price_units(lab: str, spec: Spec) -> tuple[int, str]:
    """The lab pot's price in test units and what it stands for (the contract quote: a free service is priced at the
    Knos check price; b12 credits are shown as test units because a credit's USD price is not published)."""
    from .contract import adapters
    q = adapters()[lab].quote(spec)
    return int(round(q["price"] * UNIT)), q["price_basis"] + (" (credits shown as test units)" if q["currency"] == "credits" else "")


def referee_keys(wallets: Path, referees: Path, payer: Keypair) -> list[Keypair]:
    """The referees' keys, from THEIR folder: never the buyer's. Refused when the folder is the buyer's wallets folder
    (or inside it), or when the funder's own key is one of them: a buyer holding the referee keys could sign FAIL on a
    lab that did the work. Until a referee registry exists (V34PAY), the folder stands in for independent referees;
    on one machine they are not independent, and the output says so."""
    w, r = wallets.resolve(), referees.resolve()
    if r == w or w in r.parents:
        raise ValueError("the referee keys may not live in the buyer's wallets folder: give --referees a folder the referees hold")
    r.mkdir(parents=True, exist_ok=True)
    keys = [_key(r / f"referee-{i}.json") for i in (1, 2, 3)]
    if payer.pubkey() in {k.pubkey() for k in keys}:
        raise ValueError("the funder's key may not be a referee")
    return keys


class Demo:
    def __init__(self, wallets: Path, referees: Path, led=None):
        self.dir = wallets
        self.led = led or chain.ledger()
        if "devnet" not in self.led.url:
            raise SystemExit("devnet only")
        self.payer = _key(wallets / "payer.json")
        self.mint_kp = _key(wallets / "mint.json")
        self.mint = self.mint_kp.pubkey()
        self.referees = referee_keys(wallets, referees, self.payer)
        tag = hashlib.sha256(b"".join(bytes(k.pubkey()) for k in self.referees)).hexdigest()[:8]
        self.ms_kp = _key(wallets / f"multisig-{tag}.json")    # only the account's address; its authority is the referees
        self.ms = self.ms_kp.pubkey()
        self.sent: list[dict] = []
        cfg = fees_config.load()
        self.treasury = Pubkey.from_string(cfg.doc["treasury"]["fee_owner"])

    def send(self, step: str, ixs, signers=()) -> str:
        sig = self.led.send(ixs, self.payer, list(signers))
        self.sent.append({"step": step, "signature": sig, "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet"})
        print(step, sig, flush=True)
        return sig

    def ata(self, owner: Pubkey) -> Pubkey:
        return pay.ata(owner, self.mint)

    def balance(self, account: Pubkey) -> int:
        return escrow.read_token_amount(self.led.account(account)) or 0

    def setup(self, owners: list[Pubkey]) -> None:
        """The test mint, 10,000 test units to the funder, the referees' 2-of-3 multisig, and token accounts."""
        p = self.payer.pubkey()
        if self.led.account(self.mint) is None:
            from solders.instruction import AccountMeta, Instruction
            rent = chain.call(self.led.url, "getMinimumBalanceForRentExemption", [escrow.MINT_LEN])
            init = Instruction(pay.TOKEN, bytes([20, DECIMALS]) + bytes(p) + b"\x00", [AccountMeta(self.mint, False, True)])
            self.send("setup: the demo's own test mint (6 decimals, no freeze authority)",
                      [create_account(CreateAccountParams(from_pubkey=p, to_pubkey=self.mint, lamports=rent, space=escrow.MINT_LEN, owner=pay.TOKEN)), init],
                      [self.mint_kp])
        if self.led.account(self.ata(p)) is None:
            from solders.instruction import AccountMeta, Instruction
            self.send("setup: 10,000 test units to the funder", [pay.create_ata_ix(p, p, self.mint),
                      Instruction(pay.TOKEN, bytes([7]) + (10_000 * UNIT).to_bytes(8, "little"),
                                  [AccountMeta(self.mint, False, True), AccountMeta(self.ata(p), False, True), AccountMeta(p, True, False)])])
        if self.led.account(self.ms) is None:
            rent = chain.call(self.led.url, "getMinimumBalanceForRentExemption", [escrow.MULTISIG_LEN])
            self.send("setup: the referees' 2-of-3 SPL Token multisig (owner of every pot)",
                      [create_account(CreateAccountParams(from_pubkey=p, to_pubkey=self.ms, lamports=rent, space=escrow.MULTISIG_LEN, owner=pay.TOKEN)),
                       escrow.init_multisig_ix(self.ms, [r.pubkey() for r in self.referees], M)], [self.ms_kp])
        missing = [o for o in [self.treasury, *owners] if self.led.account(self.ata(o)) is None]
        if missing:
            self.send("setup: token accounts (Knos treasury, labs, researchers, payment wallet)",
                      [pay.create_ata_ix(p, o, self.mint) for o in missing])

    def run(self, field: str, record_root: Path | None) -> dict:
        case = field_case(field)
        spec: Spec = case["spec"]
        lab_kp = _key(self.dir / f"lab-{field}.json")
        researcher = _key(self.dir / f"researcher-{field}.json").pubkey()
        hop = _key(self.dir / f"payment-wallet-{field}.json").pubkey()
        self.setup([lab_kp.pubkey(), researcher, hop])
        adapter = get(case["lab"])
        ordered_at = _now()
        q = adapter.quote(spec)
        price, price_basis = _price_units(case["lab"], spec)
        run_id = f"{field}-{int(time.time())}"
        p = escrow.plan(f"knos-lab-{run_id}", field, price, case["reward"])
        # 2. the two pots, owned by the multisig, funded by the funder
        pots = {k: Keypair() for k in ("lab", "outcome")}
        rent = chain.call(self.led.url, "getMinimumBalanceForRentExemption", [escrow.ACCOUNT_LEN])
        me = self.payer.pubkey()
        ixs = []
        for k, kp in pots.items():
            ixs += [create_account(CreateAccountParams(from_pubkey=me, to_pubkey=kp.pubkey(), lamports=rent, space=escrow.ACCOUNT_LEN, owner=pay.TOKEN)),
                    escrow.init_account_ix(kp.pubkey(), self.mint, self.ms)]
        ixs += [escrow.transfer_checked_ix(self.ata(me), self.mint, pots["lab"].pubkey(), me, p.lab_pot, DECIMALS),
                escrow.transfer_checked_ix(self.ata(me), self.mint, pots["outcome"].pubkey(), me, p.reward, DECIMALS)]
        fund_sig = self.send(f"{field}: fund the lab pot ({p.lab_pot / UNIT:,.2f} = price + 3% fee) and the outcome pot "
                             f"({p.reward / UNIT:,.2f} reward), both owned by the referees' 2-of-3 multisig", ixs, list(pots.values()))
        # 3. the lab (fixture), the two verdicts, signed 2 of 3
        o = adapter.order(spec, str(pots["lab"].pubkey()), q)
        st = adapter.status(o)
        r = cast("PyLabRobot", adapter).results(o, spec) if case["lab"] == "pylabrobot" else adapter.results(o)
        if case.get("bench"):          # only the electronics case (pcbway) carries a bench
            r = cast("PCBWay", adapter).with_bench(r, case["bench"])
        results_at = _now()
        lab_v = verdicts.lab_verdict(spec, r)
        out_v = verdicts.outcome_verdict(spec, r, lab_v)
        moves = escrow.settlement(p, lab_v, out_v)
        lab_to = lab_kp.pubkey() if case["pay"] == "direct" else hop
        expiry = int(time.time()) + 3600
        lab_msg = verdicts.message(p.order, lab_v, amount=p.price, recipient=str(lab_to), mint=str(self.mint), expiry=expiry, nonce=run_id + ":lab")
        out_msg = verdicts.message(p.order, out_v, amount=p.reward, recipient=str(researcher if out_v.passed else me), mint=str(self.mint),
                                   expiry=expiry, nonce=run_id + ":outcome")
        signers = self.referees[:M]
        lab_sigs, out_sigs = verdicts.sign(lab_msg, signers), verdicts.sign(out_msg, signers)
        refs = [str(k.pubkey()) for k in self.referees]
        for msg, sigs, amt, to in ((lab_msg, lab_sigs, p.price, str(lab_to)), (out_msg, out_sigs, p.reward, out_msg["recipient"])):
            problems = verdicts.check(msg, sigs, refs, M, amount=amt, recipient=to)
            if problems:
                raise SystemExit(f"{field}: a signed verdict would not release: {problems}")
        # Leitner: a new lab sits in box 1 and is checked on every order; a paused one is not paid
        sched = leitner.Scheduler(leitner.load_config(), {}, None)
        sched.add(f"lab:{case['lab']}", "lab", 0)
        if not sched.can_pay(f"lab:{case['lab']}"):
            raise SystemExit("the lab is paused by its last re-check")
        sched.result(f"lab:{case['lab']}", lab_v.passed, 1)
        # 4. LAB verdict releases
        rel: list[dict[str, Any]] = []
        cos = [k.pubkey() for k in signers]
        if lab_v.passed:
            ixs = [escrow.transfer_checked_ix(pots["lab"].pubkey(), self.mint, self.ata(lab_to), self.ms, p.price, DECIMALS, cos),
                   escrow.transfer_checked_ix(pots["lab"].pubkey(), self.mint, self.ata(self.treasury), self.ms, p.fee, DECIMALS, cos),
                   escrow.memo_ix(f"knos-lab-verdict:{verdicts.digest(lab_msg)}"),
                   escrow.close_account_ix(pots["lab"].pubkey(), me, self.ms, cos)]
            sig = self.send(f"{field}: LAB verdict PASS (2 of 3 referees): price to the {'lab' if case['pay'] == 'direct' else 'one-time payment wallet'}, "
                            f"3% fee to the Knos treasury, pot closed", ixs, signers)
            rel.append({"to": "lab", "signature": sig})
        else:
            sig = self.send(f"{field}: LAB verdict FAIL: everything back to the funder",
                            [escrow.transfer_checked_ix(pots["lab"].pubkey(), self.mint, self.ata(me), self.ms, p.lab_pot, DECIMALS, cos),
                             escrow.memo_ix(f"knos-lab-verdict:{verdicts.digest(lab_msg)}"), escrow.close_account_ix(pots["lab"].pubkey(), me, self.ms, cos)], signers)
            rel.append({"to": "funder", "signature": sig})
        x402 = None
        if lab_v.passed and case["pay"] == "x402-solana":
            x402 = self.pay_x402(_key(self.dir / f"payment-wallet-{field}.json"), lab_kp.pubkey(), p.price, field)
            rel.append({"to": "lab", "signature": x402.get("transaction")})
        # 5. OUTCOME verdict
        to = researcher if out_v.passed else me
        sig = self.send(f"{field}: OUTCOME verdict {out_v.verdict} (2 of 3 referees): reward {'to the researcher' if out_v.passed else 'back to the funder; the researcher is not paid'}, pot closed",
                        [escrow.transfer_checked_ix(pots["outcome"].pubkey(), self.mint, self.ata(to), self.ms, p.reward, DECIMALS, cos),
                         escrow.memo_ix(f"knos-lab-verdict:{verdicts.digest(out_msg)}"), escrow.close_account_ix(pots["outcome"].pubkey(), me, self.ms, cos)],
                        signers)
        rel.append({"to": "researcher" if out_v.passed else "funder", "signature": sig})
        base = self.base_sepolia(adapter, o) if field == "proteins" else None
        salt = privacy.new_salt()
        (self.dir / f"salt-{run_id}.txt").write_text(salt, encoding="utf-8")          # the buyer's: never published
        pub = privacy.public_record(order_id=o.order_id, field=field, lab=case["lab"], salt=salt, spec_hash=spec.hash(), lab_v=lab_v,
                                    outcome_v=out_v, ordered_at=ordered_at, results_at=results_at,
                                    turnaround_s=int((datetime.fromisoformat(results_at.replace("Z", "+00:00")) -
                                                      datetime.fromisoformat(ordered_at.replace("Z", "+00:00"))).total_seconds()),
                                    releases=rel, synthetic=True)
        recorded = privacy.record(pub, root=record_root) if record_root else None
        return {"field": field, "lab_adapter": case["lab"], "fixture": adapter.label, "plan": p.to_dict(), "price_basis": price_basis,
                "pots": {k: str(v.pubkey()) for k, v in pots.items()}, "fund_signature": fund_sig,
                "lab_verdict": {**lab_v.to_dict(), "signed": lab_msg, "signatures": lab_sigs, "digest": verdicts.digest(lab_msg)},
                "outcome_verdict": {**out_v.to_dict(), "signed": out_msg, "signatures": out_sigs, "digest": verdicts.digest(out_msg)},
                "settlement": moves, "releases": rel, "x402_solana": x402, "x402_base_sepolia": base, "lab_state": st.lab_state,
                "balances_after": {"lab": self.balance(self.ata(lab_kp.pubkey())), "researcher": self.balance(self.ata(researcher)),
                                   "treasury": self.balance(self.ata(self.treasury))},
                "addresses": {"lab": str(lab_kp.pubkey()), "researcher": str(researcher), "payment_wallet": str(hop)},
                "leitner": {"lab": sched.items[f"lab:{case['lab']}"].__dict__},
                "public_record": pub, "recorded_seq": recorded["seq"] if recorded else None}

    def pay_x402(self, wallet: Keypair, lab: Pubkey, amount: int, field: str) -> dict:
        """The lab bills over x402 `exact` on Solana devnet; the one-time payment wallet pays through the public
        testnet facilitator (it co-signs as fee payer and lands the transfer). The lab side is a stand-in that
        answers 402 with its requirement, then asks the facilitator to verify and settle, as an x402 server does."""
        from ..money import x402_exact
        fac = x402_exact.Facilitator()
        fee_payer = fac.fee_payer(x402pay.SOLANA_DEVNET)
        if not fee_payer:
            raise SystemExit("the x402.org facilitator names no Solana devnet fee payer")
        req = x402_exact.requirement(amount, str(self.mint), str(lab), fee_payer, timeout=120, memo=f"knos-lab-{field}-{int(time.time())}")
        challenge = {"x402Version": 2, "resource": {"url": f"lab-stand-in://{field}/invoice", "description": "lab invoice (stand-in)"}, "accepts": [req]}
        got = x402pay.decode_challenge({"PAYMENT-REQUIRED": x402pay.challenge_header(challenge)})
        chosen = x402pay.choose(got["accepts"])
        bh = self.led._blockhash()
        payload = x402pay.solana_payload(chosen, wallet, bh, decimals=DECIMALS, resource=got["resource"])
        s = fac.verify_and_settle(payload, chosen, confirm=x402_exact.confirm_on(self.led.url))
        self.sent.append({"step": f"{field}: x402 exact on Solana devnet: the payment wallet pays the lab's 402, settled by the x402.org facilitator",
                          "signature": s.get("transaction"), "explorer": f"https://explorer.solana.com/tx/{s.get('transaction')}?cluster=devnet"})
        print("x402", s.get("transaction"), flush=True)
        return {"requirement": chosen, "settlement": {k: s.get(k) for k in ("success", "transaction", "network", "payer", "confirmedBy")}}

    def base_sepolia(self, adapter, order) -> dict:
        """Adaptyv's invoice 402 (fixture, Base Sepolia): the EIP-3009 payment built, checked locally, and shown to the
        public testnet facilitator's /verify (no money moves; the demo wallet holds no Base Sepolia USDC)."""
        from ..money import x402_exact
        inv = adapter.confirm(order)["invoice_id"]
        _s, body, headers = adapter.challenge(inv)
        ch = x402pay.decode_challenge(headers, body)
        req = x402pay.choose(ch["accepts"])
        key = hashlib.sha256((self.dir / "payer.json").read_bytes() + b"knos-base-sepolia-demo").digest()
        payload = x402pay.evm_payload(req, key, resource=ch["resource"])
        local = x402pay.check_evm(payload, req)
        try:
            got = x402_exact.Facilitator().verify(payload, req)
            answer = {k: got.get(k) for k in ("isValid", "invalidReason", "payer")}    # not its message: it echoes r and s
        except x402_exact.Refused as why:
            answer = {"error": str(why)}
        return {"requirement": req, "payer": payload["payload"]["authorization"]["from"], "local_check": local or "ok",
                "facilitator_verify": answer, "note": "no money moves: /verify only; the demo's Base Sepolia address holds no USDC"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.labs.devnet")
    ap.add_argument("--wallets", required=True, type=Path, help="the funder's own keys (payer.json)")
    ap.add_argument("--referees", required=True, type=Path, help="the referees' keys: a folder that is NOT the funder's")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fields", default="proteins,electronics", help=f"comma-separated, from: {', '.join(FIELDS)}")
    ap.add_argument("--record", type=Path, default=None, help="a Knos Record directory for the public lines (default: none written)")
    a = ap.parse_args(argv)
    try:
        d = Demo(a.wallets, a.referees)
    except ValueError as why:
        print(why, file=sys.stderr)
        return 2
    old = {}
    try:
        old = json.loads(a.out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    runs: list[dict] = []
    failed: list[dict] = []

    def write() -> None:            # after every field: what ran is never lost when a later field fails
        out = {"what": "the Knos lab's money, held on Solana devnet until the proof passes: real transactions, TEST money (the demo's own mint), "
                       "lab replies from FIXTURES; the LAB verdict pays the lab even though the science failed, the OUTCOME verdict does not pay "
                       "the researcher",
               "synthetic": True, "cluster": "devnet", "mint": str(d.mint), "multisig": str(d.ms), "m": M,
               "referees": [str(k.pubkey()) for k in d.referees],
               "referees_note": "kept outside the funder's folder; in this demo all three are on one machine, so they are not independent re-runners",
               "treasury": str(d.treasury), "funder": str(d.payer.pubkey()), "written": _now(),
               "runs": old.get("runs", []) + runs, "failed": old.get("failed", []) + failed,
               "signatures": old.get("signatures", []) + d.sent}
        a.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")

    for f in [x.strip() for x in a.fields.split(",") if x.strip()]:
        try:
            runs.append(d.run(f, a.record))
        except Exception as why:  # noqa: BLE001 - a field that fails is reported, and the others still run
            failed.append({"field": f, "error": f"{type(why).__name__}: {str(why)[:300]}", "at": _now()})
            print(f"{f}: FAILED {why}", file=sys.stderr)
        write()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
