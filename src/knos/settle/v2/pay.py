"""Client for knos-pay, second deployment (programs-v2/knos_pay): the escrow that pays the author of a pull request
on a GitHub-signed token verified on chain by knos-oidc. Pure instruction builders, audiences and account readers;
no network. The program is upgradeable only through a multisig with a public 48-hour delay, until an outside review;
then made immutable.

A job is one bounty on one issue of one repository, funded from a Balance (`balance_pda`: money a wallet set aside
for the repositories of one GitHub owner, spent by GitHub-signed comments) or straight from a wallet:
`job_pda(repository_id, issue, source)`. Its terms are fixed at funding (`terms_json`, `terms_hash`). A signed token pays the
payee's bound wallet (`bind_pda`), else the address the pay token carries, else the job is held for the payee.

Tokens are verified with the second deployment's verifier client, `knos.settle.v2.oidc` (write_ixs, step_ix). Every
instruction here that takes a token also takes `key`, the verifier's account of the key that verified it:
`oidc.key_pda(issuer, n)`, which is also `oidc.read_token(token account data).key`. A token is refused once that key
is revoked (error 78) or has expired (77), however fresh the token is.

What a relay does with a verified token (anyone may relay; the money goes where the token and the chain say):

    fund  knos2:fund:...   the audience names the Balance it spends (`named_balance`): the funder's workflow chose it.
                           fund_balance_ix on that Balance, with the mint read_balance gives. On devnet, when it names
                           faucet_balance_pda(owner id): faucet_open_ix first, in the same transaction, then
                           fund_balance_ix on it with faucet_mint(). A fund token works once, only from its run's
                           first attempt, and a Balance takes its tokens in the order GitHub issued them.
                           With terms of MAX_TERMS bytes and one compute budget instruction the two together are 1223
                           of a transaction's 1232 bytes: with a second one (a priority fee) send faucet_open_ix in a
                           transaction of its own first.
    pay   knos2:pay:...    for each open job on (repository id, issue) with the token's terms hash and mode:
                           pay_ix(..., destination(read_bind(...), audience)); create the fee account and the wallet's
                           token account with create_ata_ix first.
    bind  knos2:bind:...   bind_ix; then settle_ix for each held job whose payee_id is the token's actor.
    no token               refund_ix for every open job past its deadline and every held job past its hold.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from . import load_ids

IDS = load_ids()            # the pinned ids, or a staging deployment named by KNOS_PROGRAM_IDS
PAY_ID = Pubkey.from_string(IDS["knos_pay"])
OIDC_ID = Pubkey.from_string(IDS["knos_oidc"])          # the verifier whose token accounts this escrow accepts
FEE_OWNER = Pubkey.from_string(IDS["fee_owner"])        # Knos's Squads vault: receives fees, nothing else
GUARDIAN = Pubkey.from_string(IDS["guardian"])          # may pause new funding, nothing else
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022 = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
ATA_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
USDC_DEVNET = Pubkey.from_string("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")  # Circle's devnet USDC
USDC_MAINNET = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
COUNTED = (USDC_DEVNET, USDC_MAINNET)   # the record counts real money only in these mints (and test money in the faucet's)

MERGE, TESTS = 0, 1
FEE_BPS, FEE_MIN, MIN_AMOUNT, MAX_AMOUNT, FAUCET_CAP = 250, 50_000, 1_000_000, 500_000_000, 100_000_000
MIN_WORK, MAX_WORK, HOLD, PAUSE_MAX = 60, 90 * 86_400, 180 * 86_400, 7 * 86_400
FUND_PERIOD, CLOCK_SLACK, MAX_TERMS = 60, 30, 600
TOKEN_AHEAD, TOKEN_LIFE = 300, 3600     # a token's iat is at most this far ahead of the chain's clock; its exp at most this long after its iat
JOB_LEN, BALANCE_LEN, BIND_LEN, REP_LEN = 320, 160, 56, 64
BALX_LEN, PLAN_LEN, ORDER_LEN, OPTS_LEN = 152, 24, 512, 48
# orders (2.1). Amounts are millionths of one whole unit of the mint: `units` gives the mint's smallest units.
ORDER_FEE_MIN, ORDER_FEE_MAX, ORDER_MIN_AMOUNT, TIP, TIP_FIRST, PLAN_BPS_MIN = 400_000, 25_000_000, 5_000_000, 50_000, 300_000, 50
MAX_HOLDBACK_BPS, MAX_WARRANTY_DAYS, MAX_KILL_BPS, MAX_PAYEES = 5000, 90, 2000, 4
F_FAUCET, F_PRIVATE, F_NEUTRAL, F_STANDING, F_TOKEN2022 = 1, 2, 4, 8, 16
STATES = {1: "open", 3: "held", 4: "warranty"}
ERRORS = {76: "the key that signed this token is not active on chain yet: it waits for its delay and the guardian's approval; try again after that",
          77: "the key that signed this token has expired on chain; run the rotate workflow and send Refresh for the key, then relay the token again while it is fresh",
          78: "the key that signed this token was revoked on chain, so the token can do nothing; run the workflow again for a token signed by another key",
          80: "a wrong account, or a missing signature",
          81: "the amount, the work time, the mode, the workflow commit, the terms or the pause length is outside what is allowed",
          82: "this issue already has a job from this funder, or the account is not a job",
          83: "too early or too late: the job is not in the state this needs",
          84: "the token is not verified, not GitHub's, expired, or its times are not GitHub's; a new run gives a new one",
          85: "the token's claims do not allow this: the event, the runner, the repository or its owner, or a re-run instead of a first run",
          86: "the token is not from the workflow this needs",
          87: "the token's audience does not match",
          88: "wrong destination, fee or refund account, or the payee has not bound a wallet yet",
          89: "only on a devnet build",
          90: "the faucet gives test USDC once per repository per minute, in the order GitHub issued the tokens; wait a minute and comment again",
          91: "this token is not newer than the last one used here, and a token works once; comment again for a new one",
          92: "this comment cannot spend that balance: only its repository owner and the spenders its wallet listed can",
          93: "more than that balance allows for one job",
          94: "the balance does not hold that much; add money to it or fund less",
          95: "this mint cannot be used: it is not a mint of the token program passed, or it can block or tax a transfer",
          96: "new funding is paused; payments, refunds, withdrawals and binds go on",
          97: "only the guardian can pause",
          98: "the balance exists already, is not a balance, or the signer is not the wallet that opened it",
          99: "a faucet balance holds test USDC and cannot be withdrawn",
          100: "more than this balance may spend in one day or in total; its wallet can raise the limit, or fund less",
          101: "this order exists already (use another seq), or the account is not an order",
          102: "only the fee owner sets a plan, with a rate of 50 to 250 basis points and an expiry in the future",
          103: "this order is both standing and has a holdback, and such an order is never paid: its money goes back to its funder at the deadline; fund a new one that is standing or has a holdback, not both"}


def units(micro: int, decimals: int = 6) -> int:
    """`micro` millionths of one whole unit of a mint with `decimals` decimals, in the mint's smallest units."""
    return min(micro * 10 ** decimals // 1_000_000, 2 ** 64 - 1)


def fee_of(amount: int, decimals: int = 6) -> int:
    """The fee of a job (2.0), taken out of its amount."""
    return min(max(amount * FEE_BPS // 10_000, units(FEE_MIN, decimals)), amount)


def order_fee(amount: int, bps: int = FEE_BPS, decimals: int = 6) -> int:
    """The fee of an order (2.1), which its funder pays on top of the amount. `bps`: FEE_BPS, or the owner's Plan."""
    return min(max(amount * bps // 10_000, units(ORDER_FEE_MIN, decimals)), units(ORDER_FEE_MAX, decimals))


def terms_json(terms: dict) -> bytes:
    """The canonical JSON of a job's terms: keys sorted, no spaces, ASCII. This is what the funding instruction
    carries and logs, and what `terms_hash` hashes."""
    raw = json.dumps(terms, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    if len(raw) > MAX_TERMS:
        raise ValueError(f"the terms are {len(raw)} bytes; a job takes at most {MAX_TERMS}")
    return raw


def terms_hash(terms: bytes) -> bytes:
    """sha256 of the terms JSON bytes: what a job stores and what the fund and pay audiences carry."""
    return hashlib.sha256(terms).digest()


def wf_repo_hash(repository: str) -> bytes:
    """sha256 of "owner/name": the repository whose fund.yml and prove.yml a job pins."""
    return hashlib.sha256(repository.encode()).digest()


def funder_key(funder: Pubkey | int) -> bytes:
    """A funder as the record counts it: the funding wallet, or the GitHub owner id of a Balance."""
    return bytes(funder) if isinstance(funder, Pubkey) else hashlib.sha256(b"gh" + _u64(funder)).digest()


def _u64(v: int) -> bytes:
    return v.to_bytes(8, "little")


def _pda(seeds: list[bytes], program: Pubkey) -> Pubkey:
    return Pubkey.find_program_address(seeds, program)[0]


# -- addresses --------------------------------------------------------------------------------------------------------
def auth_pda(program: Pubkey = PAY_ID) -> Pubkey:
    """The owner of every vault and of every Balance's token account. Only the program signs for it."""
    return _pda([b"auth"], program)


def vault_pda(mint: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"vault", bytes(mint)], program)


def balance_pda(owner_id: int, authority: Pubkey, mint: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    """The Balance a wallet (`authority`) opened for the repositories of the GitHub owner `owner_id`, in one mint."""
    return _pda([b"bal", _u64(owner_id), bytes(authority), bytes(mint)], program)


def faucet_mint(program: Pubkey = PAY_ID) -> Pubkey:
    """The devnet test-USDC mint (SPL Token, 6 decimals); its mint authority is the program."""
    return _pda([b"mint"], program)


def faucet_balance_pda(owner_id: int, program: Pubkey = PAY_ID) -> Pubkey:
    """The devnet faucet's Balance of a GitHub owner: test USDC that fund tokens of that owner's repositories spend."""
    return balance_pda(owner_id, auth_pda(program), faucet_mint(program), program)


def baltok_pda(balance: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    """A Balance's token account. Add money to a Balance with a plain token transfer to this address."""
    return _pda([b"baltok", bytes(balance)], program)


def job_pda(repo_id: int, issue: int, source: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    """A job's address. `source` is the Balance it is funded from, or the funding wallet. Anyone can add a bounty of
    their own to an issue: one signed token pays every job on the issue that pins the same workflow and terms."""
    return _pda([b"job", _u64(repo_id), _u64(issue), bytes(source)], program)


def bind_pda(user_id: int, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"bind", _u64(user_id)], program)


def rep_pda(user_id: int, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"rep", _u64(user_id)], program)


def pair_pda(payee_id: int, funder: Pubkey | int, program: Pubkey = PAY_ID) -> Pubkey:
    """Exists once this funder (a wallet, or the GitHub owner id of a Balance) has paid this payee in real money."""
    return _pda([b"pair", _u64(payee_id), funder_key(funder)], program)


def rate_pda(repo_id: int, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"rate", _u64(repo_id)], program)


def pause_pda(program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"pause"], program)


def sig_hash(token: str | bytes) -> bytes:
    """sha256 of a token's signature bytes: what names its single-use marker. `token`: the JWT as GitHub gave it, or
    the data of its token account in the verifier (the signature stays there as the token carried it)."""
    if isinstance(token, str):
        text = token.rsplit(".", 1)[1]
    else:
        jwt = bytes(token[626:626 + int.from_bytes(token[4:6], "little")])
        text = jwt.rsplit(b".", 1)[1].decode()
    return hashlib.sha256(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))).digest()


def used_pda(token: str | bytes, program: Pubkey = PAY_ID) -> Pubkey:
    """The marker of a token that works once (a 2.0 pay token, an order's fund token). `token`: as `sig_hash` takes it,
    or the 32 bytes sig_hash returned."""
    return _pda([b"used", token if isinstance(token, bytes) and len(token) == 32 else sig_hash(token)], program)


def ata(owner: Pubkey, mint: Pubkey, token_program: Pubkey = TOKEN) -> Pubkey:
    return _pda([bytes(owner), bytes(token_program), bytes(mint)], ATA_PROGRAM)


def create_ata_ix(payer: Pubkey, owner: Pubkey, mint: Pubkey, token_program: Pubkey = TOKEN) -> Instruction:
    """Creates the owner's associated token account if it does not exist (idempotent)."""
    return Instruction(ATA_PROGRAM, b"\x01", [AccountMeta(payer, True, True), AccountMeta(ata(owner, mint, token_program), False, True),
                                              AccountMeta(owner, False, False), AccountMeta(mint, False, False),
                                              AccountMeta(SYSTEM, False, False), AccountMeta(token_program, False, False)])


# -- audiences: what the workflows ask GitHub to sign ------------------------------------------------------------------
def fund_audience(issue: int, amount: int, mode: int, terms: bytes, balance: Pubkey, work_s: int = 14 * 86_400) -> str:
    """`terms` is terms_hash(...) (32 bytes). `balance` is the Balance this comment spends: the funder's workflow
    chooses it (a Balance of the repository's owner that lists the commenter; on devnet, with none,
    faucet_balance_pda(owner id)), and the program spends no other with this token."""
    return f"knos2:fund:{issue}:{amount}:{mode}:{terms.hex()}:{work_s}:{balance}"


def named_balance(audience: str) -> Pubkey:
    """The Balance a fund audience names: the one fund_balance_ix (and, when it is a faucet Balance, faucet_open_ix)
    must be given."""
    return Pubkey.from_string(audience.split(":")[-1])


def pay_audience(repo_id: int, issue: int, payee_id: int, head_sha: str, terms: bytes, mode: int, address: Pubkey | None = None) -> str:
    """`address`: where the payee asked to be paid in the pull request, or None (the job is then held for them unless
    they have bound a wallet)."""
    return f"knos2:pay:{repo_id}:{issue}:{payee_id}:{head_sha}:{terms.hex()}:{mode}:{address if address is not None else '-'}"


def bind_audience(address: Pubkey | str) -> str:      # the address as base58 text: a Pubkey prints as one
    return f"knos2:bind:{address}"


# -- accounts ---------------------------------------------------------------------------------------------------------
@dataclass
class Job:
    state: str              # "open", or "held" (the terms were met; waits for the payee to bind a wallet)
    mode: int
    from_balance: bool      # funded from a Balance by a comment (True) or by a wallet (False)
    token_program: Pubkey
    faucet: bool            # test money: the devnet faucet's mint
    repo_id: int
    issue: int
    amount: int
    deadline: int
    hold_until: int
    payee_id: int           # held: who the money waits for
    funder_id: int          # the GitHub id of whoever wrote the funding comment (0 for a wallet)
    not_before: int
    owner_id: int           # the Balance's GitHub owner (0 for a wallet)
    source: Pubkey          # the Balance, or the funding wallet
    refund_to: Pubkey       # the Balance's token account, or the funding wallet
    rent_to: Pubkey
    mint: Pubkey
    terms: bytes
    wf_repo_hash: bytes
    wf_sha: str

    @property
    def funder(self) -> Pubkey | int:
        """The funder the record counts: the Balance's GitHub owner id, or the funding wallet."""
        return self.owner_id if self.from_balance else self.source


def _i64(data: bytes, o: int) -> int:
    return int.from_bytes(data[o:o + 8], "little", signed=True)


def _n(data: bytes, o: int, size: int = 8) -> int:
    return int.from_bytes(data[o:o + size], "little")


def read_job(data: bytes | None) -> Job | None:
    if not data or len(data) != JOB_LEN:
        return None
    return Job(state=STATES.get(data[0], "?"), mode=data[1], from_balance=data[2] == 1, token_program=TOKEN_2022 if data[6] == 1 else TOKEN,
               faucet=data[7] == 1, repo_id=_n(data, 8), issue=_n(data, 16), amount=_n(data, 24), deadline=_i64(data, 32),
               hold_until=_i64(data, 48), payee_id=_n(data, 56), funder_id=_n(data, 64), not_before=_i64(data, 72), owner_id=_n(data, 80),
               source=Pubkey.from_bytes(data[88:120]), refund_to=Pubkey.from_bytes(data[120:152]), rent_to=Pubkey.from_bytes(data[152:184]),
               mint=Pubkey.from_bytes(data[184:216]), terms=bytes(data[216:248]), wf_repo_hash=bytes(data[248:280]),
               wf_sha=bytes(data[280:320]).decode("ascii", "replace"))


@dataclass
class Balance:
    faucet: bool
    owner_id: int
    authority: Pubkey
    mint: Pubkey
    cap_per_job: int        # 0: no cap
    last_iat: int
    spenders: tuple[int, ...]
    spent: int              # everything it ever put into jobs
    has_x: bool = False     # it has a side account (balx_pda): every funding from it must pass that account


def read_balance(data: bytes | None) -> Balance | None:
    if not data or len(data) != BALANCE_LEN or data[0] != 1:
        return None
    return Balance(faucet=data[2] == 1, owner_id=_n(data, 8), authority=Pubkey.from_bytes(data[16:48]), mint=Pubkey.from_bytes(data[48:80]),
                   cap_per_job=_n(data, 80), last_iat=_i64(data, 88), spenders=tuple(s for s in (_n(data, 96 + 8 * k) for k in range(4)) if s),
                   spent=_n(data, 128), has_x=data[3] == 1)


@dataclass
class Bind:
    user_id: int
    wallet: Pubkey
    iat: int


def read_bind(data: bytes | None) -> Bind | None:
    if not data or len(data) != BIND_LEN or data[0] != 1:
        return None
    return Bind(user_id=_n(data, 8), wallet=Pubkey.from_bytes(data[16:48]), iat=_i64(data, 48))


@dataclass
class Record:
    paid: int               # payments in real money from someone else
    funders: int            # distinct funders among them
    total: int              # what those payments put in the wallet
    test_paid: int          # payments in the faucet's test USDC
    self_paid: int          # payments whose funder was the payee
    test_total: int
    first: int              # time of the first and of the latest payment counted in `paid` (0: none yet)
    last: int


def read_rep(data: bytes | None) -> Record:
    if not data or len(data) != REP_LEN:
        return Record(0, 0, 0, 0, 0, 0, 0, 0)
    return Record(paid=_n(data, 0, 4), funders=_n(data, 4, 4), total=_n(data, 8), test_paid=_n(data, 16, 4), self_paid=_n(data, 20, 4),
                  test_total=_n(data, 32), first=_i64(data, 40), last=_i64(data, 48))


def read_pause(data: bytes | None) -> int:
    """The time until which new funding is refused (0: not paused, or never was). `data`: the account at pause_pda()."""
    return _i64(data, 0) if data and len(data) == 8 else 0


def read_rate(data: bytes | None) -> tuple[int, int]:
    """(when the devnet faucet last served a repository, that fund token's iat); (0, 0) when it never did. The next
    use is FUND_PERIOD later at the earliest, with a newer token. `data`: the account at rate_pda(repository id)."""
    return (_i64(data, 0), _i64(data, 8)) if data and len(data) == 16 else (0, 0)


def destination(bind: Bind | None, audience: str) -> Pubkey | None:
    """Where the program will pay a pay token: the payee's bound wallet, else the address the audience carries, else
    None (the job is held for the payee). `bind` is read_bind of bind_pda(payee id)."""
    if bind is not None:
        return bind.wallet
    address = audience.split(":")[-1]
    return None if address == "-" else Pubkey.from_string(address)


# -- instructions ---------------------------------------------------------------------------------------------------
def _limits(cap: int, spenders) -> bytes:
    ids = list(spenders)
    if len(ids) > 4:
        raise ValueError("a balance has at most 4 spenders")
    return _u64(cap) + b"".join(_u64(s) for s in ids + [0] * (4 - len(ids)))


def open_balance_ix(authority: Pubkey, owner_id: int, mint: Pubkey, cap: int = 0, spenders=(), token_program: Pubkey = TOKEN,
                    program: Pubkey = PAY_ID) -> Instruction:
    """Opens `authority`'s Balance for the repositories of the GitHub owner `owner_id`. `cap`: the most one job may
    take (0: no cap). `spenders`: up to 4 GitHub ids that may spend it by comment, besides the owner."""
    balance = balance_pda(owner_id, authority, mint, program)
    return Instruction(program, b"\x00" + _u64(owner_id) + _limits(cap, spenders),
                       [AccountMeta(authority, True, True), AccountMeta(balance, False, True), AccountMeta(baltok_pda(balance, program), False, True),
                        AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False), AccountMeta(token_program, False, False),
                        AccountMeta(SYSTEM, False, False)])


def set_balance_ix(authority: Pubkey, balance: Pubkey, cap: int = 0, spenders=(), program: Pubkey = PAY_ID) -> Instruction:
    return Instruction(program, b"\x01" + _limits(cap, spenders), [AccountMeta(authority, True, False), AccountMeta(balance, False, True)])


def withdraw_ix(authority: Pubkey, balance: Pubkey, mint: Pubkey, amount: int = 0, dest_token: Pubkey | None = None, token_program: Pubkey = TOKEN,
                program: Pubkey = PAY_ID) -> Instruction:
    """Unspent money back to the wallet that opened the Balance. `amount` 0: everything. `dest_token`: a token account
    of that wallet (default: its associated token account)."""
    dest = dest_token if dest_token is not None else ata(authority, mint, token_program)
    return Instruction(program, b"\x02" + _u64(amount),
                       [AccountMeta(authority, True, False), AccountMeta(balance, False, False), AccountMeta(baltok_pda(balance, program), False, True),
                        AccountMeta(dest, False, True), AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False),
                        AccountMeta(token_program, False, False)])


