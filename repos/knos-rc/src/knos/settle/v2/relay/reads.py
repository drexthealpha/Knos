"""Reads of the chain, no transaction: jobs, Balances, held payments, keys, credits, orders, and what an account's logs
said."""
from __future__ import annotations

import re

from solders.pubkey import Pubkey

from .... import chain
from .. import meter, oidc, pay



# -- reading the chain --------------------------------------------------------------------------------------------------
def _read(ledger, addresses) -> dict[Pubkey, tuple[Pubkey | None, bytes] | None]:
    """{address: (owner, data)} for each account, None for one that does not exist: in one request when the ledger
    can do that (the owner is None when it cannot say)."""
    addresses = list(dict.fromkeys(addresses))
    many, owner = getattr(ledger, "infos", None), getattr(ledger, "owner", None)
    if many is not None:
        return dict(zip(addresses, many(addresses)))
    out = {}
    for a in addresses:
        data = ledger.account(a)
        out[a] = None if data is None else (owner(a) if owner else None, data)
    return out


def _data(got: dict, address: Pubkey) -> bytes | None:
    return got[address][1] if got.get(address) else None


def _amount(data: bytes | None) -> int:
    """What a token account holds (either token program)."""
    return int.from_bytes(data[64:72], "little") if data and len(data) >= 165 else 0


def jobs_for(ledger, repo_id: int, issue: int) -> list[tuple[Pubkey, pay.Job]]:
    """Every job on this issue that holds money: open, or held for its payee. An issue can have several: each Balance
    and each wallet funds its own."""
    found = ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {8: repo_id.to_bytes(8, "little") + issue.to_bytes(8, "little")})
    jobs = [(addr, pay.read_job(data)) for addr, data in found]
    return sorted(((a, j) for a, j in jobs if j is not None and j.state in ("open", "held")), key=lambda x: str(x[0]))


def balances_for(ledger, owner_id: int) -> list[tuple[Pubkey, pay.Balance, int]]:
    """(address, Balance, what its token account holds now) for every Balance set aside for one GitHub owner's
    repositories: each wallet's, and on devnet the faucet's."""
    found = ledger.program_accounts(pay.PAY_ID, pay.BALANCE_LEN, {8: owner_id.to_bytes(8, "little")})
    bals = sorted(((a, b) for a, b in ((a, pay.read_balance(d)) for a, d in found) if b is not None), key=lambda x: str(x[0]))
    held = _read(ledger, [pay.baltok_pda(a) for a, _b in bals])
    return [(a, b, _amount(_data(held, pay.baltok_pda(a)))) for a, b in bals]


def held_for(ledger, user_id: int) -> list[tuple[Pubkey, pay.Job]]:
    """Every job that is held and waits for this GitHub user to bind a wallet."""
    found = ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {0: bytes([3]), 56: user_id.to_bytes(8, "little")})
    jobs = [(addr, pay.read_job(data)) for addr, data in found]
    return sorted(((a, j) for a, j in jobs if j is not None and j.state == "held" and j.payee_id == user_id), key=lambda x: str(x[0]))


def keys(ledger) -> list[tuple[Pubkey, oidc.Key, int]]:
    """(address, Key, modulus) of every signing key the second verifier has: GitHub's first, each issuer's oldest first."""
    out = []
    for limbs in (64, 128):     # a token account can be as long as a key account, and its third byte is never a limb count
        for addr, data in ledger.program_accounts(oidc.OIDC_ID, oidc.K_HDR + 8 * limbs, {2: bytes([limbs])}):
            k = oidc.read_key(data)
            if k is not None:
                out.append((addr, k, int.from_bytes(data[oidc.K_HDR:oidc.K_HDR + 4 * limbs], "little")))
    return sorted(out, key=lambda x: (x[1].issuer, x[1].active_at, str(x[0])))


def _last(ledger, address: Pubkey) -> list[str]:
    """The transaction that last touched an account, for a result that sends none of its own. Best effort."""
    find = getattr(ledger, "last_signature", None)
    try:
        sig = find(address) if find else None
    except Exception:  # noqa: BLE001 - the verdict does not depend on finding the transaction
        sig = None
    return [sig] if sig else []


def _funded_by(ledger, order: Pubkey, used: Pubkey, most: int = 20) -> tuple[bool, list[str]]:
    """Whether the order now at `order` was funded by the fund token whose marker is `used`, and the transaction that
    funded it: the newest of the order's last few transactions in which knos-pay logged its funding, and whether that
    transaction also wrote the marker. An address is funded again once its order is paid or refunded, by another token
    of the same funder for the same issue and terms, so the order's own fields cannot tell the two tokens apart. When
    the cluster does not say: (True, the last transaction to touch the order), the answer before this was read."""
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    if not (recent and logs):
        return True, _last(ledger, order)
    try:
        for sig, _when in recent(order, most):
            if any(line.startswith(f"knos3:funded order={order} ") for line in chain.said(logs(sig), pay.PAY_ID)):  # type: ignore[misc]  # the loop runs only when `logs` is there
                return sig in {s for s, _w in recent(used, most)}, [sig]
    except Exception:  # noqa: BLE001 - not known: as before
        pass
    return True, _last(ledger, order)


