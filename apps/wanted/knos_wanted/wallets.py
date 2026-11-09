"""Every money step a person takes in Knos is signed by that person's own passkey.

A signed-in passkey (auth.py) is also a wallet: a LazorKit smart wallet on devnet (knos.settle.v2.passkey_smart)
whose one owner is that passkey's P-256 key. The server never holds a buyer's, a maker's or a lender's key. It
  - makes the wallet (CreateWallet needs no signature) and pays every fee and rent as the relayer,
  - builds each step and returns the 32-byte challenge the passkey signs (navigator.credentials.get),
  - and relays [secp256r1 precompile, the wallet's instruction] once the passkey answered. Solana's secp256r1
    precompile verifies the signature and LazorKit checks what it covered; a signature over anything else moves nothing.
The relayer key (KNOS_WANTED_RELAYER_KEYPAIR, else the app's devnet test wallet KNOS_WANTED_DEVNET_KEYPAIR) pays
fees and is the test mint's authority for the faucet. It is never a buyer, a maker or a lender.

Steps (each `prepare_*` returns {intent, challenge}; `sign` relays the passkey's answer):
  buyer   faucet (devnet test units, labelled test money) -> pre-order: FundOrderWallet of a PANEL order on the knos_pay
          0.3.34 devnet test program, the funder being the buyer's vault. Refunds go back to that vault.
  maker   claim the report's milestone with a passkey: every pre-order then pays a wallet made for that one receivable,
          owned by the maker's passkey.
  lender  the receivable sale: the lender offers cash now (an advance rate, its fee, the due date; tap one); the
          maker's passkey sells the receivable's wallet to the lender's passkey (TransferOwnership); the lender's
          passkey sends the advance to the maker's wallet (tap two); on release knos_pay pays the receivable's wallet,
          which the lender owns now, and the lender's passkey collects it.
  project a milestone of a project funded (or pooled, or granted) from the passkey's wallet, before any maker claims
          it; or an AMC commitment: an allowance from the passkey's wallet, collected only when the milestone verifies.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

from . import auth, company, escrow, preorder

FAUCET_UNITS = 25
INTENT_S = 55                  # LazorKit takes an assertion for 150 slots (about a minute) after the slot it names
ADVANCE_BPS = (5_000, 9_800)   # what a lender may advance of a receivable's face value
_pending: dict[str, dict] = {}
_ensure_locks: dict[str, threading.Lock] = {}
_lock = threading.RLock()
MONEY = "devnet test money: units of this app's own test mint (6 decimals), not USDC, worth nothing"


class NeedPasskey(ValueError):
    pass


def _ps():
    from knos.settle.v2 import passkey_smart as ps
    return ps


def _dir(name: str) -> Path:
    d = escrow._state_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, rec: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def relayer():
    return preorder.relayer()


def holder(user: dict | None) -> dict:
    """The passkey behind a session: its credential id hash, compressed key and last flags/count."""
    c = auth.credential(str((user or {}).get("sub", ""))) if user else None
    if not c:
        raise NeedPasskey("this step is signed by your own passkey: sign in with a passkey (Google, email and guest sessions hold no wallet)")
    ps = _ps()
    from knos.settle.v2.passkey import compressed
    return {"sub": user["sub"], "label": user.get("label", ""), "cred_id": c["cred_id"], "cred_hash": ps.cred_hash(auth.unb64u(c["cred_id"])),
            "key": compressed(auth.unb64u(c["spki"])), "flags": int(c.get("flags", ps.UP | ps.UV)), "sign_count": int(c.get("sign_count", 0))}


def addresses(h: dict, purpose: str = "main", extra: bytes = b"") -> dict:
    ps = _ps()
    w = ps.wallet_pda(ps.user_seed(purpose, h["cred_hash"], extra))
    return {"wallet": w, "vault": ps.vault_pda(w), "authority": ps.authority_pda(w, h["cred_hash"])[0], "seed": ps.user_seed(purpose, h["cred_hash"], extra)}


# ---- the ledger: slot, v0 sends, lookup tables ----------------------------------------------------------------------
def _slot(led) -> int:
    if hasattr(led, "slot"):
        return int(led.slot())
    from knos import chain
    return int(chain.call(led.url, "getSlot", [{"commitment": "confirmed"}]))


def _send_v0(led, ixs, tables) -> str:
    if hasattr(led, "send_v0"):
        return led.send_v0(ixs, relayer(), tables)
    from solders.transaction import VersionedTransaction

    from knos import chain
    tx = VersionedTransaction(_ps().message_v0(relayer().pubkey(), ixs, tables, led._blockhash()), [relayer()])
    sig = led._submit(tx)
    chain.wait(led.url, sig, 60.0, "confirmed")
    return sig


def _table(led, name: str, addrs: list) -> tuple:
    """A lookup table of the relayer's for `addrs`, made once (state/tables.json) and read back from the chain."""
    ps = _ps()
    f = _dir("wallets") / "tables.json"
    with _lock:
        known = _read(f) or {}
        if name in known:
            from solders.pubkey import Pubkey
            t = Pubkey.from_string(known[name])
            got = ps.read_table(led.account(t))
            if got[:len(addrs)] == list(addrs):
                return t, got
            if not name.startswith("wallet:"):                # a shared table that no longer fits: retired, its rent comes back
                known.setdefault("_retired", []).append(known[name])
        recent = int(led.recent_slot()) if hasattr(led, "recent_slot") else _slot(led) - 2
        t, ixs = ps.create_table_ixs(relayer().pubkey(), relayer().pubkey(), recent, list(addrs))
        led.send(ixs, relayer())
        made = _slot(led)
        for _ in range(40):                                  # a table serves from the slot after its extension
            if _slot(led) > made:
                break
            if hasattr(led, "tick"):
                led.tick()
            else:
                time.sleep(0.4)
        if name.startswith("wallet:"):                       # a wallet's table never changes: frozen, so nobody can change it
            from . import chainx
            try:
                led.send([chainx.alt_ix(chainx.ALT_FREEZE, t, relayer().pubkey())], relayer())
            except Exception:  # noqa: BLE001 - an unfrozen table still serves; freezing is a guarantee, not a need
                pass
        known[name] = str(t)
        _write(f, known)
        return t, list(addrs)


