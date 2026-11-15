"""Passkey wallets: a withdrawal request, and a funding carried from a comment (no token)."""
from __future__ import annotations

from solders.keypair import Keypair

from .... import fees
from .. import live, pay, passkey, passkey_fund as pkfund

from .pins import _Stop, _code, _failed, _no, transient
from .tokens import _units, _when
from .reads import _amount, _data, _read
from .plans import _decimals
from .send import _fits, _send


def withdraw(ledger, payer: Keypair, request: str | bytes) -> dict:
    """A passkey wallet's withdrawal (knos_passkey), sent and paid for by this relay, for a person who holds no SOL:
    Open when the wallet's account is not there yet, the secp256r1 check of the passkey's signature, Withdraw.
    `request` is what passkey.request wrote. {"ok": True, "kind": "withdraw", "sigs", "wallet", "mint", "to",
    "amount", "nonce"}, or {"ok": False, "kind": "withdraw", "why"}. The relay decides nothing: the passkey signed the
    mint, the destination, the amount and the nonce. Everything is asked first, by reads and then by simulating the
    very transaction, so a request the chain would refuse costs no fee; a ledger that cannot simulate sends none."""
    kind = "withdraw"
    try:
        q = passkey.read_request(request)
    except ValueError as why:
        return {"ok": False, "kind": kind, "why": str(why)}
    try:
        me, w = payer.pubkey(), q.wallet
        result = dict(kind=kind, wallet=str(w), mint=str(q.mint), to=str(q.to), amount=q.amount, nonce=q.nonce)
        got = _read(ledger, [w, q.mint, q.to, passkey.PASSKEY_ID])
        if _data(got, passkey.PASSKEY_ID) is None:     # knos_passkey never calls the escrow: what a withdrawal needs is that program, whatever the escrow's version
            raise _no(kind, f"knos_passkey ({passkey.PASSKEY_ID}) is not deployed on this cluster, so no passkey wallet can withdraw here")
        program = got[q.mint][0] if got.get(q.mint) else None  # type: ignore[index]  # got.get(q.mint) holds it
        if program not in (pay.TOKEN, pay.TOKEN_2022):
            raise _no(kind, "the mint this request names does not exist")
        source = pay.ata(w, q.mint, program)
        state = passkey.read_wallet(_data(got, w))
        if q.nonce != (state.nonce if state else 0) + 1:
            raise _no(kind, passkey.ERRORS[119])
        dest = _data(got, q.to)
        if dest is None or len(dest) < 165 or bytes(dest[:32]) != bytes(q.mint) or q.to == source:
            raise _no(kind, "the destination is not a token account of this mint; it is made first (by whoever is paid), then the request is signed for it")
        if q.amount == 0 or _amount(_data(_read(ledger, [source]), source)) < q.amount:
            raise _no(kind, "the wallet holds less of this mint than the request asks for")
        ixs = [*([passkey.open_ix(me, q.key)] if state is None else []),
               *passkey.withdraw_ixs(q.key, q.mint, q.to, q.amount, q.nonce, q.authenticator_data, q.client_data_json, q.signature, program)]
        ask = getattr(ledger, "simulate", None)
        if ask is None:
            raise _no(kind, "this relay's ledger cannot simulate, and a withdrawal is never sent unchecked")
        try:
            ask(ixs, payer)
        except Exception as why:  # noqa: BLE001 - the chain's refusal, in the passkey program's words
            if transient(why) and _code(str(why)) is None:
                raise
            code = _code(str(why))
            raise _no(kind, f"{passkey.ERRORS[code]} (error {code})" if code in passkey.ERRORS else
                      "the passkey's signature does not verify: it is another key's, or over other bytes than this request's" if code is not None and code < 8 else
                      f"the chain would refuse it: {str(why)[:200]}") from None       # (the secp256r1 check's own errors are 0 to 4)
        return {"ok": True, **result, "sigs": [ledger.send(ixs, payer)]}
    except _Stop as stop:
        return stop.result
    except Exception as why:  # noqa: BLE001 - the cluster did not answer, or dropped it: the same request may be sent again
        return _failed(kind, why)


def _rent(size: int) -> int:
    """The lamports that keep an account of `size` bytes: 3,480 a byte and year, two years, 128 bytes of overhead
    (the cluster's rent parameters, the same on every public cluster)."""
    return (128 + size) * 6960


