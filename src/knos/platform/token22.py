"""Token-2022 extensions, read from a mint's or a token account's bytes: whether money held in vault in that mint can
be paid out as its terms say (https://solana.com/docs/tokens/extensions, read 14 Oct 2026).

knos_pay holds a bounty in the job's own token account and pays it with one TransferChecked (a CPI). Some extensions of
a Token-2022 mint let someone other than the funder and the judge decide what happens to that money, or make the
payment fail, so a bounty funded in such a mint would not be the promise its terms make:

    extension            on        what it does to a vault                                              Knos
    PermanentDelegate    mint      the delegate can move or burn ANY account's tokens, the vault's too    refuse
    Pausable             mint      the pause authority can stop every transfer, the payout's too           refuse
    TransferHook         mint      every transfer runs another program, with accounts knos_pay never passes refuse
    NonTransferable      mint      the tokens cannot move at all                                           refuse
    TransferFeeConfig    mint      a fee is withheld from every transfer: the payee gets less than the terms refuse
    DefaultAccountState  mint      new accounts start frozen (state 2): a payee's new account cannot receive refuse when frozen
    ConfidentialTransferMint mint  balances may move encrypted, out of what the vault's terms can read     warn
    MintCloseAuthority   mint      the mint can be closed once its supply is zero                          warn
    InterestBearingConfig / ScaledUiAmount  mint  the amount shown differs from the raw amount paid        warn
    MemoTransfer         account   an incoming transfer needs a Memo instruction right before it; knos_pay's
                                   payout CPI carries none, so a payout to this account fails              refuse (payee)
    frozen account       account   a frozen account receives nothing                                       refuse (payee)

`mint_risks(data)` and `account_risks(data)` return [{extension, severity, why}]; `refused(risks)` is true when one
says "refuse". Classic SPL Token mints and accounts have no extensions: [] for them."""
from __future__ import annotations

MINT_SIZE, ACCOUNT_SIZE = 82, 165
ACCOUNT_TYPE_AT = 165                  # the byte after the base account (a mint is padded to 165 first): 1 mint, 2 account
NAMES = {1: "TransferFeeConfig", 2: "TransferFeeAmount", 3: "MintCloseAuthority", 4: "ConfidentialTransferMint",
         5: "ConfidentialTransferAccount", 6: "DefaultAccountState", 7: "ImmutableOwner", 8: "MemoTransfer",
         9: "NonTransferable", 10: "InterestBearingConfig", 11: "CpiGuard", 12: "PermanentDelegate",
         13: "NonTransferableAccount", 14: "TransferHook", 15: "TransferHookAccount", 16: "ConfidentialTransferFeeConfig",
         17: "ConfidentialTransferFeeAmount", 18: "MetadataPointer", 19: "TokenMetadata", 20: "GroupPointer",
         21: "TokenGroup", 22: "GroupMemberPointer", 23: "TokenGroupMember", 24: "ConfidentialMintBurn",
         25: "ScaledUiAmount", 26: "Pausable", 27: "PausableAccount"}
ZERO = bytes(32)


def extensions(data: bytes) -> dict[str, bytes]:
    """{extension name: its bytes} of a Token-2022 mint or account (TLV after byte 165: u16 type, u16 length)."""
    data = bytes(data)
    if len(data) <= ACCOUNT_TYPE_AT:
        return {}
    out, i = {}, ACCOUNT_TYPE_AT + 1
    while i + 4 <= len(data):
        kind, size = int.from_bytes(data[i:i + 2], "little"), int.from_bytes(data[i + 2:i + 4], "little")
        if kind == 0:
            break
        out[NAMES.get(kind, f"Unknown{kind}")] = data[i + 4:i + 4 + size]
        i += 4 + size
    return out


def _risk(ext: str, severity: str, why: str) -> dict:
    return {"extension": ext, "severity": severity, "why": why}