def fund_balance_ix(relayer: Pubkey, fund_token: Pubkey, key: Pubkey, balance: Pubkey, mint: Pubkey, repo_id: int, issue: int, terms: bytes,
                    token_program: Pubkey = TOKEN, program: Pubkey = PAY_ID, balx: bool = False) -> Instruction:
    """Funds the job a fund token describes from the Balance its audience names (`named_balance`). `key` is the
    verifier's account of the key that verified the token. `mint` is the Balance's; `repo_id` and `issue` are the
    token's; `terms` is the terms JSON whose hash the audience carries. `balx=True` adds the Balance's side account as a
    13th account: the program requires it once the Balance has one (read_balance(...).has_x)."""
    last = [AccountMeta(balx_pda(balance, program), False, True)] if balx else []
    return Instruction(program, b"\x03" + terms,
                       [AccountMeta(relayer, True, True), AccountMeta(fund_token, False, False), AccountMeta(key, False, False),
                        AccountMeta(balance, False, True), AccountMeta(baltok_pda(balance, program), False, True),
                        AccountMeta(job_pda(repo_id, issue, balance, program), False, True), AccountMeta(vault_pda(mint, program), False, True),
                        AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False), AccountMeta(token_program, False, False),
                        AccountMeta(SYSTEM, False, False), AccountMeta(pause_pda(program), False, False), *last])