def passkey_fund(ledger, payer: Keypair, request: str | bytes | dict, repo_id: int | None = None, issue: int | None = None) -> dict:
    """The comment `/knos passkey-fund <base64url>` (web/passkey_fund.js writes it; commands.PasskeyFund is its parse):
    a passkey wallet funds a work order, and this relay sends it, for a funder who holds no SOL and no wallet app. One
    transaction: Open when the wallet's account is not there yet, the rent of the order and of its token account (the
    wallet holds data and cannot pay rent), the secp256r1 check of the passkey's signature, Fund.
    `request`: the comment, its base64url text, or the intent's object. `repo_id`, `issue`: where the comment was
    posted; given them, an intent the passkey signed for another issue is refused (a private order names neither).
    {"ok": True, "kind": "passkey-fund", "sigs", "wallet", "order", "mint", "repo_id", "issue", "amount", "fee",
    "nonce", "deadline"}, or {"ok": False, "kind": "passkey-fund", "why"}: `passkey_fund_reply` is the comment for
    either. The relay decides nothing: the passkey signed the order's terms, amount, mint, nonce and last slot.
    Everything is asked first, by reads and then by simulating the very transaction, so a line the chain would refuse
    (an expired slot, a nonce used already, a signature over other bytes) costs no fee; a ledger that cannot simulate
    sends none. What this relay spends on a good one, besides the fee: the rent of two accounts, which knos_pay
    returns to the WALLET when the order closes, not to the relay."""
    kind = "passkey-fund"
    try:
        q = pkfund.read_intent(request.decode() if isinstance(request, bytes) else request)
    except (ValueError, UnicodeDecodeError) as why:
        return {"ok": False, "kind": kind, "why": str(why)}
    try:
        me, w, order = payer.pubkey(), q.wallet, q.order
        ov, d = pay.ov_pda(order), q.data
        n, repo, private = int.from_bytes(d[1:9], "little"), int.from_bytes(d[9:17], "little"), d[pkfund.SALTED] == 1
        result = dict(kind=kind, wallet=str(w), order=str(order), mint=str(q.mint), repo_id=repo, issue=n, amount=q.amount, nonce=q.nonce)
        if repo_id is not None and not private and (repo, n) != (int(repo_id), int(issue or 0)):
            raise _no(kind, f"the passkey signed for issue #{n} of the repository with id {repo}, and this comment is on another issue; "
                            "post the line on that issue, or sign again for this one", astray=True)
        got = _read(ledger, [w, q.mint, order, ov, passkey.PASSKEY_ID, pay.PAY_ID])
        for program, name in ((passkey.PASSKEY_ID, "knos_passkey"), (pay.PAY_ID, "knos_pay")):
            if _data(got, program) is None:
                raise _no(kind, f"{name} ({program}) is not deployed on this cluster, so no passkey wallet can fund an order here")
        if old := live.needs(ledger, payer, "knos_passkey", ledger.now() if hasattr(ledger, "now") else None):     # Fund is 1.1's
            raise _no(kind, old)
        if (got[q.mint][0] if got.get(q.mint) else None) != q.token_program:  # type: ignore[index]  # got.get(q.mint) holds it
            raise _no(kind, "the mint this line names does not exist, or is not a mint of the token program it names")
        state = passkey.read_wallet(_data(got, w))
        if q.nonce != (state.nonce if state else 0) + 1:
            raise _no(kind, "the nonce is not the wallet's nonce plus one: this funding was sent already, or the wallet signed something else "
                            "after it; sign again on the Buy page")
        if _data(got, order) is not None:
            raise _no(kind, "there is an order at that address already: this wallet funded this issue before; sign again on the Buy page, "
                            "which then signs for the next order of the issue")
        need = q.amount + fees.live(ledger, payer).order(q.amount, decimals=_decimals(_data(got, q.mint)))
        source = pay.ata(w, q.mint, q.token_program)
        if _amount(_data(_read(ledger, [source]), source)) < need:
            raise _no(kind, f"the wallet holds less of this mint than the order's amount and its fee ({need} of its smallest units); "
                            "put more in the wallet, then post the same line again while its slot lasts")
        ixs = [*([passkey.open_ix(me, q.key)] if state is None else []),
               *pkfund.rent_ixs(me, order, ov, _rent(pkfund.ORDER_LEN), _rent(165)), *q.ixs()]
        ask = getattr(ledger, "simulate", None)
        if ask is None:
            raise _no(kind, "this relay's ledger cannot simulate, and a passkey's funding is never sent unchecked")
        v1 = not _fits(me, ixs) and bool(getattr(ledger, "takes_v1", False))
        try:
            ask(ixs, payer, v1=True) if v1 else ask(ixs, payer)
        except Exception as why:  # noqa: BLE001 - the chain's refusal, in the words of the program that refused
            code = _code(str(why))
            if transient(why) and code is None:
                raise
            words = {**passkey.ERRORS, **pkfund.ERRORS, 118: "the passkey signed for another funding: the order's data, the mint, the last slot or the nonce "
                     "differs from what this line says; sign again on the Buy page"}
            raise _no(kind, f"{words[code]} (error {code})" if code in words else f"{pay.ERRORS[code]} (error {code})" if code in pay.ERRORS else
                      "the passkey's signature does not verify: it is another key's, or over other bytes than this line's" if code is not None and code < 8 else
                      f"the chain would refuse it: {str(why)[:200]}") from None       # (the secp256r1 check's own errors are 0 to 4)
        sig = _send(ledger, payer, ixs, v1)
        o = pay.read_order(_data(_read(ledger, [order]), order))
        return {"ok": True, **result, "sigs": [sig], "fee": o.fee if o else None, "deadline": o.deadline if o else None}
    except _Stop as stop:
        return stop.result
    except Exception as why:  # noqa: BLE001 - the cluster did not answer, or dropped it: the same line may be sent again
        return _failed(kind, why)


def passkey_fund_reply(r: dict) -> str:
    """The comment that answers a `/knos passkey-fund` line: what happened, and what to do next."""
    if r.get("ok"):
        test = r.get("mint") in (str(pay.USDC_DEVNET), str(pay.faucet_mint()))
        money = (lambda n: f"{_units(n)} test USDC") if test else (lambda n: f"{n} units of the test token {r.get('mint')}")
        where = f"issue #{r['issue']}" if r.get("issue") else "a private order"
        fee = f", and the wallet paid {money(r['fee'])} fee on top" if r.get("fee") is not None else ""
        return (f"Knos: funded from a passkey wallet. {money(r['amount'])} is in escrow for {where}{fee}. The order is `{r['order']}` on Solana devnet. "
                + (f"If it is not paid by {_when(r['deadline'])}, anyone can send it back to the wallet. " if r.get("deadline") else "")
                + "Nobody can change its terms now. The funder paid no SOL: the relay paid the transaction and the order's rent.")
    again = " The same line can be posted again in a few minutes." if r.get("retry") else ""
    return f"Knos: nothing was funded and nothing left the passkey wallet: {r.get('why', 'the line was refused')}.{again}"