def _said_in(ledger, address: Pubkey, line: str, most: int = 10) -> list[str]:
    """The newest of the last few transactions that named `address` in which knos-pay itself logged exactly `line`.
    The last transaction to name an account is not the one that wrote it: a wallet's Bind is named, read-only, by
    every payment to its owner afterwards. When none is found the result names no transaction, never another one."""
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    try:
        for sig, _when in (recent(address, most) if recent and logs else []):
            if line in chain.said(logs(sig), pay.PAY_ID):  # type: ignore[misc]  # the loop runs only when `logs` is there
                return [sig]
    except Exception:  # noqa: BLE001, S110 - the verdict does not depend on finding the transaction
        pass
    return []


def _batch_taken(ledger, where: Pubkey, kind: str, b, most: int = 20) -> dict | None:
    """Where knos_meter took exactly this batch (RecordBatch or ClaimBatch logs every number of the audience and its
    root), among the last few transactions that named its Ledger account `where`: {"sigs", "fee", "chain"} as that
    line says them, or None when none is found or the cluster does not say. A seq is taken once, so a line with this
    seq and this root is this audience's own batch: any token for it asks for what the chain already shows. One with
    another root is another batch, and is refused."""
    head = (f"knosm:{kind} buyer={b.buyer} seller={b.seller} month={b.month} seq={b.seq} count={b.count} accepted={b.accepted} "
            f"value={b.value} root={b.root.hex()} ")
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    try:
        for sig, _when in (recent(where, most) if recent and logs else []):
            for line in chain.said(logs(sig), meter.METER_ID):  # type: ignore[misc]  # the loop runs only when `logs` is there
                if line.startswith(head):
                    fee, made = re.search(r" fee=(\d+)", line), re.search(r" chain=([0-9a-f]{64})", line)
                    return {"sigs": [sig], "fee": int(fee.group(1)) if fee else 0, **({"chain": made.group(1)} if made else {})}
    except Exception:  # noqa: BLE001, S110 - not known: the seq rule answers, as before
        pass
    return None


def _said_since(ledger, address: Pubkey, pattern: str, since: int) -> tuple[re.Match, str] | None:
    """The newest line knos-pay itself logged, no earlier than `since`, in a transaction that named `address`, which
    matches `pattern` whole: (the match, the transaction). None when there is none, or the ledger cannot say."""
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    try:
        for sig, when in (recent(address, 5) if recent and logs else []):
            if when is not None and when < since:
                continue
            for line in chain.said(logs(sig), pay.PAY_ID):  # type: ignore[misc]  # the loop runs only when `logs` is there
                if m := re.fullmatch(pattern, line):
                    return m, sig
    except Exception:  # noqa: BLE001, S110 - not finding it only means the plain refusal is given
        pass
    return None


# -- knos_meter: an evaluation counted, with no escrow --------------------------------------------------------------------
def credits_for(ledger, buyer_id: int) -> list[tuple[Pubkey, meter.Credits, int]]:
    """(address, Credits, what its token account holds) for every credits account prepaid for one buyer's evaluations."""
    found = ledger.program_accounts(meter.METER_ID, meter.CREDITS_LEN, {8: buyer_id.to_bytes(8, "little")})
    got = sorted(((a, c) for a, c in ((a, meter.read_credits(d)) for a, d in found) if c is not None), key=lambda x: str(x[0]))
    held = _read(ledger, [meter.crtok_pda(a) for a, _c in got])
    return [(a, c, _amount(_data(held, meter.crtok_pda(a)))) for a, c in got]


def orders(ledger, state: int) -> list[tuple[Pubkey, pay.Order]]:
    """Every work order in one state (1 open, 3 held, 4 warranty). Needs ledger.program_accounts."""
    found = ((a, pay.read_order(d)) for a, d in ledger.program_accounts(pay.PAY_ID, pay.ORDER_LEN, {0: bytes([2, state])}))
    return sorted(((a, o) for a, o in found if o is not None), key=lambda x: str(x[0]))


def open_repositories(ledger) -> set[int]:
    """The GitHub id of every repository with money waiting on a proof: an open job, or an open work order (a private
    order names no repository, so the one whose runs judge it stands in). A worker that reads those repositories'
    comments finds a pay token with no search at all. Reads only; needs ledger.program_accounts."""
    jobs = (pay.read_job(d) for _a, d in ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {0: bytes([1])}))
    ids = {j.repo_id for j in jobs if j is not None} | {o.repo_id or o.judge_repo_id for _a, o in orders(ledger, 1)}
    return ids - {0}