def fund_wallet_ix(funder: Pubkey, funder_token: Pubkey, mint: Pubkey, repo_id: int, issue: int, amount: int, wf_repo: str, wf_sha: str, terms: bytes,
                   mode: int = MERGE, work_s: int = 14 * 86_400, token_program: Pubkey = TOKEN, program: Pubkey = PAY_ID) -> Instruction:
    """A wallet funds a job with its own money. `wf_repo` ("owner/name") and `wf_sha` pin the prove.yml whose signed run can pay it."""
    data = (b"\x04" + _u64(repo_id) + _u64(issue) + _u64(amount) + work_s.to_bytes(8, "little", signed=True) + bytes([mode])
            + wf_repo_hash(wf_repo) + wf_sha.encode() + terms)
    return Instruction(program, data,
                       [AccountMeta(funder, True, True), AccountMeta(job_pda(repo_id, issue, funder, program), False, True),
                        AccountMeta(funder_token, False, True), AccountMeta(vault_pda(mint, program), False, True), AccountMeta(mint, False, False),
                        AccountMeta(auth_pda(program), False, False), AccountMeta(token_program, False, False), AccountMeta(SYSTEM, False, False),
                        AccountMeta(pause_pda(program), False, False)])


def _payout_accounts(job: Pubkey, j: Job, payee_id: int, wallet: Pubkey | None, dest_token: Pubkey | None, program: Pubkey) -> list[AccountMeta]:
    vault = vault_pda(j.mint, program)
    # a job that will be held names no destination: the vault stands in, and the program does not touch it
    dest = dest_token if dest_token is not None else ata(wallet, j.mint, j.token_program) if wallet is not None else vault
    return [AccountMeta(job, False, True), AccountMeta(bind_pda(payee_id, program), False, False), AccountMeta(dest, False, True),
            AccountMeta(rep_pda(payee_id, program), False, True), AccountMeta(pair_pda(payee_id, j.funder, program), False, True),
            AccountMeta(vault, False, True), AccountMeta(ata(FEE_OWNER, j.mint, j.token_program), False, True),
            AccountMeta(auth_pda(program), False, False), AccountMeta(j.rent_to, False, True), AccountMeta(j.mint, False, False),
            AccountMeta(j.token_program, False, False), AccountMeta(SYSTEM, False, False)]


