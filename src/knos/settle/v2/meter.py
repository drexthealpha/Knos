"""Client for knos-meter (programs-v2/knos_meter): acceptance without escrow. A neutral on-chain count of evaluations
that GitHub signed, for a buyer who pays a vendor by invoice and for a vendor who bills per accepted outcome. It moves
no customer money: each billable evaluation costs a fee from credits somebody prepaid. Pure instruction builders, the
audience, account readers and the statement; no network. The program is upgradeable only through a multisig with a
public 48-hour delay, until an outside review.

    open_credits_ix(authority, owner_id, mint, wf_repo, wf_sha)   # a wallet prepays for one GitHub owner, and pins the workflows
    deposit_ix(source, owner, credits, mint, amount, decimals)    # a plain token transfer into the credits (anyone)
    withdraw_credits_ix(authority, credits, mint, amount)         # unspent credits back to the wallet that opened them
    set_plan_ix(fee_owner, payer, owner_id, tier, rate, expiry)   # FEE_OWNER lowers one owner's rate until an expiry
    record_ix(relayer, token, key, credits, c, audience, now)     # one verified token = one evaluation; anyone relays
    close_mark_ix(payer, mark)                                    # the relayer takes back the rent of a mark it paid for

An evaluation is a run of attest.yml or prove.yml at the commit the Credits account pins, in a repository of the
buyer, on a GitHub-hosted runner, first attempt, whose token's audience is `eval_audience(...)`. It is billed and
counted once per (buyer, work order, artifact, policy, milestone), whatever the verdict; a later token for the same
is free and changes nothing while its mark stands (the first verdict stands). The first FREE_PER_MONTH evaluations of an owner in a UTC
calendar month cost nothing; after that FEE per evaluation, or the owner's Plan rate. Credits that cannot pay are
refused (error 118): nothing is recorded, and the same token can be relayed again once money is added.

What makes a retry free is the mark account, and the relayer puts up its rent. The mark names that relayer and the
time from which it can be closed: the first second of the next UTC month plus MARK_GRACE, when no token GitHub issued
in the month of the count is accepted any more. From then `close_mark_ix` returns all of the rent to that relayer
(`marks_of` finds its marks, `closable` says which are due). So a retry is free for the whole calendar month. After a
mark is closed, a token issued in a later month for the same evaluation is billed and counted again, in that month;
a relayer that wants an evaluation billed once for longer leaves its mark open.

Tokens are verified with `knos.settle.v2.oidc` (write_ixs, step_ix). `key` is the verifier's account of the key that
verified the token: `oidc.read_token(token account data).key`. A token is refused once that key is revoked (78) or
has expired (77), and always when the key is a private one (122).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from . import load_ids
from .pay import ATA_PROGRAM, SYSTEM, TOKEN, TOKEN_2022, ata, create_ata_ix, wf_repo_hash  # noqa: F401

IDS = load_ids()            # the pinned ids, or a staging deployment named by KNOS_PROGRAM_IDS
METER_ID = Pubkey.from_string(IDS["knos_meter"])
OIDC_ID = Pubkey.from_string(IDS["knos_oidc"])          # the verifier whose token accounts the meter accepts
FEE_OWNER = Pubkey.from_string(IDS["fee_owner"])        # Knos's Squads vault: receives the fees and sets Plans, nothing else

MICRO = 1_000_000                       # rates are in millionths of a whole unit of the mint
FEE, PLAN_MIN, FREE_PER_MONTH = 50_000, 20_000, 10_000  # 0.05 per billable evaluation; 0.02 the lowest Plan rate; free per owner per month
MIN_DECIMALS, MAX_DECIMALS = 2, 18
EXTENSIONS = (3, 4, 10, 18, 19, 20, 21, 22, 23, 25)     # the only Token-2022 mint extensions a mint of credits may carry
TOKEN_AHEAD, TOKEN_LIFE = 300, 3600
MARK_GRACE = 7200                       # TOKEN_LIFE + the hour the verifier allows past a token's expiry
CREDITS_LEN, PLAN_LEN, MARK_LEN, MONTH_LEN = 168, 40, 88, 64
MARK_LEN_1 = 48                         # a mark written before CloseMark existed: no payer, it stays
MARK_PAYER = 48                         # where a mark keeps the relayer that paid its rent (`marks_of` filters on it)
CLOSED = "knosm:closed "                # a mark was closed and its rent returned
WORKFLOWS = ("attest.yml", "prove.yml")
EVAL = "knosm:eval "                    # the log line a statement is recomputed from
ERRORS = {61: "the token's claims are not a JSON object", 62: "a claim the meter reads appears twice in the token", 63: "a claim the meter reads is missing from the token",
          76: "the key that signed this token is not active on chain yet: it waits for its delay and the guardian's approval; try again after that",
          77: "the key that signed this token has expired on chain; run the rotate workflow and send Refresh for the key, then relay the token again while it is fresh",
          78: "the key that signed this token was revoked on chain, so the token counts nothing; run the workflow again for a token signed by another key",
          110: "a wrong account, or a missing signature",
          111: "the owner id, the workflow commit, the rate or the tier is outside what is allowed",
          112: "this is not a credits account, or the signer is not the wallet that opened it",
          113: "the token is not verified, not GitHub's, expired, or its times are not GitHub's; a new run gives a new one",
          114: "the token's claims do not allow this: the runner is not GitHub's, or this is a re-run; start a new run",
          115: "the token is not from attest.yml or prove.yml at the commit these credits pin; send OpenCredits again to pin another commit",
          116: "the token's audience is not a knosm:eval audience",
          117: "the run was not in a repository of the buyer its audience names, or these credits were prepaid for another owner",
          118: "the credits do not hold that much; add money with a transfer to the credits' token account and send this again",
          119: "this mint cannot be used: it is not Circle's USDC, not a mint of the token program passed, has fewer than 2 or more than 18 decimals, or carries an extension that is not on the list",
          120: "the fee account is not a token account of the credits' mint owned by the fee owner, or the destination is not the withdrawing wallet's",
          121: "only the fee owner sets a plan",
          122: "the key that signed this token is a private key, or of a kind the meter does not know: it counts nothing here",
          123: "this is not a mark that can be closed, or the signer is not the relayer that paid its rent; sign with the wallet the mark names",
          124: "this mark cannot be closed yet; send this again after the time the mark names (two hours into the month after the one it was counted in)"}


def _u64(v: int) -> bytes:
    return v.to_bytes(8, "little")


def _pda(seeds: list[bytes], program: Pubkey) -> Pubkey:
    return Pubkey.find_program_address(seeds, program)[0]


def _n(data: bytes, o: int, size: int = 8) -> int:
    return int.from_bytes(data[o:o + size], "little")


def _i64(data: bytes, o: int) -> int:
    return int.from_bytes(data[o:o + 8], "little", signed=True)


def fee_units(rate: int, decimals: int) -> int:
    """A rate (millionths of a whole unit) in the smallest units of a mint with these decimals, rounded down."""
    return rate * 10 ** decimals // MICRO


def yyyymm(t: int) -> int:
    """The UTC calendar month of a unix time, as the program computes it from the chain's clock."""
    d = datetime.fromtimestamp(max(t, 0), timezone.utc)
    return d.year * 100 + d.month


