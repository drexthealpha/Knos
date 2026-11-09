"""x402 v2 `exact` on Solana, settled by a public facilitator (no key): the per-check price paid in one HTTP round trip.

Knos's own "knos-order" scheme (knos.money.x402, knos.record_api) holds money in vault and is the right shape for a
pre-order or a pack of checks. One check at 0.02 test USDC is too small for an order (the smallest is 5.00), so the
`/checks` route of knos.money.x402 also offers the standard `exact` scheme: the agent signs ONE token transfer of the
check's price to the operator's address, the facilitator checks it, pays the network fee and lands it, and the agent
gets its answer. Any x402 client that speaks `exact` on Solana can pay it, with no Knos code.

    requirement(amount, asset, pay_to, fee_payer)    the PaymentRequirements entry (network solana devnet, CAIP-2)
    payment(req, payer, blockhash, ...)              a client's PaymentPayload: a partially signed v0 transaction of
                                                     SetComputeUnitLimit, SetComputeUnitPrice, TransferChecked, Memo(nonce)
    Facilitator(url).supported() / verify() / settle()   POST /verify and /settle, GET /supported
    bazaar(...)                                      the Bazaar discovery extension of a 402 (extensions.bazaar)

Specs read 14 Oct 2026: https://github.com/coinbase/x402/blob/main/specs/schemes/exact/scheme_exact_svm.md,
specs/x402-specification-v2.md, specs/extensions/bazaar.md; the testnet facilitator https://x402.org/facilitator
(`/supported` lists v2 exact on solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1 with its own fee payer). The facilitator
never holds the money: the transfer goes from the payer's token account straight to pay_to's."""
from __future__ import annotations

import json
import os
import secrets
import urllib.error
import urllib.request

X402_VERSION = 2
SCHEME = "exact"
DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
FACILITATOR = "https://x402.org/facilitator"       # Coinbase's testnet facilitator: no key
UNIT_LIMIT = 20_000                                 # TransferChecked + Memo use a few thousand; the facilitator pays for the limit
UNIT_PRICE = 1                                      # micro-lamports a unit (the reference facilitator takes at most 5 lamports)
MEMO = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"


class Refused(Exception):
    """The facilitator said no, or could not be reached: its reason, in one line."""


def facilitator_url() -> str:
    return (os.environ.get("KNOS_X402_FACILITATOR") or FACILITATOR).rstrip("/")


def requirement(amount: int, asset: str, pay_to: str, fee_payer: str, *, timeout: int = 60, memo: str | None = None,
                network: str = DEVNET) -> dict:
    extra = {"feePayer": fee_payer, **({"memo": memo} if memo else {})}
    return {"scheme": SCHEME, "network": network, "amount": str(int(amount)), "asset": asset, "payTo": pay_to,
            "maxTimeoutSeconds": int(timeout), "extra": extra}


def transfer_checked_ix(source, mint, dest, owner, amount: int, decimals: int, token_program):
    """SPL Token / Token-2022 TransferChecked (instruction 12): source, mint, destination, owner (signer)."""
    from solders.instruction import AccountMeta, Instruction
    return Instruction(token_program, bytes([12]) + int(amount).to_bytes(8, "little") + bytes([decimals]),
                       [AccountMeta(source, False, True), AccountMeta(mint, False, False), AccountMeta(dest, False, True),
                        AccountMeta(owner, True, False)])


def payment(req: dict, payer, blockhash, *, decimals: int, token_program=None, resource: dict | None = None,
            nonce: str | None = None) -> dict:
    """The PaymentPayload for `req`, signed by `payer` (a Keypair) and not by the fee payer, which the facilitator adds."""
    from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
    from solders.instruction import Instruction
    from solders.message import MessageV0, to_bytes_versioned
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    from solders.transaction import VersionedTransaction

    from ..settle.v2 import pay
    program = token_program or pay.TOKEN
    mint, to, fee_payer = Pubkey.from_string(req["asset"]), Pubkey.from_string(req["payTo"]), Pubkey.from_string(req["extra"]["feePayer"])
    me = payer.pubkey()
    memo = (req.get("extra") or {}).get("memo") or nonce or secrets.token_hex(16)
    ixs = [set_compute_unit_limit(UNIT_LIMIT), set_compute_unit_price(UNIT_PRICE),
           transfer_checked_ix(pay.ata(me, mint, program), mint, pay.ata(to, mint, program), me, int(req["amount"]), decimals, program),
           Instruction(Pubkey.from_string(MEMO), memo.encode("utf-8"), [])]
    msg = MessageV0.try_compile(fee_payer, ixs, [], blockhash)
    keys = list(msg.account_keys[:msg.header.num_required_signatures])
    sigs = [payer.sign_message(to_bytes_versioned(msg)) if k == me else Signature.default() for k in keys]
    tx = VersionedTransaction.populate(msg, sigs)
    import base64
    return {"x402Version": X402_VERSION, **({"resource": resource} if resource else {}), "accepted": req,
            "payload": {"transaction": base64.b64encode(bytes(tx)).decode()}}