def pay_ix(relayer: Pubkey, pay_token: Pubkey, key: Pubkey, job: Pubkey, j: Job, payee_id: int, wallet: Pubkey | None,
           dest_token: Pubkey | None = None, program: Pubkey = PAY_ID, *, used: Pubkey | str | bytes) -> Instruction:
    """`key` is the verifier's account of the key that verified the token. `j` is read_job of `job`. `wallet` is
    destination(read_bind(...), audience): the program pays a token account of that wallet (default: its associated
    token account; create it and FEE_OWNER's with create_ata_ix first), or holds the job when it is None. `used`: the
    token's single-use marker, used_pda(...), or what used_pda takes (the JWT, or the token account's data): a pay
    token pays, or holds, exactly one job."""
    marker = used if isinstance(used, Pubkey) else used_pda(used, program)
    return Instruction(program, b"\x05", [AccountMeta(relayer, True, True), AccountMeta(pay_token, False, False), AccountMeta(key, False, False),
                                          *_payout_accounts(job, j, payee_id, wallet, dest_token, program), AccountMeta(marker, False, True)])


def settle_ix(relayer: Pubkey, job: Pubkey, j: Job, wallet: Pubkey, dest_token: Pubkey | None = None, program: Pubkey = PAY_ID) -> Instruction:
    """Pays a held job once its payee has bound a wallet: `wallet` is read_bind(bind_pda(j.payee_id)).wallet."""
    return Instruction(program, b"\x06", [AccountMeta(relayer, True, True), *_payout_accounts(job, j, j.payee_id, wallet, dest_token, program)])


def refund_ix(relayer: Pubkey, job: Pubkey, j: Job, refund_token: Pubkey | None = None, program: Pubkey = PAY_ID) -> Instruction:
    """An open job past its deadline, or a held job past its hold: the money back to the Balance it came from, or to a
    token account of the funding wallet (default: its associated token account)."""
    dest = refund_token if refund_token is not None else j.refund_to if j.from_balance else ata(j.refund_to, j.mint, j.token_program)
    return Instruction(program, b"\x07", [AccountMeta(relayer, True, True), AccountMeta(job, False, True), AccountMeta(vault_pda(j.mint, program), False, True),
                                          AccountMeta(dest, False, True), AccountMeta(auth_pda(program), False, False), AccountMeta(j.rent_to, False, True),
                                          AccountMeta(j.mint, False, False), AccountMeta(j.token_program, False, False)])


def bind_ix(relayer: Pubkey, bind_token: Pubkey, key: Pubkey, user_id: int, program: Pubkey = PAY_ID) -> Instruction:
    """`key` is the verifier's account of the key that verified the token. `user_id` is the token's actor_id."""
    return Instruction(program, b"\x08", [AccountMeta(relayer, True, True), AccountMeta(bind_token, False, False), AccountMeta(key, False, False),
                                          AccountMeta(bind_pda(user_id, program), False, True), AccountMeta(SYSTEM, False, False)])


def pause_ix(guardian: Pubkey, payer: Pubkey, seconds: int, program: Pubkey = PAY_ID) -> Instruction:
    """The guardian refuses new funding for `seconds` (at most PAUSE_MAX) from now; 0 lifts the pause."""
    return Instruction(program, b"\x09" + seconds.to_bytes(4, "little"),
                       [AccountMeta(guardian, True, False), AccountMeta(payer, True, True), AccountMeta(pause_pda(program), False, True),
                        AccountMeta(SYSTEM, False, False)])


def init_faucet_ix(payer: Pubkey, program: Pubkey = PAY_ID) -> Instruction:
    return Instruction(program, b"\x0a", [AccountMeta(payer, True, True), AccountMeta(faucet_mint(program), False, True),
                                          AccountMeta(auth_pda(program), False, False), AccountMeta(TOKEN, False, False), AccountMeta(SYSTEM, False, False)])


def faucet_open_ix(relayer: Pubkey, fund_token: Pubkey, key: Pubkey, owner_id: int, repo_id: int, program: Pubkey = PAY_ID) -> Instruction:
    """Devnet: mints the fund token's amount of test USDC into the faucet Balance of the token's repository owner
    (`owner_id`, `repo_id` are the token's), which the token's audience must name. `key` is the verifier's account of
    the key that verified the token. Send fund_balance_ix(..., faucet_balance_pda(owner_id), faucet_mint(), ...) after
    it, in the same transaction."""
    balance = faucet_balance_pda(owner_id, program)
    return Instruction(program, b"\x0b", [AccountMeta(relayer, True, True), AccountMeta(fund_token, False, False), AccountMeta(key, False, False),
                                          AccountMeta(balance, False, True), AccountMeta(baltok_pda(balance, program), False, True),
                                          AccountMeta(faucet_mint(program), False, True), AccountMeta(auth_pda(program), False, False),
                                          AccountMeta(TOKEN, False, False), AccountMeta(SYSTEM, False, False),
                                          AccountMeta(rate_pda(repo_id, program), False, True)])


# == orders (2.1) =====================================================================================================
# A work order is ["ord", scope, source, seq]: its money (the amount its payees receive, plus the fee its funder pays
# on top) is alone in its own token account, ov_pda(order). A funder fixes its options at funding (`opts`). It is paid
# on a pay token of one of its judges to 1..=4 payees, refunded after its deadline, topped up from where its money
# came. Audiences start `knos3:`, so no token of the jobs' generation (knos2) is good for an order, nor the reverse.
def scope_of(repo_id: int, issue: int, salt: bytes | None = None) -> bytes:
    """An order's scope. Public: sha256("knos3:scope" || repo id || issue). Private (`salt`, 32 bytes, kept off
    chain): sha256(salt || repo id || issue); the order then stores no repository and no issue."""
    return hashlib.sha256((b"knos3:scope" if salt is None else salt) + _u64(repo_id) + _u64(issue)).digest()


def order_pda(scope: bytes, source: Pubkey, seq: int = 0, program: Pubkey = PAY_ID) -> Pubkey:
    """`source`: the Balance the order is funded from, or the funding wallet. `seq`: the funder's own counter, so one
    source can fund an issue more than once."""
    return _pda([b"ord", scope, bytes(source), seq.to_bytes(4, "little")], program)


