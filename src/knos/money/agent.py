"""The agent side of "submit work for verification and payment": three tools that quote and plan and never sign.

    knos_fees       the fee of any line of config/fees.yaml for an amount, or the whole schedule
    knos_graduate   a passing verdict -> the milestone vault and pre-order pool it opens, the contributor split, and
                    the unsigned FundOrderWallet instruction a funder's wallet signs
    knos_preorder   a buyer's pre-order in a graduated claim's pool: the unsigned instruction, the fee on top, and
                    (with a ledger) the pool as the chain has it now

`TOOLS` are MCP tool definitions in the shape knos.mcp lists (`_tool`); `call(name, args, ledger=None)` answers one
and is what an MCP server, a Hermes plugin (`ctx.register_tool(name, schema, lambda **a: call(name, a))`) or any
other host runs. No key is read, nothing is sent: the wallet that pays signs the returned instruction itself.
Devnet only; every amount is base units of a 6-decimal mint (1 USDC = 1,000,000).
"""
from __future__ import annotations

import base64
from typing import Any

from . import fees_config

_ADDR = {"type": "string", "description": "a Solana address (base58)"}
_AMOUNT = {"type": "integer", "minimum": 0, "description": "base units of a 6-decimal mint (1 USDC = 1000000)"}


def _tool(name: str, title: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "title": title, "description": description,
            "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "openWorldHint": True}}


TOOLS = [
    _tool("knos_fees", "Knos fees",
          "The fee Knos charges, from its one fee config: for `kind` (payout, bounty, funding, graduation, task_package, "
          "verification, x402_check) and an amount (or a count, for verification and x402_check), or the whole schedule "
          "with each line's status (live on devnet, proposed, or a placeholder not set yet). Test money on devnet.",
          {"kind": {"type": "string", "enum": list(fees_config.KINDS)}, "amount": _AMOUNT,
           "count": {"type": "integer", "minimum": 0}, "used": {"type": "integer", "minimum": 0}}, []),
    _tool("knos_graduate", "Graduate a verified claim",
          "Given a Knos verdict that passed (works, wanted, makeable), the milestone's held money and the pre-order pool it opens "
          "on Solana devnet (knos_pay work orders), the contributor split each payout follows, and, with `funder` and "
          "`funder_token`, the unsigned instruction that funds the milestone hold. Refused unless the verdict passed. Signs nothing.",
          {"verdict": {"type": "object", "description": "knos.referee.verdict(...) output: {passed, spec_hash, checks}"},
           "claim_id": {"type": "string"}, "repo_id": {"type": "integer", "minimum": 1, "description": "the research repository's GitHub id: its prove.yml is the judge"},
           "amount": _AMOUNT, "contributors": {"type": "array", "maxItems": 4, "items": {"type": "object"},
                                               "description": "[{role: researcher|agent|lab|referee, github_id, address?}]"},
           "milestone": {"type": "integer", "minimum": 1}, "min_buyers": {"type": "integer", "minimum": 0},
           "min_locked": _AMOUNT, "funder": _ADDR, "funder_token": _ADDR, "mint": _ADDR},
          ["verdict", "claim_id", "repo_id", "amount", "contributors"]),
    _tool("knos_preorder", "Pre-order a graduated claim",
          "A buyer locks money against a graduated claim's spec: the unsigned instruction that funds a pre-order in its pool "
          "(paid to the makers when the judge accepts delivery, refunded with its fee after the deadline otherwise), the fee "
          "on top, and the pool as the chain has it now. `plan` is what knos_graduate returned.",
          {"plan": {"type": "object"}, "buyer": _ADDR, "buyer_token": _ADDR, "mint": _ADDR, "amount": _AMOUNT,
           "seq": {"type": "integer", "minimum": 0}}, ["plan", "buyer", "buyer_token", "mint", "amount"]),
]
NAMES = tuple(t["name"] for t in TOOLS)


class Refused(ValueError):
    """A request a tool will not answer: one sentence for the agent."""


def instruction_json(ix) -> dict:
    """An instruction as JSON a wallet can rebuild and sign: program, accounts in order, data in base64."""
    return {"program_id": str(ix.program_id), "data": base64.b64encode(bytes(ix.data)).decode(),
            "accounts": [{"pubkey": str(a.pubkey), "is_signer": a.is_signer, "is_writable": a.is_writable} for a in ix.accounts]}


def _pk(v: Any, name: str):
    from solders.pubkey import Pubkey
    try:
        return Pubkey.from_string(str(v))
    except ValueError:
        raise Refused(f"{name} is not a Solana address") from None


def call(name: str, args: dict, ledger=None, cfg: fees_config.FeeConfig | None = None) -> dict:
    if name not in NAMES:
        raise Refused(f"unknown tool {name}: one of {', '.join(NAMES)}")
    cfg = cfg or fees_config.load()
    try:
        return {"knos_fees": _fees, "knos_graduate": _graduate, "knos_preorder": _preorder}[name](args or {}, ledger, cfg)
    except Refused:
        raise
    except ValueError as why:     # GraduationError, SplitError, FeeConfigError: their sentence is the answer
        raise Refused(str(why)) from None


def _fees(a: dict, _ledger, cfg: fees_config.FeeConfig) -> dict:
    kind = a.get("kind")
    if kind is None:
        return {**cfg.public(), "said": "Every Knos fee, from config/fees.yaml. On devnet all of it is test money: revenue 0."}
    if kind not in fees_config.KINDS:
        raise Refused(f"kind: one of {', '.join(fees_config.KINDS)}")
    line = cfg.doc["fees"][kind]
    if kind in fees_config.COUNT_KINDS:
        count, used = int(a.get("count", 1)), int(a.get("used", 0))
        cost = cfg.price(kind, count, used)
        return {"kind": kind, "count": count, "used": used, "price": cost, "status": line["status"], "what": line["what"],
                "said": f"{count} x {kind} after {used} this month: {cost / 1e6:.6f} USD ({line['status']})."}
    amount = a.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise Refused("amount: base units, a whole number")
    fee = cfg.fee(kind, amount)
    return {"kind": kind, "amount": amount, "fee": fee, "status": line["status"], "what": line["what"],
            "said": f"The {kind} fee on {amount / 1e6:,.2f} is {fee / 1e6:,.6f} ({line['status']})."}


def _graduate(a: dict, _ledger, cfg: fees_config.FeeConfig) -> dict:
    from .. import graduation
    p = graduation.plan(a.get("verdict"), claim_id=a.get("claim_id"), repo_id=a.get("repo_id"), amount=a.get("amount"),  # type: ignore[arg-type]  # JSON tool arguments: plan() checks each one and refuses a wrong type
                        contributors=a.get("contributors"), milestone=a.get("milestone", 1), min_buyers=a.get("min_buyers", 1),  # type: ignore[arg-type]  # as above
                        min_locked=a.get("min_locked", 0), cfg=cfg)
    out: dict = {"plan": p, "said": (f"Graduates: a milestone hold of {p['escrow']['amount'] / 1e6:,.2f} (the funder pays "
                                     f"{p['escrow']['funder_pays'] / 1e6:,.2f} with the fee) and a pre-order pool. Nothing was sent.")}
    if a.get("funder") and a.get("funder_token") and a.get("mint"):
        funder = _pk(a["funder"], "funder")
        ix = graduation.escrow_ix(p, funder, _pk(a["funder_token"], "funder_token"), _pk(a["mint"], "mint"))
        out["escrow_order"] = str(graduation.address(p, "escrow", funder))
        out["instruction"] = instruction_json(ix)
        out["sign"] = "the funder's wallet signs this one instruction (FundOrderWallet of knos_pay) and sends it to devnet"
    return out


def _preorder(a: dict, ledger, cfg: fees_config.FeeConfig) -> dict:
    from .. import graduation
    p = a.get("plan")
    if not isinstance(p, dict) or "pool" not in p:
        raise Refused("plan: the plan knos_graduate returned")
    buyer = _pk(a.get("buyer"), "buyer")
    amount: int = a.get("amount")  # type: ignore[assignment]  # a JSON tool argument: preorder_ix() refuses it unless an int in range, before any other use
    ix = graduation.preorder_ix(p, buyer, _pk(a.get("buyer_token"), "buyer_token"), _pk(a.get("mint"), "mint"), amount, seq=int(a.get("seq", 0)))
    fee = cfg.fee("payout", amount)
    out = {"order": str(graduation.address(p, "pool", buyer, int(a.get("seq", 0)))), "amount": amount, "fee": fee, "buyer_pays": amount + fee,
           "instruction": instruction_json(ix), "refund": "after the deadline anyone may send RefundOrder: the amount and the fee go back to the buyer",
           "said": f"A pre-order of {amount / 1e6:,.2f} plus a fee of {fee / 1e6:,.2f}, held by knos_pay. Nothing was sent."}
    if ledger is not None:
        out["pool"] = graduation.pool(ledger, p, str(a.get("mint")))
    return out