def mint_risks(data: bytes) -> list[dict]:
    """What a mint's extensions mean for money held in it until the proof passes."""
    ext, out = extensions(data), []
    pd = ext.get("PermanentDelegate")
    if pd is not None and bytes(pd[:32]) != ZERO:
        out.append(_risk("PermanentDelegate", "refuse", "its permanent delegate can move or burn the tokens in any account, the held money's included"))
    if "Pausable" in ext:
        out.append(_risk("Pausable", "refuse", "its pause authority can stop every transfer, the payout included" +
                         (" (it is paused now)" if len(ext["Pausable"]) >= 33 and ext["Pausable"][32] else "")))
    th = ext.get("TransferHook")
    if th is not None and bytes(th[32:64]) != ZERO:
        out.append(_risk("TransferHook", "refuse", "every transfer runs another program with accounts the payment program's payout does not pass, so the payout would fail"))
    if "NonTransferable" in ext:
        out.append(_risk("NonTransferable", "refuse", "its tokens cannot be transferred, so the held money could never be paid"))
    tf = ext.get("TransferFeeConfig")
    # authorities 0..64, withheld 64..72, older {epoch, maximum_fee, bps} 72..90, newer 90..108: either fee's bps
    if tf is not None and len(tf) >= 108 and (int.from_bytes(tf[88:90], "little") or int.from_bytes(tf[106:108], "little")):
        out.append(_risk("TransferFeeConfig", "refuse", "a fee is withheld from every transfer, so the payee would get less than the terms say"))
    das = ext.get("DefaultAccountState")
    if das is not None and das[:1] == b"\x02":
        out.append(_risk("DefaultAccountState", "refuse", "new token accounts start frozen, so a payee's new account could not receive"))
    if "ConfidentialTransferMint" in ext:
        out.append(_risk("ConfidentialTransferMint", "warn", "balances can move encrypted; the payment program pays in the clear, but what a payee does next is not visible"))
    if "MintCloseAuthority" in ext:
        out.append(_risk("MintCloseAuthority", "warn", "the mint can be closed once its supply is zero"))
    for name in ("InterestBearingConfig", "ScaledUiAmount"):
        if name in ext:
            out.append(_risk(name, "warn", "wallets show an amount that differs from the raw amount the terms pay"))
    return out


def account_risks(data: bytes) -> list[dict]:
    """What a payee's token account's state and extensions mean for a payout into it."""
    data, out = bytes(data), []
    if len(data) >= ACCOUNT_SIZE and data[108] == 2:
        out.append(_risk("frozen", "refuse", "the account is frozen and receives nothing"))
    mt = extensions(data).get("MemoTransfer")
    if mt is not None and mt[:1] == b"\x01":
        out.append(_risk("MemoTransfer", "refuse", "the account requires a memo on every incoming transfer; the payment program's payout carries none, so it would fail. "
                         "Turn it off (spl-token disable-required-transfer-memos) or name another account"))
    return out


def refused(risks: list[dict]) -> bool:
    return any(r["severity"] == "refuse" for r in risks)


def words(risks: list[dict]) -> str:
    return "; ".join(f"{r['extension']}: {r['why']}" for r in risks)


def check(owner: str, data: bytes) -> dict:
    """One address as the chain has it ({owner program, data}): {kind: mint|account|other, token_2022, risks, ok}."""
    from ..settle.v2 import pay
    t22 = owner == str(pay.TOKEN_2022)
    if owner not in (str(pay.TOKEN), str(pay.TOKEN_2022)):
        return {"kind": "other", "token_2022": False, "risks": [], "ok": False, "said": "not a token mint or token account"}
    data = bytes(data)
    kind = "mint" if len(data) == MINT_SIZE or (t22 and len(data) > ACCOUNT_TYPE_AT and data[ACCOUNT_TYPE_AT] == 1) else "account"
    risks = (mint_risks(data) if kind == "mint" else account_risks(data)) if t22 or kind == "account" else []
    return {"kind": kind, "token_2022": t22, "risks": risks, "ok": not refused(risks),
            "said": words(risks) or ("no extension that changes what money held in it pays" if kind == "mint" else "it can receive a payout")}


def main(argv: list[str] | None = None) -> int:
    """python -m knos.platform.token22 ADDRESS [...]: whether a mint can hold money until the proof passes, or an account receive a payout."""
    import json
    import sys
    from solders.pubkey import Pubkey
    from .. import chain
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m knos.platform.token22 MINT_OR_TOKEN_ACCOUNT [...]", file=sys.stderr)
        return 2
    ledger, bad = chain.ledger(), 0
    for a in args:
        got = ledger.infos([Pubkey.from_string(a)])[0]
        row = {"address": a, **(check(str(got[0]), bytes(got[1])) if got else {"kind": "missing", "ok": False, "risks": [], "said": "no such account"})}
        bad += not row["ok"]
        print(json.dumps(row))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