def ov_pda(order: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    """The token account that holds one order's money and nothing else."""
    return _pda([b"ov", bytes(order)], program)


def balx_pda(balance: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    """A Balance's side account: limits per day and in total, the repositories and the workflows commit that may spend it."""
    return _pda([b"balx", bytes(balance)], program)


def plan_pda(owner_id: int, program: Pubkey = PAY_ID) -> Pubkey:
    return _pda([b"plan", _u64(owner_id)], program)


def opts(flags: int = 0, holdback_bps: int = 0, warranty_days: int = 0, kill_bps: int = 0, reserve_days: int = 0, rate: int = 0, arbiter_id: int = 0,
         judge_repo_id: int = 0, salted: bool = False) -> bytes:
    """The 48 bytes a funder fixes beside the amount and the terms. `flags`: F_PRIVATE, F_NEUTRAL, F_STANDING."""
    return (bytes([flags]) + holdback_bps.to_bytes(2, "little") + warranty_days.to_bytes(2, "little") + kill_bps.to_bytes(2, "little")
            + bytes([reserve_days]) + _u64(rate) + _u64(arbiter_id) + _u64(judge_repo_id) + bytes([int(salted)]) + bytes(15))


def order_fund_audience(issue: int, amount: int, mode: int, terms: bytes, balance: Pubkey, work_s: int = 14 * 86_400, seq: int = 0,
                        options: bytes | None = None) -> str:
    """What fund.yml asks GitHub to sign to fund an order from a Balance. `terms` is terms_hash(...); `options` is opts(...)."""
    return f"knos3:fund:{issue}:{amount}:{mode}:{terms.hex()}:{work_s}:{balance}:{seq}:{(options or opts()).hex()}"


def payees_text(payees) -> str:
    """`payees`: 1..=4 of (GitHub id, basis points, address or None); the basis points add up to 10000."""
    return ",".join(f"{i}.{bps}.{a if a is not None else '-'}" for i, bps, a in payees)


def order_pay_audience(order: Pubkey, head_sha: str, terms: bytes, mode: int, pr: int, payees) -> str:
    """What a judge's workflow asks GitHub to sign to pay an order. `payees` as `payees_text` takes them."""
    return f"knos3:pay:{order}:{head_sha}:{terms.hex()}:{mode}:{pr}:{payees_text(payees)}"


def payees_of(audience: str) -> list[tuple[int, int, Pubkey | None]]:
    """The payees a pay audience of an order names: (GitHub id, basis points, address or None), in its order."""
    out = []
    for entry in audience.split(":")[-1].split(","):
        i, bps, a = entry.split(".")
        out.append((int(i), int(bps), None if a == "-" else Pubkey.from_string(a)))
    return out


@dataclass
class Order:
    state: str              # "open", "held" (proven; waits for its one payee to bind a wallet), "warranty"
    mode: int
    from_balance: bool
    flags: int              # F_FAUCET, F_PRIVATE, F_NEUTRAL, F_STANDING, F_TOKEN2022
    decimals: int
    reserve_days: int
    repo_id: int            # 0: private
    issue: int              # 0: private
    scope: bytes
    seq: int
    holdback_bps: int
    kill_bps: int
    amount: int             # what payees receive in total
    fee: int                # escrowed on top of it
    rate: int               # standing: what one accepted change is paid
    paid: int
    deadline: int
    not_before: int
    hold_until: int
    warranty_s: int
    reserved_by: int
    reserved_until: int
    cancel_at: int
    payee_id: int           # held: who the money waits for
    funder_id: int
    owner_id: int
    arbiter_id: int
    judge_repo_id: int
    source: Pubkey
    refund_to: Pubkey
    rent_to: Pubkey
    mint: Pubkey
    terms: bytes
    wf_repo_hash: bytes
    wf_sha: str
    fee_bps: int

    @property
    def token_program(self) -> Pubkey:
        return TOKEN_2022 if self.flags & F_TOKEN2022 else TOKEN

    @property
    def faucet(self) -> bool:
        return bool(self.flags & F_FAUCET)

    @property
    def funder(self) -> Pubkey | int:
        """The funder the record counts: the Balance's GitHub owner id, or the funding wallet."""
        return self.owner_id if self.from_balance else self.source

    def address(self, program: Pubkey = PAY_ID) -> Pubkey:
        return order_pda(self.scope, self.source, self.seq, program)


def read_order(data: bytes | None) -> Order | None:
    if not data or len(data) != ORDER_LEN or data[0] != 2:
        return None
    key = lambda o: Pubkey.from_bytes(data[o:o + 32])  # noqa: E731
    return Order(state=STATES.get(data[1], "?"), mode=data[2], from_balance=data[3] == 1, flags=data[4], decimals=data[6], reserve_days=data[7],
                 repo_id=_n(data, 8), issue=_n(data, 16), scope=bytes(data[24:56]), seq=_n(data, 56, 4), holdback_bps=_n(data, 60, 2),
                 kill_bps=_n(data, 62, 2), amount=_n(data, 64), fee=_n(data, 72), rate=_n(data, 80), paid=_n(data, 88), deadline=_i64(data, 96),
                 not_before=_i64(data, 104), hold_until=_i64(data, 112), warranty_s=_i64(data, 120), reserved_by=_n(data, 128),
                 reserved_until=_i64(data, 136), cancel_at=_i64(data, 144), payee_id=_n(data, 152), funder_id=_n(data, 160), owner_id=_n(data, 168),
                 arbiter_id=_n(data, 176), judge_repo_id=_n(data, 184), source=key(192), refund_to=key(224), rent_to=key(256), mint=key(288),
                 terms=bytes(data[320:352]), wf_repo_hash=bytes(data[352:384]), wf_sha=bytes(data[384:424]).decode("ascii", "replace"),
                 fee_bps=_n(data, 424, 2))


@dataclass
class BalanceX:
    day_limit: int          # the most the Balance may spend in one day (UTC), in the mint's smallest units; 0: no limit
    total_limit: int        # the most it may spend from the day this account was made; 0: no limit
    repos: tuple[int, ...]  # the only repository ids that may spend it; empty: any repository of the owner
    wf_sha: str             # the only commit of the pinned workflows that may spend it; "": any
    day: int                # the day (unix time // 86400) day_spent counts
    day_spent: int
    total_spent: int


def read_balx(data: bytes | None) -> BalanceX | None:
    if not data or len(data) != BALX_LEN or data[0] != 1:
        return None
    sha = bytes(data[88:128])
    return BalanceX(day_limit=_n(data, 8), total_limit=_n(data, 16), repos=tuple(r for r in (_n(data, 24 + 8 * k) for k in range(8)) if r),
                    wf_sha="" if sha == bytes(40) else sha.decode("ascii", "replace"), day=_i64(data, 128), day_spent=_n(data, 136),
                    total_spent=_n(data, 144))


@dataclass
class Plan:
    fee_bps: int
    owner_id: int
    expires: int


def read_plan(data: bytes | None) -> Plan | None:
    if not data or len(data) != PLAN_LEN or data[0] != 1:
        return None
    return Plan(fee_bps=_n(data, 2, 2), owner_id=_n(data, 8), expires=_i64(data, 16))


def plan_bps(plan: Plan | None, now: int) -> int:
    """The fee rate of an owner's orders now: its Plan's while it lasts, FEE_BPS otherwise."""
    return min(max(plan.fee_bps, PLAN_BPS_MIN), FEE_BPS) if plan is not None and now < plan.expires else FEE_BPS


def version_ix(program: Pubkey = PAY_ID) -> Instruction:
    """Simulate it: a 2.1 program logs `knos2:version 1`; a 2.0 program refuses the instruction."""
    return Instruction(program, b"\x0c", [])


def set_balance_x_ix(authority: Pubkey, balance: Pubkey, day_limit: int = 0, total_limit: int = 0, repos=(), wf_sha: str = "",
                     program: Pubkey = PAY_ID) -> Instruction:
    """The wallet that opened a Balance sets its side account. Limits are in the mint's smallest units (0: none);
    `repos`: up to 8 repository ids (none: any repository of the owner); `wf_sha`: 40 hex characters, or "" for any."""
    ids = list(repos)
    if len(ids) > 8:
        raise ValueError("a balance lists at most 8 repositories")
    data = b"\x0d" + _u64(day_limit) + _u64(total_limit) + b"".join(_u64(r) for r in ids + [0] * (8 - len(ids))) + (wf_sha.encode() or bytes(40))
    return Instruction(program, data, [AccountMeta(authority, True, True), AccountMeta(balance, False, True),
                                       AccountMeta(balx_pda(balance, program), False, True), AccountMeta(SYSTEM, False, False)])


def set_plan_ix(fee_owner: Pubkey, payer: Pubkey, owner_id: int, fee_bps: int, expires: int, program: Pubkey = PAY_ID) -> Instruction:
    """FEE_OWNER sets the fee rate (50..=250 basis points) of the orders of one repository owner until `expires`."""
    return Instruction(program, b"\x0e" + _u64(owner_id) + fee_bps.to_bytes(2, "little") + expires.to_bytes(8, "little", signed=True),
                       [AccountMeta(fee_owner, True, False), AccountMeta(payer, True, True), AccountMeta(plan_pda(owner_id, program), False, True),
                        AccountMeta(SYSTEM, False, False)])


def fund_order_wallet_ix(funder: Pubkey, funder_token: Pubkey, mint: Pubkey, repo_id: int, issue: int, amount: int, wf_repo: str, wf_sha: str,
                         terms: bytes, mode: int = MERGE, work_s: int = 14 * 86_400, seq: int = 0, options: bytes | None = None,
                         scope: bytes | None = None, token_program: Pubkey = TOKEN, program: Pubkey = PAY_ID) -> Instruction:
    """A wallet funds an order for an issue of any public repository: `amount` for the payees plus order_fee(amount)
    on top, from `funder_token`. `terms` is the terms JSON. A private order: `options` with F_PRIVATE and salted,
    `scope` = scope_of(repo id, issue, salt), `repo_id` and `issue` 0, and `terms` the 32-byte terms_hash."""
    o = options or opts()
    s = scope_of(repo_id, issue) if scope is None else scope
    order = order_pda(s, funder, seq, program)
    data = (b"\x0f" + _u64(issue) + _u64(repo_id) + _u64(amount) + bytes([mode]) + work_s.to_bytes(8, "little", signed=True) + seq.to_bytes(4, "little")
            + o + wf_repo_hash(wf_repo) + wf_sha.encode() + (scope or b"") + terms)
    return Instruction(program, data,
                       [AccountMeta(funder, True, True), AccountMeta(order, False, True), AccountMeta(ov_pda(order, program), False, True),
                        AccountMeta(funder_token, False, True), AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False),
                        AccountMeta(token_program, False, False), AccountMeta(SYSTEM, False, False), AccountMeta(pause_pda(program), False, False)])


def fund_order_balance_ix(relayer: Pubkey, fund_token: Pubkey, key: Pubkey, balance: Pubkey, mint: Pubkey, owner_id: int, repo_id: int, issue: int,
                          terms: bytes, used: Pubkey | str | bytes, seq: int = 0, token_program: Pubkey = TOKEN, program: Pubkey = PAY_ID) -> Instruction:
    """Funds the order a fund token (knos3:fund) describes from the Balance its audience names. `mint` and `owner_id`
    are the Balance's; `repo_id`, `issue` and `seq` are the token's; `terms` is the terms JSON whose hash the audience
    carries; `used` is the token's single-use marker, as pay_ix takes it."""
    order = order_pda(scope_of(repo_id, issue), balance, seq, program)
    marker = used if isinstance(used, Pubkey) else used_pda(used, program)
    return Instruction(program, b"\x10" + terms,
                       [AccountMeta(relayer, True, True), AccountMeta(fund_token, False, False), AccountMeta(key, False, False),
                        AccountMeta(balance, False, True), AccountMeta(baltok_pda(balance, program), False, True),
                        AccountMeta(balx_pda(balance, program), False, True), AccountMeta(plan_pda(owner_id, program), False, False),
                        AccountMeta(order, False, True), AccountMeta(ov_pda(order, program), False, True), AccountMeta(marker, False, True),
                        AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False), AccountMeta(token_program, False, False),
                        AccountMeta(SYSTEM, False, False), AccountMeta(pause_pda(program), False, False)])