def retire_tables(led) -> list[dict]:
    """The relayer's retired lookup tables: deactivated first, then closed once the cooldown passed (rent returned to
    the relayer). The sweeper calls this; each table moves one step per call."""
    from solders.pubkey import Pubkey

    from . import chainx
    f = _dir("wallets") / "tables.json"
    out = []
    with _lock:
        known = _read(f) or {}
        keep = []
        for t in known.get("_retired", []):
            data = led.account(Pubkey.from_string(t))
            if data is None:
                continue                                         # closed already
            deactivated = int.from_bytes(data[4:12], "little") != (1 << 64) - 1
            try:
                if not deactivated:
                    sig = led.send([chainx.alt_ix(chainx.ALT_DEACTIVATE, Pubkey.from_string(t), relayer().pubkey())], relayer())
                    out.append({"table": t, "step": "deactivated", "signature": sig})
                else:
                    sig = led.send([chainx.alt_ix(chainx.ALT_CLOSE, Pubkey.from_string(t), relayer().pubkey(), relayer().pubkey())], relayer())
                    out.append({"table": t, "step": "closed", "signature": sig, "rent_returned_lamports": len(data) and led.rent(len(data))})
                    continue
            except Exception as why:  # noqa: BLE001 - still cooling down: tried again on the next sweep
                out.append({"table": t, "step": "waiting", "why": str(why)[:120]})
            keep.append(t)
        known["_retired"] = keep
        _write(f, known)
    return out


def _tables(led, mint, h: dict | None = None) -> list:
    ps = _ps()
    out = [_table(led, f"shared:{preorder.program()}:{mint}", ps.table_addresses(preorder.program(), mint))]
    if h is not None:
        a = addresses(h)
        out.append(_table(led, f"wallet:{a['wallet']}:{mint}", ps.wallet_table_addresses(a["wallet"], h["cred_hash"], mint)))
    return out


def _units(led, token_account) -> int:
    """A token account's amount, read from its bytes (64..72 of an SPL token account): no RPC beyond getAccountInfo."""
    d = led.account(token_account)
    return int.from_bytes(d[64:72], "little") if d and len(d) >= 72 else 0


# ---- the wallet -----------------------------------------------------------------------------------------------------
def ensure(led, h: dict, rp_id: str, purpose: str = "main", extra: bytes = b"") -> dict:
    """The passkey's wallet, made by the relayer the first time (no signature of the passkey is needed to make one)."""
    from knos.settle.v2 import pay
    ps = _ps()
    a = addresses(h, purpose, extra)
    sig = None
    # one creation per wallet: two requests of one person at once (the page loading its wallet while a button is
    # pressed) would both send CreateWallet, and the second fails with AccountAlreadyInitialized
    with _lock:
        lk = _ensure_locks.setdefault(str(a["authority"]), threading.Lock())
    with lk:
        if led.account(a["authority"]) is None:
            sig = led.send([ps.create_wallet_ix(relayer().pubkey(), a["seed"], h["cred_hash"], h["key"], rp_id)], relayer())
        m = escrow.mint(led)
        tok = pay.ata(a["vault"], m)
        if purpose == "main" and led.account(tok) is None:
            led.send([pay.create_ata_ix(relayer().pubkey(), a["vault"], m)], relayer())
    return {**a, "created": sig, "token_account": tok, "mint": m}


def public(led, h: dict, rp_id: str) -> dict:
    w = ensure(led, h, rp_id)
    units = _units(led, w["token_account"]) / escrow.UNIT
    return {"wallet": str(w["wallet"]), "vault": str(w["vault"]), "token_account": str(w["token_account"]), "balance_units": units,
            "kind": "LazorKit smart wallet on devnet, owned by your passkey (P-256, checked by Solana's secp256r1 precompile)",
            "program": str(_ps().LAZOR_ID), "explorer": escrow.explorer(str(w["vault"]), "address"), "created": w["created"],
            "money": MONEY}


def faucet(led, h: dict, rp_id: str) -> dict:
    """Test units of this app's own devnet test mint to the passkey's wallet: devnet test money, worth nothing."""
    w = ensure(led, h, rp_id)
    with _lock:
        auth = escrow.demo_key()                 # the test mint's authority (`escrow`.mint); the relayer may be another key
        sig = led.send([escrow._mint_to_ix(w["mint"], w["token_account"], auth.pubkey(), FAUCET_UNITS)], auth)
    return {"signature": sig, "explorer": escrow.explorer(sig), "units": FAUCET_UNITS, "to": str(w["vault"]), "mint": str(w["mint"]), "money": MONEY}


# ---- intents: what waits for a passkey ------------------------------------------------------------------------------
_fee_seen: dict = {}