def next_month(t: int) -> int:
    """The first second of the UTC calendar month after the one `t` is in."""
    d = datetime.fromtimestamp(max(t, 0), timezone.utc)
    return int(datetime(d.year + d.month // 12, d.month % 12 + 1, 1, tzinfo=timezone.utc).timestamp())


def close_after(t: int) -> int:
    """From when a mark recorded at `t` can be closed: its month has closed and no token issued in it is accepted."""
    return next_month(t) + MARK_GRACE


# -- the audience: what attest.yml or prove.yml asks GitHub to sign -----------------------------------------------------
def eval_audience(buyer_id: int, seller_id: int, order: bytes, artifact: str, policy: bytes, milestone: int, verdict: int | bool, rate: int) -> str:
    """`order` and `policy` are 32 bytes (the work order and the policy it was judged under); `artifact` is a commit
    (40 hex characters); `verdict` 1 accepted, 0 rejected; `rate` is what the seller bills for this outcome when it is
    accepted, in the smallest units of whatever the two settle in."""
    if len(order) != 32 or len(policy) != 32 or len(artifact) != 40 or not 0 <= milestone < 2 ** 32:
        raise ValueError("an evaluation names a 32-byte work order, a 40-character commit, a 32-byte policy and a milestone below 2^32")
    return f"knosm:eval:{buyer_id}:{seller_id}:{order.hex()}:{artifact}:{policy.hex()}:{milestone}:{int(bool(verdict))}:{rate}"


@dataclass
class Eval:
    buyer_id: int
    seller_id: int
    order: bytes
    artifact: str
    policy: bytes
    milestone: int
    accepted: bool
    rate: int

    @property
    def key(self) -> bytes:
        """What makes it billable once (with the buyer): sha256(work order || artifact || policy || milestone u32)."""
        return eval_key(self.order, self.artifact, self.policy, self.milestone)


def parse_audience(audience: str) -> Eval:
    p = audience.split(":")
    if len(p) != 10 or p[:2] != ["knosm", "eval"] or p[8] not in ("0", "1"):
        raise ValueError("this is not a knosm:eval audience")
    return Eval(buyer_id=int(p[2]), seller_id=int(p[3]), order=bytes.fromhex(p[4]), artifact=p[5], policy=bytes.fromhex(p[6]), milestone=int(p[7]),
                accepted=p[8] == "1", rate=int(p[9]))


def eval_key(order: bytes, artifact: str, policy: bytes, milestone: int) -> bytes:
    return hashlib.sha256(order + artifact.encode() + policy + milestone.to_bytes(4, "little")).digest()


# -- addresses --------------------------------------------------------------------------------------------------------
def auth_pda(program: Pubkey = METER_ID) -> Pubkey:
    """The owner of every credits token account. Only the program signs for it."""
    return _pda([b"auth"], program)


def credits_pda(owner_id: int, authority: Pubkey, mint: Pubkey, program: Pubkey = METER_ID) -> Pubkey:
    """The credits a wallet (`authority`) prepaid for the evaluations of the GitHub owner `owner_id`, in one mint."""
    return _pda([b"cr", _u64(owner_id), bytes(authority), bytes(mint)], program)


def crtok_pda(credits: Pubkey, program: Pubkey = METER_ID) -> Pubkey:
    """A credits account's token account. Add money with a plain token transfer to this address (`deposit_ix`)."""
    return _pda([b"crtok", bytes(credits)], program)


def plan_pda(owner_id: int, program: Pubkey = METER_ID) -> Pubkey:
    """An owner's rate under a contract and its count of billable evaluations this month."""
    return _pda([b"plan", _u64(owner_id)], program)


def mark_pda(buyer_id: int, key: bytes, program: Pubkey = METER_ID) -> Pubkey:
    """Exists once this evaluation of this buyer was billed. `key` is eval_key(...) or Eval.key."""
    return _pda([b"k", _u64(buyer_id), key], program)


def month_pda(buyer_id: int, seller_id: int, month: int, program: Pubkey = METER_ID) -> Pubkey:
    """The count of one buyer and one seller in one month (`month` is yyyymm, as `yyyymm(unix time)` gives it)."""
    return _pda([b"m", _u64(buyer_id), _u64(seller_id), month.to_bytes(4, "little")], program)


# -- accounts ---------------------------------------------------------------------------------------------------------
@dataclass
class Credits:
    token_program: Pubkey
    decimals: int
    owner_id: int           # the GitHub owner (the buyer) whose evaluations it pays for
    authority: Pubkey       # the wallet that opened it
    mint: Pubkey
    spent: int              # every fee it ever paid
    evaluations: int        # the billable evaluations recorded against it, the free ones included
    wf_repo_hash: bytes     # sha256 of "owner/name": the repository whose attest.yml and prove.yml may spend it
    wf_sha: str             # at this commit


def read_credits(data: bytes | None) -> Credits | None:
    if not data or len(data) != CREDITS_LEN or data[0] != 1:
        return None
    return Credits(token_program=TOKEN_2022 if data[2] == 1 else TOKEN, decimals=data[3], owner_id=_n(data, 8), authority=Pubkey.from_bytes(data[16:48]),
                   mint=Pubkey.from_bytes(data[48:80]), spent=_n(data, 80), evaluations=_n(data, 88), wf_repo_hash=bytes(data[96:128]),
                   wf_sha=bytes(data[128:168]).decode("ascii", "replace"))


@dataclass
class Plan:
    tier: int               # a label for the contract (0: none)
    month: int              # yyyymm that `used` counts
    owner_id: int
    rate: int               # millionths of a whole unit per evaluation (0: no plan)
    expiry: int
    used: int               # billable evaluations of the owner in `month`

    def rate_at(self, now: int) -> int:
        """What a billable evaluation past the free ones costs at `now`, in millionths of a whole unit."""
        return self.rate if self.rate and now < self.expiry else FEE

    def used_in(self, month: int) -> int:
        return self.used if self.month == month else 0


def read_plan(data: bytes | None) -> Plan:
    """The account at plan_pda(owner id); an owner with no account has no plan and has used nothing."""
    if not data or len(data) != PLAN_LEN or data[0] != 1:
        return Plan(0, 0, 0, 0, 0, 0)
    return Plan(tier=data[2], month=_n(data, 4, 4), owner_id=_n(data, 8), rate=_n(data, 16), expiry=_i64(data, 24), used=_n(data, 32))


@dataclass
class Mark:
    accepted: bool
    month: int
    buyer_id: int
    seller_id: int
    time: int
    rate: int
    fee: int
    payer: Pubkey | None = None     # the relayer that paid its rent, and the only one that closes it (None: a mark from before CloseMark)
    close_after: int | None = None  # the chain time from which that relayer can close it (None: never)


def read_mark(data: bytes | None) -> Mark | None:
    """None: this evaluation was never billed, or its mark was closed after its month."""
    if not data or (len(data), data[0]) not in ((MARK_LEN, 2), (MARK_LEN_1, 1)):
        return None
    m = Mark(accepted=data[1] == 1, month=_n(data, 4, 4), buyer_id=_n(data, 8), seller_id=_n(data, 16), time=_i64(data, 24), rate=_n(data, 32), fee=_n(data, 40))
    if len(data) == MARK_LEN:
        m.payer, m.close_after = Pubkey.from_bytes(data[48:80]), _i64(data, 80)
    return m


def marks_of(ledger, payer: Pubkey, program: Pubkey = METER_ID) -> list[tuple[Pubkey, Mark]]:
    """Every mark whose rent `payer` put up: (address, mark), from one getProgramAccounts filtered by length and payer."""
    return [(k, m) for k, d in ledger.program_accounts(program, MARK_LEN, {MARK_PAYER: bytes(payer)}) if (m := read_mark(d)) is not None]


def closable(marks: list[tuple[Pubkey, Mark]], now: int) -> list[Pubkey]:
    """The marks of `marks_of` that CloseMark takes at `now` (the chain's clock)."""
    return [k for k, m in marks if m.close_after is not None and now >= m.close_after]


@dataclass
class Statement:
    """One buyer, one seller, one month: billable evaluations, how many were accepted and rejected, the declared value
    (the sum of `rate` over the accepted) and what they cost in credits."""
    buyer_id: int
    seller_id: int
    month: int
    evaluations: int = 0
    accepted: int = 0
    rejected: int = 0
    value: int = 0
    fees: int = 0


def read_month(data: bytes | None, buyer_id: int = 0, seller_id: int = 0, month: int = 0) -> Statement:
    """The account at month_pda(buyer, seller, month); zeros when nothing was recorded."""
    if not data or len(data) != MONTH_LEN or data[0] != 1:
        return Statement(buyer_id, seller_id, month)
    return Statement(buyer_id=_n(data, 8), seller_id=_n(data, 16), month=_n(data, 4, 4), evaluations=_n(data, 24), accepted=_n(data, 32),
                     rejected=_n(data, 40), value=_n(data, 48), fees=_n(data, 56))


def quote(plan: Plan, decimals: int, now: int) -> int:
    """What the next billable evaluation of this owner costs at `now`, in the mint's smallest units."""
    return 0 if plan.used_in(yyyymm(now)) < FREE_PER_MONTH else fee_units(plan.rate_at(now), decimals)


# -- the statement, from the logs ---------------------------------------------------------------------------------------
def parse_eval(line: str) -> dict[str, str] | None:
    """The fields of a `knosm:eval` log line; None for any other line."""
    if not line.startswith(EVAL):
        return None
    return dict(part.split("=", 1) for part in line[len(EVAL):].split(" ") if "=" in part)


def statement(ledger, buyer: int, seller: int, month: int, program: Pubkey = METER_ID, most: int = 100_000) -> Statement:
    """The month of one buyer and one seller, recomputed from the program's own log lines: every transaction that
    named the month's account is read (`ledger.history`, `ledger.logs`), and only what the meter itself logged in it
    counts. It equals `read_month(ledger.account(month_pda(...)))` while the cluster still has the transactions; a
    difference means the node's history is cut short, and the account is the count."""
    from ...chain import said
    out, seen = Statement(buyer, seller, month), set()
    for sig in ledger.history(month_pda(buyer, seller, month, program), most):
        for line in said(ledger.logs(sig), program):
            e = parse_eval(line)
            if e is None or (int(e["buyer"]), int(e["seller"]), int(e["month"])) != (buyer, seller, month):
                continue
            key = (e["order"], e["artifact"], e["policy"], e["milestone"])
            if key in seen:                     # the program bills an evaluation once; a node that repeats a row does not make two
                continue
            seen.add(key)
            ok = e["verdict"] == "1"
            out.evaluations += 1
            out.accepted += ok
            out.rejected += not ok
            out.value += int(e["rate"]) if ok else 0
            out.fees += int(e["fee"])
    return out


# -- instructions ---------------------------------------------------------------------------------------------------
def open_credits_ix(authority: Pubkey, owner_id: int, mint: Pubkey, wf_repo: str, wf_sha: str, token_program: Pubkey = TOKEN,
                    program: Pubkey = METER_ID) -> Instruction:
    """Opens `authority`'s credits for the evaluations of the GitHub owner `owner_id` (the buyer), and pins the
    workflows whose runs may spend them: attest.yml and prove.yml of the repository `wf_repo` ("owner/name") at the
    commit `wf_sha`. Sent again by the same wallet, it only sets a new pin."""
    if len(wf_sha) != 40:
        raise ValueError("the workflows are pinned by a full commit: 40 hex characters")
    credits = credits_pda(owner_id, authority, mint, program)
    return Instruction(program, b"\x00" + _u64(owner_id) + wf_repo_hash(wf_repo) + wf_sha.encode(),
                       [AccountMeta(authority, True, True), AccountMeta(credits, False, True), AccountMeta(crtok_pda(credits, program), False, True),
                        AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False), AccountMeta(token_program, False, False),
                        AccountMeta(SYSTEM, False, False)])


def deposit_ix(source: Pubkey, owner: Pubkey, credits: Pubkey, mint: Pubkey, amount: int, decimals: int, token_program: Pubkey = TOKEN,
               program: Pubkey = METER_ID) -> Instruction:
    """Adds money to credits: a plain TransferChecked of the token program, from `source` (a token account `owner`
    signs for) to the credits' token account. The meter is not called."""
    return Instruction(token_program, b"\x0c" + _u64(amount) + bytes([decimals]),
                       [AccountMeta(source, False, True), AccountMeta(mint, False, False), AccountMeta(crtok_pda(credits, program), False, True),
                        AccountMeta(owner, True, False)])


def withdraw_credits_ix(authority: Pubkey, credits: Pubkey, mint: Pubkey, amount: int = 0, dest_token: Pubkey | None = None,
                        token_program: Pubkey = TOKEN, program: Pubkey = METER_ID) -> Instruction:
    """Unspent credits back to the wallet that opened them. `amount` 0: everything. `dest_token`: a token account of
    that wallet (default: its associated token account)."""
    dest = dest_token if dest_token is not None else ata(authority, mint, token_program)
    return Instruction(program, b"\x01" + _u64(amount),
                       [AccountMeta(authority, True, False), AccountMeta(credits, False, False), AccountMeta(crtok_pda(credits, program), False, True),
                        AccountMeta(dest, False, True), AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False),
                        AccountMeta(token_program, False, False)])