def _order_common(relayer: Pubkey, order: Pubkey, o: Order, tip_token: Pubkey | None, program: Pubkey) -> list[AccountMeta]:
    tp = o.token_program
    return [AccountMeta(order, False, True), AccountMeta(ov_pda(order, program), False, True),
            AccountMeta(tip_token if tip_token is not None else ata(relayer, o.mint, tp), False, True),
            AccountMeta(ata(FEE_OWNER, o.mint, tp), False, True), AccountMeta(auth_pda(program), False, False), AccountMeta(o.rent_to, False, True),
            AccountMeta(o.mint, False, False), AccountMeta(tp, False, False), AccountMeta(SYSTEM, False, False), AccountMeta(ATA_PROGRAM, False, False)]


def _payee_accounts(o: Order, payee_id: int, wallet: Pubkey | None, dest_token: Pubkey | None, program: Pubkey) -> list[AccountMeta]:
    # a payee the order will be held for names no wallet: the system program stands in, and the program does not read it
    w = wallet if wallet is not None else SYSTEM
    dest = dest_token if dest_token is not None else ata(w, o.mint, o.token_program)
    return [AccountMeta(bind_pda(payee_id, program), False, False), AccountMeta(w, False, False), AccountMeta(dest, False, True),
            AccountMeta(rep_pda(payee_id, program), False, True), AccountMeta(pair_pda(payee_id, o.funder, program), False, True)]


def order_destination(bind: Bind | None, address: Pubkey | None) -> Pubkey | None:
    """Where the program pays one payee of an order: the address the token carries for it, else its bound wallet,
    else None (a single payee: the order is held for it; one of several: the payment is refused)."""
    return address if address is not None else bind.wallet if bind is not None else None


def pay_order_ix(relayer: Pubkey, pay_token: Pubkey, key: Pubkey, order: Pubkey, o: Order, payees, tip_token: Pubkey | None = None,
                 program: Pubkey = PAY_ID, pr: int = 0) -> Instruction:
    """`o` is read_order of `order`. `payees`: for each payee of the audience, in its order, (GitHub id, wallet) or
    (GitHub id, wallet, dest_token); `wallet` is order_destination(read_bind(...), the address the audience carries).
    The program pays each a token account of its wallet (default: its associated token account, which the program
    creates when it does not exist, at the relayer's cost and for a larger tip). `tip_token`: a token account of the
    relayer for the tip (default: its associated token account; it must exist, as FEE_OWNER's must).
    -- order terms: a payee who assigned this order's payment is paid at its assignee: pass `payee_wallet(...)` as
    its wallet. `pr`: the pull request the audience names (a STANDING order marks it)."""
    per = [m for p in payees for m in _payee_accounts(o, p[0], p[1], p[2] if len(p) > 2 else None, program)]
    return Instruction(program, b"\x11", [AccountMeta(relayer, True, True), AccountMeta(pay_token, False, False), AccountMeta(key, False, False),
                                          *_order_common(relayer, order, o, tip_token, program), *per,
                                          *_terms_accounts(order, o, [p[0] for p in payees], pr, program)])     # order terms


def settle_order_ix(relayer: Pubkey, order: Pubkey, o: Order, wallet: Pubkey, dest_token: Pubkey | None = None, tip_token: Pubkey | None = None,
                    program: Pubkey = PAY_ID) -> Instruction:
    """Pays a held order once its payee has bound a wallet: `wallet` is read_bind(bind_pda(o.payee_id)).wallet."""
    return Instruction(program, b"\x1a", [AccountMeta(relayer, True, True), *_order_common(relayer, order, o, tip_token, program),
                                          *_payee_accounts(o, o.payee_id, wallet, dest_token, program),
                                          AccountMeta(assign_pda(order, o.payee_id, program), False, False)])           # order terms