def network_fee() -> dict | None:
    """What devnet charges for the step before anyone signs: getFeeForMessage on a one-memo message the relayer pays
    (every passkey step is sent by the relayer, one signature). Asked at most once a minute."""
    import base64

    from solders.hash import Hash
    from solders.instruction import Instruction
    from solders.message import Message
    from solders.pubkey import Pubkey

    from knos import chain
    if time.time() - _fee_seen.get("at", 0) < 60:
        return _fee_seen.get("fee")
    try:
        url = escrow.ledger().url
        bh = chain.call(url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
        memo = Instruction(Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"), b"knos", [])
        msg = Message.new_with_blockhash([memo], relayer().pubkey(), Hash.from_string(bh))
        got = chain.call(url, "getFeeForMessage", [base64.b64encode(bytes(msg)).decode(), {"commitment": "confirmed"}])
        fee = {"lamports": got["value"], "sol": got["value"] / 1e9, "paid_by": "the relayer (not you)", "method": "getFeeForMessage"}
    except Exception:  # noqa: BLE001 - the step still works; the card then says the fee could not be read
        fee = None
    _fee_seen.update(at=time.time(), fee=fee)
    return fee


def _intent(kind: str, h: dict, prep, meta: dict, summary: dict) -> dict:
    summary = {**summary, "network_fee": network_fee()}
    with _lock:
        now = time.time()
        for k in [k for k, v in _pending.items() if now - v["at"] > INTENT_S]:
            _pending.pop(k)
        iid = secrets.token_urlsafe(12)
        _pending[iid] = {"kind": kind, "sub": h["sub"], "prep": prep, "meta": meta, "at": now, "summary": summary}
    return _out(iid)


def _out(iid: str) -> dict:
    p = _pending[iid]
    prep = p["prep"]
    return {"intent": iid, "kind": p["kind"], "challenge": auth.b64u(prep.challenge), "credential": auth.b64u(auth.unb64u(p["meta"]["cred_id"])),
            "rp_id": prep.rp_id, "parts": prep.parts(), "summary": p["summary"], "expires_in_s": INTENT_S,
            "what_signs": "your passkey; the server only relays and pays the fee"}


def _prep(led, h: dict, a: dict, inner, pre=()):
    ps = _ps()
    au = ps.read_authority(led.account(a["authority"]))
    if au is None:
        raise ValueError("this wallet is not owned by your passkey (no authority of yours on chain)")
    return ps.execute(relayer().pubkey(), a["wallet"], a["authority"], list(inner), slot=_slot(led), counter=au.counter + 1, rp_id=au.rp_id,
                      key=h["key"], flags=h["flags"], sign_count=ps.next_count(h["sign_count"]), pre=list(pre))


def sign(led, user: dict, body: dict) -> dict:
    """Relay the passkey's answer to an intent. When the authenticator answered with other flags or count than
    predicted, the same step is prepared again with what it answered: {again: true, challenge} (one more touch)."""
    ps = _ps()
    iid = str(body.get("intent", ""))
    with _lock:
        p = _pending.get(iid)
        if p is None or time.time() - p["at"] > INTENT_S:
            raise ValueError("this step expired (a passkey approval is good for about a minute): start it again")
        if p["sub"] != (user or {}).get("sub"):
            raise NeedPasskey("this step waits for another passkey")
        prep = p["prep"]
        try:
            ad, cd, sg = (auth.unb64u(str(body.get(k, ""))) for k in ("authenticatorData", "clientDataJSON", "signature"))
            ixs = prep.finish(ad, cd, sg)
        except ps.Mismatch as m:
            prep.flags, prep.sign_count, prep.type_flags, prep.slot = m.flags, m.sign_count, m.type_flags, _slot(led)
            p["at"] = time.time()
            return {**_out(iid), "again": True, "why": str(m)}
        _pending.pop(iid)
    pre = []
    if prep.pre:
        pre.append(led.send(prep.pre, relayer()))
    sig = _send_v0(led, ixs[len(prep.pre):], p["meta"].get("tables") or [])
    auth.seen(p["sub"], ad)
    done = {"preorder": _done_preorder, "accept": _done_accept, "advance": _done_advance, "collect": _done_collect,
            "project_fund": _done_project_fund, "amc": _done_amc, "company": _done_company}[p["kind"]]
    return done(led, p, sig, pre)


# ---- buyer: the pre-order -------------------------------------------------------------------------------------------
def _maker_file(report_hash: str) -> Path:
    if not isinstance(report_hash, str) or len(report_hash) != 64:
        raise ValueError("report: its 64-hex hash")
    return _dir("makers") / f"{report_hash}.json"


def maker_of(report_hash: str) -> dict | None:
    return _read(_maker_file(report_hash))


def claim_maker(led, user: dict, report: dict, rp_id: str) -> dict:
    """The signed-in passkey becomes the maker of this report's milestone: pre-orders from now pay wallets that this
    passkey owns (one per receivable). First come; the same passkey may claim again."""
    h = holder(user)
    f = _maker_file(report["hash"])
    with _lock:
        cur = _read(f)
        if cur and cur["sub"] != h["sub"]:
            raise ValueError("another maker's passkey claimed this milestone already")
        main = ensure(led, h, rp_id)
        rec = {"sub": h["sub"], "label": h["label"][:80], "cred_hash": h["cred_hash"].hex(), "key": h["key"].hex(), "rp_id": rp_id,
               "main_vault": str(main["vault"]), "claimed": cur["claimed"] if cur else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _write(f, rec)
    return {"report": report["hash"], "maker": rec["label"], "paid_at": "a wallet per receivable, owned by your passkey", "main_wallet": rec["main_vault"],
            "claimed": rec["claimed"]}


def prepare_preorder(led, user: dict, report: dict, units, rp_id: str, funder: bool = False) -> dict:
    """The pre-order a buyer's passkey signs: test units from the buyer's own wallet into a PANEL order of knos_pay,
    released by 2 of 3 referees to the maker's receivable wallet, refunded to the buyer's wallet after the deadline."""
    from solders.pubkey import Pubkey

    from knos import ideas
    from knos.ideas import commit as C
    from knos.ideas import wanted as W
    from knos.settle.v2 import passkey_fund as pf
    from knos.settle.v2 import pay
    ps = _ps()
    d = report.get("decision") or {}
    if d.get("verdict") != "OPEN" or report.get("label", "").startswith("NO QLOO"):
        raise ValueError("pre-orders open only on a report whose decision is OPEN on live Qloo evidence")
    preorder._need()
    if isinstance(units, bool) or not isinstance(units, int) or not 5 <= units <= min(1000, d["target_units"]):
        raise ValueError(f"units: 5 to {min(1000, d['target_units'])} (the report's target)")
    h = holder(user)
    mk = maker_of(report["hash"])
    if not mk:
        raise ValueError("no maker has claimed this milestone yet: the maker claims it with a passkey, then pre-orders open")
    price = int((d.get("plan") or {}).get("unit_price") or preorder.PRICE)
    days = max(1, min(preorder.MAX_DAYS, int(os.environ.get("KNOS_WANTED_MILESTONE_DAYS", "30"))))
    buyer = ensure(led, h, rp_id)
    mint, prog, (pm, pkeys) = buyer["mint"], preorder.program(), preorder.panel()
    with preorder._lock:
        n = len(preorder.of_report(report["hash"])) + sum(1 for v in _pending.values() if v["meta"].get("report") == report["hash"]) + 1
    claim = ideas.claim(f"Pre-order {n} for: {report['idea']} (Knos demand report {report['hash'][:16]})", field_name=preorder.FIELD,
                        kind="person", by={"app": "knos demand check", "report": report["hash"], "buyer": f"passkey {h['sub']}"[:80]})
    maker = {"cred_hash": bytes.fromhex(mk["cred_hash"]), "key": bytes.fromhex(mk["key"])}
    rseed = ps.user_seed("receivable", maker["cred_hash"], claim["id"].encode())
    rwallet = ps.wallet_pda(rseed)
    rvault = ps.vault_pda(rwallet)
    payee = C.parse_payee(str(rvault))
    # the panel every new order pins (preorder.panel): the FROST referee group key (1 of 1, 2 of 3 hosts sign it)
    # when this server is a FROST host, else 2 of the 3 server-held keys
    m_, keys_, label = C.parse_panel(f"{pm}:{','.join(pkeys)}", buyer["vault"], str(rvault), True)
    p = W.plan(claim, units=units, price=price, stages=[("referee_pass", 10_000)], stage_work_s=[days * 86_400], demand_hash=report["hash"])
    amount = p["stage1"]["amount"]
    need = amount + pay.order_fee(amount)
    have = _units(led, buyer["token_account"])
    if have < need:
        raise ValueError(f"your passkey wallet holds {have / escrow.UNIT:g} test units; this pre-order needs {need / escrow.UNIT:g} "
                         "(amount and fee): get devnet test units first")
    fund = W.fund_panel_ix(p, "stage1", buyer["vault"], buyer["token_account"], mint, m_, [bytes(Pubkey.from_string(k)) for k in keys_],
                           program=prog, unlisted_panel=True)
    order = W.panel_address(p, "stage1", buyer["vault"], program=prog)
    if led.account(order) is not None:
        raise ValueError("this order is funded already")
    pre = pf.rent_ixs(relayer().pubkey(), order, pay.ov_pda(order, prog), led.rent(pf.ORDER_LEN), led.rent(165))
    if led.account(ps.authority_pda(rwallet, maker["cred_hash"])[0]) is None:
        pre.insert(0, ps.create_wallet_ix(relayer().pubkey(), rseed, maker["cred_hash"], maker["key"], mk["rp_id"]))
    if led.account(pay.ata(pay.FEE_OWNER, mint)) is None:
        pre.insert(0, pay.create_ata_ix(relayer().pubkey(), pay.FEE_OWNER, mint))
    prep = _prep(led, h, buyer, [fund], pre)
    meta = {"cred_id": h["cred_id"], "report": report["hash"], "idea": report["idea"], "units": units, "price": price, "days": days,
            "claim": claim, "plan_hash": p["commitment_hash"], "order": str(order), "funder": funder, "buyer_vault": str(buyer["vault"]),
            "payee": payee, "panel": {"m": m_, "keys": keys_, "unlisted": True, "label": label}, "program": str(prog), "mint": str(mint),
            "warnings": p["warnings"], "receivable": {"wallet": str(rwallet), "vault": str(rvault), "maker_sub": mk["sub"], "claim": claim["id"]},
            "buyer_label": f"{user.get('kind')}: {user.get('label')}"[:80], "tables": _tables(led, mint, h)}
    summary = {"what": "pre-order", "amount_units": amount / escrow.UNIT, "fee_units": pay.order_fee(amount) / escrow.UNIT,
               "from": str(buyer["vault"]), "order": str(order), "paid_on_proof_to": str(rvault), "refunded_to": str(buyer["token_account"]),
               "program": str(prog), "deadline_days": days, "money": MONEY}
    return _intent("preorder", h, prep, meta, summary)


def _done_preorder(led, p: dict, sig: str, pre: list) -> dict:
    m = p["meta"]
    order = m["order"]
    if led.account(__import__("solders.pubkey", fromlist=["Pubkey"]).Pubkey.from_string(order)) is None:
        raise RuntimeError("the pre-order transaction was sent but the order is not on chain")
    doc = {"v": 1, "kind": "knos-idea-commitment", "claim": m["claim"], "commitment_hash": m["plan_hash"],
           "plan_args": {"units": m["units"], "price": m["price"], "stages": [["referee_pass", 10_000]], "stage_work_s": [m["days"] * 86_400],
                         "demand": m["report"], "maker_github_id": None},
           "judge": "panel", "panel": m["panel"], "payee": m["payee"], "program": m["program"], "mint": m["mint"], "funder": m["buyer_vault"],
           "orders": {"stage1": {"order": order, "oracle": "referee_pass", "amount": m["units"] * m["price"] * escrow.UNIT,
                                 "work_s": m["days"] * 86_400, "signature": sig, "note": None}},
           "warnings": m["warnings"], "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cluster": "devnet",
           "signed_by": "the buyer's passkey (LazorKit Execute, secp256r1 precompile)"}
    from knos.ideas import commit as C
    C.plan_of(doc)                                         # the commitment recomputes: what was signed is what is filed
    rec = {"order": order, "report": m["report"], "idea": m["idea"], "claim_id": m["claim"]["id"], "units": m["units"], "unit_price": m["price"],
           "via": preorder.FUNDER_VIA if m["funder"] else preorder.PREORDER_VIA, "via_kind": "funder" if m["funder"] else "preorder",
           "buyer": f"passkey wallet {m['buyer_vault']} ({m['buyer_label']})", "maker_wallet": m["receivable"]["vault"],
           "receivable": m["receivable"], "status": "locked", "deadline_days": m["days"], "doc": doc, "made": doc["made"],
           "signatures": {"setup": pre[0] if pre else None, "lock": sig}}
    rec["record"] = company.record_lock(m["report"], order, m["units"], sig)
    preorder._save(rec)
    return preorder.public(rec)


# ---- lender: quotes, the maker's acceptance, the advance, the collection --------------------------------------------
def _lender_rec(h: dict, rp_id: str) -> dict:
    return {"sub": h["sub"], "label": h["label"][:80], "cred_hash": h["cred_hash"].hex(), "key": h["key"].hex(), "rp_id": rp_id}


def receivables() -> list[dict]:
    """Every pre-order paid to a maker's receivable wallet, as a lender sees it (a PayFi receivable)."""
    out = []
    for rec in preorder_records():
        if not rec.get("receivable"):
            continue
        face = rec["units"] * int(rec.get("unit_price") or preorder.PRICE)
        made = time.mktime(time.strptime(rec["made"], "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        f = rec.get("factoring") or {}
        out.append({"commitment": rec["order"], "idea": rec.get("idea"), "face_units": face, "status": rec["status"],
                    "due": time.strftime("%Y-%m-%d", time.gmtime(made + rec["deadline_days"] * 86_400)), "receivable_wallet": rec["receivable"]["vault"],
                    "factoring": {k: v for k, v in f.items() if k not in ("lender_key", "lender_cred")}, "quotes": [
                        {k: v for k, v in q.items() if k in ("id", "advance_bps", "advance_units", "fee_units", "fee_pct", "lender", "made")}
                        for q in f.get("quotes", [])]})
    return out


def preorder_records() -> list[dict]:
    out = []
    for f in sorted(preorder._dir().glob("*.commit")):
        r = _read(f)
        if r:
            out.append(r)
    return out


def quote(led, user: dict, commitment: str, advance_bps, rp_id: str) -> dict:
    """A lender's quote on a receivable: how much it advances now (advance rate), what it keeps (the fee: face less
    advance), repaid by the release. No money moves until the maker accepts and the lender's passkey pays."""
    h = holder(user)
    rec = preorder.load(commitment)
    if not rec.get("receivable") or rec["status"] != "locked":
        raise ValueError("only a locked pre-order paid to a maker's receivable wallet can be financed")
    if (rec.get("factoring") or {}).get("status") in ("assigned", "advanced", "repaid"):
        raise ValueError("this receivable is sold already")
    if rec["receivable"]["maker_sub"] == h["sub"]:
        raise ValueError("a maker cannot lend against its own receivable")
    bps = int(advance_bps)
    if not ADVANCE_BPS[0] <= bps <= ADVANCE_BPS[1]:
        raise ValueError(f"advance rate: {ADVANCE_BPS[0] / 100:g}% to {ADVANCE_BPS[1] / 100:g}% of face value")
    ensure(led, h, rp_id)
    face = rec["units"] * int(rec.get("unit_price") or preorder.PRICE) * escrow.UNIT
    adv = face * bps // 10_000
    q = {"id": secrets.token_hex(4), "advance_bps": bps, "advance_units": adv / escrow.UNIT, "fee_units": (face - adv) / escrow.UNIT,
         "fee_pct": round((face - adv) * 100 / face, 2), "lender": h["label"][:80] or "lender", "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         **{"lender_" + k: v for k, v in _lender_rec(h, rp_id).items()}}
    with preorder._lock:
        rec = preorder.load(commitment)
        f = rec.setdefault("factoring", {"status": "quoted", "quotes": []})
        f.setdefault("quotes", []).append(q)
        preorder._save(rec)
    return {k: v for k, v in q.items() if not k.startswith("lender_")}


def _controls(led, wallet) -> list:
    ps = _ps()
    out = []
    for disc, off in ps.control_filters(wallet):
        out += led.program_accounts(ps.LAZOR_ID, memcmp={0: bytes([disc]), off: bytes(wallet)})
    return out


def prepare_accept(led, user: dict, commitment: str, quote_id: str) -> dict:
    """The maker's passkey hands the receivable's wallet to the lender's passkey (LazorKit TransferOwnership)."""
    from solders.pubkey import Pubkey
    ps = _ps()
    h = holder(user)
    rec = preorder.load(commitment)
    r = rec.get("receivable") or {}
    if r.get("maker_sub") != h["sub"]:
        raise NeedPasskey("only the maker's passkey can sell this receivable")
    preorder.chain_gate(rec, led)
    q = next((q for q in (rec.get("factoring") or {}).get("quotes", []) if q["id"] == quote_id), None)
    if q is None:
        raise ValueError("unknown quote")
    w = Pubkey.from_string(r["wallet"])
    cur = ps.authority_pda(w, h["cred_hash"])[0]
    ok, why = ps.sole_owner(_controls(led, w), w, h["cred_hash"], _slot(led))
    if not ok:
        raise ValueError(f"the receivable's wallet cannot be sold: {why}")
    au = ps.read_authority(led.account(cur))
    prep = ps.transfer_ownership(relayer().pubkey(), w, cur, bytes.fromhex(q["lender_cred_hash"]), bytes.fromhex(q["lender_key"]), q["lender_rp_id"],
                                 slot=_slot(led), counter=au.counter + 1, rp_id=au.rp_id, key=h["key"], flags=h["flags"],
                                 sign_count=ps.next_count(h["sign_count"]))
    summary = {"what": "sell the receivable", "receivable_wallet": r["vault"], "to_lender": q["lender"], "advance_units": q["advance_units"],
               "fee_units": q["fee_units"], "face_units": rec["units"] * int(rec.get("unit_price") or preorder.PRICE),
               "note": "after this the release pays the lender; the lender's passkey then pays you the advance"}
    return _intent("accept", h, prep, {"cred_id": h["cred_id"], "commitment": commitment, "quote": q["id"]}, summary)


def _done_accept(led, p: dict, sig: str, pre: list) -> dict:
    from solders.pubkey import Pubkey
    ps = _ps()
    m = p["meta"]
    with preorder._lock:
        rec = preorder.load(m["commitment"])
        f = rec["factoring"]
        q = next(q for q in f["quotes"] if q["id"] == m["quote"])
        w = Pubkey.from_string(rec["receivable"]["wallet"])
        ok, why = ps.sole_owner(_controls(led, w), w, bytes.fromhex(q["lender_cred_hash"]), _slot(led))
        f.update(status="assigned" if ok else "assignment unclear", accepted=q["id"], lender=q["lender"], lender_sub=q["lender_sub"],
                 advance_units=q["advance_units"], fee_units=q["fee_units"], advance_bps=q["advance_bps"], owner_check=why)
        rec["signatures"]["sold_to_lender"] = sig
        preorder._save(rec)
    return preorder.public(rec)


def _transfer_ix(src, mint, dst, owner, amount: int):
    from solders.instruction import AccountMeta, Instruction

    from knos.settle.v2 import pay
    return Instruction(pay.TOKEN, bytes([12]) + int(amount).to_bytes(8, "little") + bytes([6]),
                       [AccountMeta(src, False, True), AccountMeta(mint, False, False), AccountMeta(dst, False, True), AccountMeta(owner, True, False)])


def prepare_advance(led, user: dict, commitment: str, rp_id: str) -> dict:
    """The lender's passkey pays the advance from its wallet to the maker's wallet."""
    from solders.pubkey import Pubkey

    from knos.settle.v2 import pay
    ps = _ps()
    h = holder(user)
    rec = preorder.load(commitment)
    f = rec.get("factoring") or {}
    if f.get("status") != "assigned" or f.get("lender_sub") != h["sub"]:
        raise ValueError("the advance is paid by the lender whose quote the maker accepted, once the receivable is assigned")
    w = Pubkey.from_string(rec["receivable"]["wallet"])
    ok, why = ps.sole_owner(_controls(led, w), w, h["cred_hash"], _slot(led))
    if not ok:
        raise ValueError(f"the receivable is not yours on chain: {why}")
    me = ensure(led, h, rp_id)
    mk = maker_of(rec["report"])
    to_vault = Pubkey.from_string(mk["main_vault"])
    to = pay.ata(to_vault, me["mint"])
    amount = int(round(f["advance_units"] * escrow.UNIT))
    if _units(led, me["token_account"]) < amount:
        raise ValueError(f"your passkey wallet holds less than the advance ({f['advance_units']:g} test units): get devnet test units first")
    pre = [pay.create_ata_ix(relayer().pubkey(), to_vault, me["mint"])] if led.account(to) is None else []
    prep = _prep(led, h, me, [_transfer_ix(me["token_account"], me["mint"], to, me["vault"], amount)], pre)
    return _intent("advance", h, prep, {"cred_id": h["cred_id"], "commitment": commitment, "amount": amount, "tables": _tables(led, me["mint"], h)},
                   {"what": "pay the advance", "amount_units": amount / escrow.UNIT, "to_maker_wallet": str(to_vault), "from": str(me["vault"])})


def _done_advance(led, p: dict, sig: str, pre: list) -> dict:
    with preorder._lock:
        rec = preorder.load(p["meta"]["commitment"])
        rec["factoring"]["status"] = "advanced"
        rec["signatures"]["advance"] = sig
        preorder._save(rec)
    return preorder.public(rec)


def prepare_collect(led, user: dict, commitment: str, rp_id: str) -> dict:
    """After the release, the lender's passkey moves what the receivable's wallet received to its own wallet."""
    from solders.pubkey import Pubkey

    from knos.settle.v2 import pay
    ps = _ps()
    h = holder(user)
    rec = preorder.load(commitment)
    f = rec.get("factoring") or {}
    if f.get("lender_sub") != h["sub"] or f.get("status") not in ("advanced", "assigned"):
        raise ValueError("only the lender who bought this receivable collects it")
    w = Pubkey.from_string(rec["receivable"]["wallet"])
    rvault = ps.vault_pda(w)
    mint = Pubkey.from_string(rec["doc"]["mint"])
    src = pay.ata(rvault, mint)
    amount = _units(led, src)
    if not amount:
        raise ValueError("nothing to collect yet: the release pays the receivable's wallet when the milestone is proven")
    me = ensure(led, h, rp_id)
    a = {"wallet": w, "vault": rvault, "authority": ps.authority_pda(w, h["cred_hash"])[0]}
    prep = _prep(led, h, a, [_transfer_ix(src, mint, me["token_account"], rvault, amount)])
    return _intent("collect", h, prep, {"cred_id": h["cred_id"], "commitment": commitment, "amount": amount},
                   {"what": "collect the repayment", "amount_units": amount / escrow.UNIT, "from_receivable": str(rvault), "to": str(me["vault"])})


def _done_collect(led, p: dict, sig: str, pre: list) -> dict:
    with preorder._lock:
        rec = preorder.load(p["meta"]["commitment"])
        rec["factoring"]["status"] = "repaid"
        rec["factoring"]["repaid_units"] = p["meta"]["amount"] / escrow.UNIT
        rec["signatures"]["collect"] = sig
        preorder._save(rec)
    return preorder.public(rec)


# ---- projects: a milestone funded, pooled or committed by a passkey -------------------------------------------------
def prepare_project_fund(led, user: dict, pid: str, key: str, units, rp_id: str, kind: str = "funder", grant: dict | None = None,
                         ref: str | None = None, pool: str | None = None, private: bool = False) -> dict:
    """A project milestone funded from the passkey's own wallet: a PANEL order of knos_pay (the same FundOrderWallet as
    a pre-order), released on the maker's result and an independent check, refunded to this wallet after the deadline.
    No maker is needed yet: the payee is the attempt's wallet, named in the verdict when the milestone is released."""
    from solders.pubkey import Pubkey

    from knos import ideas
    from knos.ideas import commit as C
    from knos.ideas import wanted as W
    from knos.settle.v2 import passkey_fund as pf
    from knos.settle.v2 import pay

    from . import valley
    if kind not in ("funder", "grant", "pool"):
        raise ValueError("kind: funder, grant or pool")
    if isinstance(units, bool) or not isinstance(units, int) or not 5 <= units <= 1000:
        raise ValueError("units: 5 to 1,000 test units")
    if kind == "grant":
        grant = {k: str((grant or {}).get(k) or "").strip()[:120] for k in ("agency", "id", "url")}
        if not grant["agency"] or not grant["id"]:
            raise ValueError("grant: the agency and the grant's id (the award it comes from)")
    referral = valley.load_referral(ref) if ref else None
    p = valley.project(pid)
    m = valley._milestone(p, key)
    if m["status"] == "released":
        raise ValueError("this milestone is already released")
    crit = valley.gate(p)["criteria_hash"]
    preorder._need()
    h = holder(user)
    me = ensure(led, h, rp_id)
    mint, prog, (pm, pkeys) = me["mint"], preorder.program(), preorder.panel()
    claim = ideas.claim(valley.memo(p, m, crit), field_name=preorder.FIELD, kind="person", by={"app": "knos projects", "project": pid, "milestone": key,
                                                                       "funder": f"passkey {h['sub']}"[:80]})
    m_, keys_, label = C.parse_panel(f"{pm}:{','.join(pkeys)}", me["vault"], str(me["vault"]), True)
    from knos import ready
    tranches = ready.tranches(int(m["deadline_s"]))       # an order holds money 90 days at most: a long milestone, in tranches
    plan = W.plan(claim, units=units, price=1, stages=[("referee_pass", 10_000)], stage_work_s=[tranches[0]], demand_hash=p.get("report"))
    amount = plan["stage1"]["amount"]
    need = amount + pay.order_fee(amount)
    have = _units(led, me["token_account"])
    if have < need:
        raise ValueError(f"your passkey wallet holds {have / escrow.UNIT:g} test units; this funding needs {need / escrow.UNIT:g} "
                         "(amount and fee): get devnet test units first")
    fund = W.fund_panel_ix(plan, "stage1", me["vault"], me["token_account"], mint, m_, [bytes(Pubkey.from_string(k)) for k in keys_],
                           program=prog, unlisted_panel=True)
    order = W.panel_address(plan, "stage1", me["vault"], program=prog)
    if led.account(order) is not None:
        raise ValueError("this order is funded already")
    pre = pf.rent_ixs(relayer().pubkey(), order, pay.ov_pda(order, prog), led.rent(pf.ORDER_LEN), led.rent(165))
    if led.account(pay.ata(pay.FEE_OWNER, mint)) is None:
        pre.insert(0, pay.create_ata_ix(relayer().pubkey(), pay.FEE_OWNER, mint))
    prep = _prep(led, h, me, [fund], pre)
    meta = {"cred_id": h["cred_id"], "project": pid, "milestone": key, "units": units, "deadline_s": int(m["deadline_s"]),
            "tranches": tranches, "tranche": 1, "claim": claim,
            "plan_hash": plan["commitment_hash"], "order": str(order), "funder_vault": str(me["vault"]), "kind": kind, "grant": grant,
            "pool": pool, "referral": {"code": referral["code"], "wallet": referral["wallet"]} if referral else None,
            "panel": {"m": m_, "keys": keys_, "unlisted": True, "label": label}, "program": str(prog), "mint": str(mint),
            "warnings": plan["warnings"], "report": p.get("report"), "tables": _tables(led, mint, h), "criteria_hash": crit,
            "private": private is True}
    summary = {"what": f"fund the milestone '{m['name']}'" + (" (a grant)" if kind == "grant" else " (part of a pool)" if kind == "pool" else ""),
               "amount_units": amount / escrow.UNIT, "fee_units": pay.order_fee(amount) / escrow.UNIT, "from": str(me["vault"]),
               "order": str(order), "paid_on": "the maker's result and an independent check", "refunded_to": str(me["token_account"]),
               "criteria_hash": crit, "kill_fee_bps": p.get("kill_fee_bps", 0), "challenge_s": p.get("challenge_s"),
               "program": str(prog), "money": MONEY}
    return _intent("project_fund", h, prep, meta, summary)


def _done_project_fund(led, p: dict, sig: str, pre: list) -> dict:
    from knos.ideas import commit as C

    from . import valley
    m = p["meta"]
    order = m["order"]
    doc = {"v": 1, "kind": "knos-idea-commitment", "claim": m["claim"], "commitment_hash": m["plan_hash"],
           "plan_args": {"units": m["units"], "price": 1, "stages": [["referee_pass", 10_000]], "stage_work_s": [m["deadline_s"]],
                         "demand": m["report"], "maker_github_id": None},
           "judge": "panel", "panel": m["panel"], "payee": C.parse_payee(m["funder_vault"]), "program": m["program"], "mint": m["mint"],
           "funder": m["funder_vault"],
           "orders": {"stage1": {"order": order, "oracle": "referee_pass", "amount": m["units"] * escrow.UNIT, "work_s": m["deadline_s"],
                                 "signature": sig, "note": None}},
           "warnings": m["warnings"], "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cluster": "devnet",
           "signed_by": "the funder's passkey (LazorKit Execute, secp256r1 precompile)"}
    C.plan_of(doc)                                         # the commitment recomputes: what was signed is what is filed
    o = {"order": order, "project": m["project"], "milestone": m["milestone"], "claim_id": m["claim"]["id"], "units": m["units"], "unit_price": 1,
         "kind": m["kind"], "funder": m["funder_vault"], "grant": m["grant"] if m["kind"] == "grant" else None, "pool": m["pool"],
         "referral": m["referral"], "status": "pending", "deadline_s": m["deadline_s"], "doc": doc, "made": doc["made"],
         "signatures": {"setup": pre[0] if pre else None}, "signed_by": "passkey", "criteria_hash": m.get("criteria_hash"),
         "private": m.get("private") is True}
    valley._save("orders", order, o)
    with valley._lock:
        pr = valley.project(m["project"])
        valley._milestone(pr, m["milestone"])["fundings"].append(order)
        valley._save("projects", m["project"], pr)
    if m["pool"]:
        cur = valley._safe_load("pools", m["pool"]) or {"id": m["pool"], "funder": m["funder_vault"], "units": 0, "orders": [], "made": valley._now()}
        cur["orders"].append(order)
        cur["units"] += m["units"]
        valley._save("pools", m["pool"], cur)
    return valley.confirm(order, sig, led=led)


COMPANY_LAMPORTS = 10_000_000           # the multisig account's rent and room, sent to the company wallet's vault first


def prepare_company(led, user: dict, name: str, members: list, threshold, rp_id: str) -> dict:
    """A company's Squads v4 multisig created by a passkey: the company gets its own passkey wallet (one per company
    name), whose vault is both the multisig's create key and its creator (it signs inside LazorKit Execute, no other
    key), and is its first member. The relayer only sends the rent to that vault and pays the fee."""
    import hashlib

    from solders.system_program import TransferParams, transfer

    from . import enterprise
    name = (name or "").strip()[:80]
    if len(name) < 2:
        raise ValueError("name: the company's name")
    h = holder(user)
    me = ensure(led, h, rp_id, "company", hashlib.sha256(name.lower().encode()).digest()[:16])
    vault = me["vault"]
    others = [str(m) for m in (members or []) if str(m) and str(m) != str(vault)]
    ix, rec, fee = enterprise.multisig_ix(name, [str(vault), *others], threshold, vault, vault, led)
    if led.account(enterprise._pk(rec["multisig"])) is not None:
        raise ValueError("this company's multisig exists already")
    rec["creator_kind"] = "passkey (LazorKit Execute)"
    enterprise._save_company(rec)
    pre = [transfer(TransferParams(from_pubkey=relayer().pubkey(), to_pubkey=vault, lamports=COMPANY_LAMPORTS + fee))]
    prep = _prep(led, h, me, [ix], pre)
    meta = {"cred_id": h["cred_id"], "company": rec["id"], "tables": []}
    summary = {"what": f"create {name}'s Squads multisig ({rec['threshold']} of {len(rec['members'])})", "multisig": rec["multisig"],
               "created_by": str(vault), "program": "Squads v4", "money": "devnet SOL for rent, sent by the relayer"}
    return _intent("company", h, prep, meta, summary)


def _done_company(led, p: dict, sig: str, pre: list) -> dict:
    from . import enterprise
    return {**enterprise.company_confirm(p["meta"]["company"], sig, led=led), "signatures": {"create": sig, "rent": pre[0] if pre else None}}


def prepare_amc(led, user: dict, pid: str, key: str, units, rp_id: str) -> dict:
    """An advance-market commitment from the passkey's wallet: an allowance to the relayer (SPL Approve, signed by the
    wallet through LazorKit). Nothing moves now; when the milestone verifies, the relayer pays the maker from it."""
    from . import valley
    if isinstance(units, bool) or not isinstance(units, int) or not 1 <= units <= 1000:
        raise ValueError("units: 1 to 1,000 test units")
    p = valley.project(pid)
    m = valley._milestone(p, key)
    if m["status"] == "released":
        raise ValueError("this milestone is already released")
    preorder._need()
    h = holder(user)
    me = ensure(led, h, rp_id)
    if _units(led, me["token_account"]) < units * escrow.UNIT:
        raise ValueError(f"your passkey wallet holds less than {units} test units: get devnet test units first")
    rel = relayer().pubkey()
    prep = _prep(led, h, me, [valley._approve_ix(me["token_account"], rel, me["vault"], units * escrow.UNIT)])
    aid = valley._id("amc", str(me["vault"]), pid, key)
    meta = {"cred_id": h["cred_id"], "amc": aid, "project": pid, "milestone": key, "units": units, "buyer": str(me["vault"]),
            "token": str(me["token_account"]), "delegate": str(rel), "tables": _tables(led, me["mint"], h)}
    return _intent("amc", h, prep, meta, {"what": f"commit to buy when '{m['name']}' is proven", "allowance_units": units,
                                          "from": str(me["vault"]), "to_whom": "the maker, paid by the relayer from this allowance on proof",
                                          "money": MONEY})


def _done_amc(led, p: dict, sig: str, pre: list) -> dict:
    from . import valley
    m = p["meta"]
    valley._save("amc", m["amc"], {"id": m["amc"], "project": m["project"], "milestone": m["milestone"], "buyer": m["buyer"], "token": m["token"],
                                   "units": m["units"], "delegate": m["delegate"], "status": "pending", "made": valley._now(), "signatures": {},
                                   "signed_by": "passkey"})
    return valley.amc_confirm(m["amc"], sig, led=led)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