class Facilitator:
    def __init__(self, url: str | None = None, post=None, get=None, timeout: float = 30.0):
        self.url = (url or facilitator_url()).rstrip("/")
        self._post, self._get, self.timeout = post, get, timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        if method == "POST" and self._post is not None:
            return self._post(path, body)
        if method == "GET" and self._get is not None:
            return self._get(path)
        req = urllib.request.Request(f"{self.url}{path}", method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "knos-x402"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - the facilitator's https URL
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read() or b"{}") | {"httpStatus": e.code}
            except ValueError:
                raise Refused(f"the facilitator answered {e.code} to {path}") from None
        except (OSError, ValueError) as why:
            raise Refused(f"the facilitator at {self.url} did not answer ({type(why).__name__})") from None

    def supported(self) -> dict:
        return self._call("GET", "/supported")

    def fee_payer(self, network: str = DEVNET) -> str | None:
        """The fee payer the facilitator names for `exact` on this network (its `/supported`), or None."""
        for k in self.supported().get("kinds") or []:
            if k.get("x402Version") == X402_VERSION and k.get("scheme") == SCHEME and k.get("network") == network:
                return (k.get("extra") or {}).get("feePayer")
        return None

    def verify(self, payload: dict, req: dict) -> dict:
        return self._call("POST", "/verify", {"x402Version": X402_VERSION, "paymentPayload": payload, "paymentRequirements": req})

    def settle(self, payload: dict, req: dict) -> dict:
        return self._call("POST", "/settle", {"x402Version": X402_VERSION, "paymentPayload": payload, "paymentRequirements": req})

    def verify_and_settle(self, payload: dict, req: dict, confirm=None) -> dict:
        """verify, then settle: the settlement response ({success, transaction, network, payer}); Refused otherwise.
        The testnet facilitator may answer `settlement_pending` with the transaction's signature when its own RPC is
        slow (devnet, 14 Oct 2026: it answered so for a transfer that was finalized seconds later): `confirm(sig)`
        then decides, by the chain (knos.chain.wait), and the answer is the settlement it confirmed."""
        v = self.verify(payload, req)
        if not v.get("isValid"):
            raise Refused(f"the facilitator refused the payment: {v.get('invalidReason') or v.get('error') or v}")
        s = self.settle(payload, req)
        if s.get("success"):
            return s
        if s.get("errorReason") == "settlement_pending" and s.get("transaction") and confirm is not None:
            try:
                seen = confirm(s["transaction"])
            except Exception as why:  # noqa: BLE001 - not landed, or failed on chain
                raise Refused(f"the settlement {s['transaction']} did not land: {str(why)[:160]}") from None
            return {**s, "success": True, "errorReason": None, "errorMessage": None, "confirmedBy": "chain",
                    **({"commitment": seen["confirmationStatus"]} if isinstance(seen, dict) and seen.get("confirmationStatus") else {})}
        raise Refused(f"the facilitator did not settle: {s.get('errorReason') or s.get('error') or s}")


def confirm_on(url: str | None = None, within: float = 60.0):
    """`confirm` for verify_and_settle: wait for the signature on the cluster (KNOS_RPC or devnet)."""
    def confirm(sig: str) -> dict:
        from .. import chain
        return chain.wait(url or os.environ.get("KNOS_RPC") or chain.CLUSTERS["devnet"], sig, within)     # finalized on Alpenglow
    return confirm


def bazaar(method: str, *, output_example: dict | None = None, query: dict | None = None, description: str = "",
           output_schema: dict | None = None) -> dict:
    """extensions.bazaar of a 402: how the resource is called and what it returns, so a discovery service (Bazaar) and
    any agent reading the 402 can list and call it. Listing in the CDP catalog happens after a settlement through the
    CDP facilitator, which needs a CDP key: with the testnet facilitator the extension is declared, not listed."""
    info = {"input": {"type": "http", "method": method, **({"queryParams": query} if query else {})},
            "output": {"type": "json", **({"example": output_example} if output_example is not None else {})}}
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
              "properties": {"input": {"type": "object"}, "output": output_schema or {"type": "object"}}}
    return {"info": info, "schema": schema, **({"description": description} if description else {})}