def refund_order_ix(relayer: Pubkey, order: Pubkey, o: Order, refund_token: Pubkey | None = None, program: Pubkey = PAY_ID,
                    kill_token: Pubkey | None = None) -> Instruction:
    """An open order past its deadline, or a held one past its hold: everything it holds back to the Balance it came
    from, or to a token account of the funding wallet (default: its associated token account).
    -- order terms: when a kill fee is due (kill_fee(o) > 0), `kill_token` is a token account of the taker's bound
    wallet and the fee is sent there first; with None (or a taker with no wallet) the fee stays held for him in the
    order, and the rest goes back now."""
    dest = refund_token if refund_token is not None else o.refund_to if o.from_balance else ata(o.refund_to, o.mint, o.token_program)
    kill = [] if not kill_fee(o) else [AccountMeta(bind_pda(o.reserved_by, program), False, False),
                                       AccountMeta(kill_token, False, True) if kill_token is not None else AccountMeta(SYSTEM, False, False)]
    return Instruction(program, b"\x16", [AccountMeta(relayer, True, True), AccountMeta(order, False, True), AccountMeta(ov_pda(order, program), False, True),
                                          AccountMeta(dest, False, True), AccountMeta(auth_pda(program), False, False), AccountMeta(o.rent_to, False, True),
                                          AccountMeta(o.mint, False, False), AccountMeta(o.token_program, False, False), *kill])


def top_up_ix(signer: Pubkey, order: Pubkey, o: Order, add: int, from_token: Pubkey | None = None, program: Pubkey = PAY_ID) -> Instruction:
    """Adds `add` to an open order's amount (the fee on it comes on top) from where its money came. A wallet's order:
    the funding wallet signs and `from_token` is a token account of it (default: its associated token account). A
    Balance's order: the wallet that opened the Balance signs and the Balance's token account pays."""
    src = from_token if from_token is not None else o.refund_to if o.from_balance else ata(o.source, o.mint, o.token_program)
    return Instruction(program, b"\x17" + _u64(add),
                       [AccountMeta(signer, True, True), AccountMeta(order, False, True), AccountMeta(ov_pda(order, program), False, True),
                        AccountMeta(src, False, True), AccountMeta(o.source, False, False), AccountMeta(o.mint, False, False),
                        AccountMeta(auth_pda(program), False, False), AccountMeta(o.token_program, False, False), AccountMeta(pause_pda(program), False, False)])


# == judges of an order (2.1, order_judge.rs): begin ==================================================================
# Who may sign a payment of an order: its own repository's prove.yml (a); with F_NEUTRAL, attest.yml started by hand
# by the owner of the repository it runs in (b); a run in the order's judge repository (c); the arbiter's ruling (d).
# pay_order_ix is the same for all four: the judge is in the token's claims, never in the accounts.
def private_fund_terms(scope: bytes, terms: bytes) -> bytes:
    """What the fund audience of a PRIVATE order carries where a public one carries its terms hash:
    sha256(scope || terms hash). GitHub's signature then fixes both, and the audience (which is public, as every
    token is) names neither the repository nor the issue: pass issue 0 to order_fund_audience."""
    return hashlib.sha256(scope + terms).digest()


def fund_private_order_balance_ix(relayer: Pubkey, fund_token: Pubkey, key: Pubkey, balance: Pubkey, mint: Pubkey, owner_id: int, scope: bytes,
                                  terms: bytes, used: Pubkey | str | bytes, seq: int = 0, token_program: Pubkey = TOKEN,
                                  program: Pubkey = PAY_ID) -> Instruction:
    """Funds a PRIVATE order from a Balance: fund_order_balance_ix's accounts, and as data the order's scope
    (scope_of(repo id, issue, salt)) and its 32-byte terms hash. The fund token is from fund.yml in the order's judge
    repository (opts: F_PRIVATE, salted, judge_repo_id), with issue 0 and private_fund_terms(scope, terms) as terms."""
    order = order_pda(scope, balance, seq, program)
    marker = used if isinstance(used, Pubkey) else used_pda(used, program)
    return Instruction(program, b"\x10" + scope + terms,
                       [AccountMeta(relayer, True, True), AccountMeta(fund_token, False, False), AccountMeta(key, False, False),
                        AccountMeta(balance, False, True), AccountMeta(baltok_pda(balance, program), False, True),
                        AccountMeta(balx_pda(balance, program), False, True), AccountMeta(plan_pda(owner_id, program), False, False),
                        AccountMeta(order, False, True), AccountMeta(ov_pda(order, program), False, True), AccountMeta(marker, False, True),
                        AccountMeta(mint, False, False), AccountMeta(auth_pda(program), False, False), AccountMeta(token_program, False, False),
                        AccountMeta(SYSTEM, False, False), AccountMeta(pause_pda(program), False, False)])


def rule_audience(order: Pubkey, payees) -> str:
    """What attest.yml asks GitHub to sign when the arbiter an order named decides it (judge d): who is paid, and in
    what shares. `payees` as `payees_text` takes them; the arbiter himself cannot be one. The ruling is relayed with
    pay_order_ix, like any pay token."""
    return f"knos3:rule:{order}:{payees_text(payees)}"


def org_bind_audience(address: Pubkey | str) -> str:
    """What the pinned claim workflow asks GitHub to sign when it is started by hand in an ORGANISATION's repository
    named knos-claim: the organisation is paid at `address`. (A person binds with bind_audience, in a repository of
    his own; neither token does the other's work.)"""
    return f"knos3:bind:{address}"


def bind_org_ix(relayer: Pubkey, bind_token: Pubkey, key: Pubkey, org_id: int, program: Pubkey = PAY_ID) -> Instruction:
    """25 BindOrg. `key` is the verifier's account of the key that verified the token; `org_id` is the token's
    repository_owner_id. The Bind is the account a person's is, bind_pda(org_id): a payee id that is an organisation
    is then paid like any other."""
    return Instruction(program, b"\x19", [AccountMeta(relayer, True, True), AccountMeta(bind_token, False, False), AccountMeta(key, False, False),
                                          AccountMeta(bind_pda(org_id, program), False, True), AccountMeta(SYSTEM, False, False)])
# == judges of an order: end ==========================================================================================
# == order terms (2.1): BEGIN ========================================================================================
# What an order can promise (programs-v2/knos_pay/src/order_terms.rs): a holdback kept through a warranty (Release,
# Revert), a standing offer paid once per pull request, a reservation (Reserve), a cancellation with notice and a
# kill fee (Cancel, RefundOrder), an assigned payment (Assign), and markers that are closed when they no longer
# matter (CloseMarker).
HB_LEN, DONE_LEN, AS_LEN, USED_LEN = 240, 65, 88, 41
NOTICE = 7 * 86_400                                 # a cancelled order still takes a pay token for this long
USED_KEEP = TOKEN_AHEAD + TOKEN_LIFE + 3600 + 3600  # a used marker can be closed this long after it was made


def hb_pda(order: Pubkey, program: Pubkey = PAY_ID) -> Pubkey:
    """Where the holdback of an order in warranty goes."""
    return _pda([b"hb", bytes(order)], program)


def done_pda(order: Pubkey, pr: int, program: Pubkey = PAY_ID) -> Pubkey:
    """Exists once a standing order has paid this pull request."""
    return _pda([b"done", bytes(order), _u64(pr)], program)


def assign_pda(order: Pubkey, payee_id: int, program: Pubkey = PAY_ID) -> Pubkey:
    """The wallet an order pays for this payee instead of the payee's own."""
    return _pda([b"as", bytes(order), _u64(payee_id)], program)


def take_audience(order: Pubkey, taker_id: int, days: int) -> str:
    """What the taker's own run asks GitHub to sign to reserve an order for `taker_id` for `days` (at most the order's
    reserve_days): the order's repository answering his comment (fund.yml) or his pull request (prove.yml), or, for a
    NEUTRAL order, attest.yml he started by hand in a repository of his. The token's actor must be `taker_id`."""
    return f"knos3:take:{order}:{taker_id}:{days}"