def set_plan_ix(fee_owner: Pubkey, payer: Pubkey, owner_id: int, tier: int, rate: int, expiry: int, program: Pubkey = METER_ID) -> Instruction:
    """FEE_OWNER sets one owner's rate (millionths of a whole unit, PLAN_MIN..=FEE) until `expiry` (unix time)."""
    return Instruction(program, b"\x02" + _u64(owner_id) + bytes([tier]) + _u64(rate) + expiry.to_bytes(8, "little", signed=True),
                       [AccountMeta(fee_owner, True, False), AccountMeta(payer, True, True), AccountMeta(plan_pda(owner_id, program), False, True),
                        AccountMeta(SYSTEM, False, False)])


def record_ix(relayer: Pubkey, token: Pubkey, key: Pubkey, credits: Pubkey, c: Credits, audience: str, now: int, fee_token: Pubkey | None = None,
              program: Pubkey = METER_ID) -> Instruction:
    """Records the evaluation a verified token describes. `key` is the verifier's account of the key that verified
    it; `c` is read_credits of `credits`; `audience` is the token's; `now` is the chain's clock (`ledger.now()`),
    which decides the month. `fee_token`: a token account of the credits' mint owned by FEE_OWNER (default: its
    associated token account; create it with create_ata_ix before the first evaluation that costs something)."""
    e = parse_audience(audience)
    fee = fee_token if fee_token is not None else ata(FEE_OWNER, c.mint, c.token_program)
    return Instruction(program, b"\x03",
                       [AccountMeta(relayer, True, True), AccountMeta(token, False, False), AccountMeta(key, False, False), AccountMeta(credits, False, True),
                        AccountMeta(crtok_pda(credits, program), False, True), AccountMeta(plan_pda(e.buyer_id, program), False, True),
                        AccountMeta(mark_pda(e.buyer_id, e.key, program), False, True),
                        AccountMeta(month_pda(e.buyer_id, e.seller_id, yyyymm(now), program), False, True), AccountMeta(fee, False, True),
                        AccountMeta(c.mint, False, False), AccountMeta(auth_pda(program), False, False), AccountMeta(c.token_program, False, False),
                        AccountMeta(SYSTEM, False, False)])


def close_mark_ix(payer: Pubkey, mark: Pubkey, program: Pubkey = METER_ID) -> Instruction:
    """The relayer that paid a mark's rent takes all of it back and the mark is gone. `payer` signs and is the wallet
    the mark names; `mark` is mark_pda(buyer id, key) or an address from `marks_of`. Refused before the mark's
    `close_after` (error 124). Several fit in one transaction: one signature closes them all."""
    return Instruction(program, b"\x04", [AccountMeta(payer, True, True), AccountMeta(mark, False, True)])