def cancel_audience(order: Pubkey) -> str:
    """What the order's own repository asks GitHub to sign (fund.yml answering a comment, or prove.yml) to cancel an
    order funded from a Balance. The token's actor must be the commenter who funded it or the Balance's owner."""
    return f"knos3:cancel:{order}"


def revert_audience(order: Pubkey, head_sha: str) -> str:
    """What a judge of the order (a, b or c; not the arbiter) asks GitHub to sign when the accepted change was reverted
    inside the warranty."""
    return f"knos3:revert:{order}:{head_sha}"


@dataclass
class Holdback:
    payer: Pubkey                           # who paid the record's rent and gets it back
    until: int                              # the end of the warranty
    payees: list[tuple[int, Pubkey, int]]   # (GitHub id, wallet, amount) each


def read_holdback(data: bytes | None) -> Holdback | None:
    """`data`: the account at hb_pda(order)."""
    if not data or len(data) != HB_LEN or data[0] != 1:
        return None
    at = [48 + 48 * k for k in range(data[2])]
    return Holdback(payer=Pubkey.from_bytes(data[8:40]), until=_i64(data, 40),
                    payees=[(_n(data, o), Pubkey.from_bytes(data[o + 8:o + 40]), _n(data, o + 40)) for o in at])


def read_assign(data: bytes | None, o: Order | None = None) -> Pubkey | None:
    """The assignee in the account at assign_pda(order, payee). With `o` (the order as it is now): None too when the
    assignment was made for an earlier order at the same address, which the program ignores."""
    if not data or len(data) != AS_LEN or data[0] != 1 or (o is not None and _i64(data, 80) != o.not_before):
        return None
    return Pubkey.from_bytes(data[48:80])


def payee_wallet(assign: bytes | None, o: Order, bind: Bind | None, address: Pubkey | None) -> Pubkey | None:
    """Where the program pays one payee of an order: its assignee (`assign`: the account at assign_pda), else as
    order_destination says."""
    return read_assign(assign, o) or order_destination(bind, address)


def read_marker(data: bytes | None) -> tuple[Pubkey, int | Pubkey] | None:
    """A marker's rent payer and, for a used marker, the time after which it can be closed; for a done marker, its order."""
    if data and len(data) == USED_LEN:
        return Pubkey.from_bytes(data[1:33]), _i64(data, 33)
    if data and len(data) == DONE_LEN:
        return Pubkey.from_bytes(data[1:33]), Pubkey.from_bytes(data[33:65])
    return None


def kill_fee(o: Order) -> int:
    """What a refund owes the taker first: kill_bps of the amount, when an open order was cancelled while reserved."""
    if o.state != "open" or not o.kill_bps or not o.cancel_at or not o.reserved_by or o.cancel_at > o.reserved_until:
        return 0
    return min(o.amount * o.kill_bps // 10_000, o.amount - o.paid)


def _terms_accounts(order: Pubkey, o: Order, payee_ids, pr: int, program: Pubkey) -> list[AccountMeta]:
    """What PayOrder takes after its payees: each payee's assignment, then a standing order's marker or a holdback's record."""
    out = [AccountMeta(assign_pda(order, i, program), False, False) for i in payee_ids]
    if o.flags & F_STANDING:
        out.append(AccountMeta(done_pda(order, pr, program), False, True))
    elif o.holdback_bps:
        out.append(AccountMeta(hb_pda(order, program), False, True))
    return out


def release_ix(relayer: Pubkey, order: Pubkey, o: Order, hb: Holdback, tip_token: Pubkey | None = None, program: Pubkey = PAY_ID) -> Instruction:
    """After the warranty, anyone: the holdback to the recorded wallets (their associated token accounts, created
    when missing), the tip to the relayer, the rest of the fee to FEE_OWNER. `hb`: read_holdback of hb_pda(order)."""
    per = [m for _, w, _ in hb.payees for m in (AccountMeta(w, False, False), AccountMeta(ata(w, o.mint, o.token_program), False, True))]
    c = _order_common(relayer, order, o, tip_token, program)     # order ov tip fee auth rent_to mint token_program system ata_program
    return Instruction(program, b"\x12", [AccountMeta(relayer, True, True), c[0], c[1], AccountMeta(hb_pda(order, program), False, True), c[2], c[3], c[4],
                                          c[5], AccountMeta(hb.payer, False, True), *c[6:], *per])


def revert_ix(relayer: Pubkey, revert_token: Pubkey, key: Pubkey, order: Pubkey, o: Order, hb: Holdback, refund_token: Pubkey | None = None,
              program: Pubkey = PAY_ID) -> Instruction:
    """Inside the warranty, on a revert token of one of the order's judges (a, b or c): everything the order holds back to its funder."""
    dest = refund_token if refund_token is not None else o.refund_to if o.from_balance else ata(o.refund_to, o.mint, o.token_program)
    return Instruction(program, b"\x13", [AccountMeta(relayer, True, False), AccountMeta(revert_token, False, False), AccountMeta(key, False, False),
                                          AccountMeta(order, False, True), AccountMeta(ov_pda(order, program), False, True),
                                          AccountMeta(hb_pda(order, program), False, True), AccountMeta(dest, False, True),
                                          AccountMeta(auth_pda(program), False, False), AccountMeta(o.rent_to, False, True),
                                          AccountMeta(hb.payer, False, True), AccountMeta(o.mint, False, False), AccountMeta(o.token_program, False, False)])


def reserve_ix(relayer: Pubkey, take_token: Pubkey, key: Pubkey, order: Pubkey, program: Pubkey = PAY_ID) -> Instruction:
    """Reserves an order for the taker a take token names."""
    return Instruction(program, b"\x14", [AccountMeta(relayer, True, False), AccountMeta(take_token, False, False), AccountMeta(key, False, False),
                                          AccountMeta(order, False, True)])


def cancel_ix(signer: Pubkey, order: Pubkey, cancel_token: Pubkey | None = None, key: Pubkey | None = None, program: Pubkey = PAY_ID) -> Instruction:
    """Gives notice: the deadline becomes min(deadline, now + NOTICE). A wallet's order: `signer` is the funding
    wallet. A Balance's order: anyone signs and `cancel_token` (with its `key`) carries cancel_audience(order)."""
    tok: list[AccountMeta] = []
    if cancel_token is not None:
        if key is None:
            raise ValueError("cancel_ix: a cancel token is read with its key; give `key` too")
        tok = [AccountMeta(cancel_token, False, False), AccountMeta(key, False, False)]
    return Instruction(program, b"\x15", [AccountMeta(signer, True, False), AccountMeta(order, False, True), *tok])


def assign_ix(signer: Pubkey, order: Pubkey, payee_id: int, to: Pubkey, program: Pubkey = PAY_ID) -> Instruction:
    """This order's payment for `payee_id` goes to the wallet `to`. `signer`: the payee's bound wallet the first time,
    the current assignee after that."""
    return Instruction(program, b"\x18" + _u64(payee_id) + bytes(to),
                       [AccountMeta(signer, True, True), AccountMeta(order, False, False), AccountMeta(bind_pda(payee_id, program), False, False),
                        AccountMeta(assign_pda(order, payee_id, program), False, True), AccountMeta(SYSTEM, False, False)])


def close_marker_ix(marker: Pubkey, rent_to: Pubkey, order: Pubkey | None = None, program: Pubkey = PAY_ID) -> Instruction:
    """Closes a used marker (used_pda) once its time has passed, or a done marker (done_pda) once its `order` is
    closed. `rent_to`: who paid the marker's rent (read_marker(...)[0]); it gets the rent back."""
    return Instruction(program, b"\x1b", [AccountMeta(marker, False, True), AccountMeta(rent_to, False, True),
                                          AccountMeta(order if order is not None else SYSTEM, False, False)])
# == order terms (2.1): END ==========================================================================================
