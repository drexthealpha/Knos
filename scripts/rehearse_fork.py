"""The money flows of the second deployment, rehearsed on a Surfpool fork of mainnet-beta: nothing here costs anything
and nothing reaches a cluster. scripts/rehearse_fork.sh starts the fork and runs this.

    python scripts/rehearse_fork.py --rpc URL

What is real on the fork: the USDC mint (Circle's, with its freeze authority), the token programs, the Squads program,
and the clock the fork was taken at. What is loaded into it: the test build of knos-oidc and the no-faucet test build
of knos-pay (tests/fixtures), each at its pinned program id. A test build also trusts a seed-derived signing key, which
tests/_settle.py makes and this script uses to play GitHub, and a test guardian; the released builds trust GitHub's keys
and the pinned guardian only, so they cannot be run here.

    1  the fork            which cluster it copies, its clock, the real Squads program and the real USDC mint
    2  the programs        both builds written at the pinned ids; the faucet is refused (this is the real-money build)
    3  a signing key       the test key registered with knos-oidc: usable at once
    4  a wallet            SOL, and real USDC from the surfnet_setTokenAccount cheatcode; token accounts for the payee and the fee
    5  wallet funding      the wallet funds a bounty with its own USDC
    6  a Balance           the wallet opens a Balance for a repository owner and puts USDC in it
    7  a bounty by comment  a GitHub-signed comment (test key) funds a second bounty from the Balance, verified on chain
    8  a payment            a GitHub-signed proof pays the first bounty: the payee gets 97.5%, the fee account 2.5%
    9  a refund             the second bounty's deadline passes (surfnet_timeTravel); the money goes back to the Balance

Every step prints what it did and what it found; the first thing that is not as it should be stops the run (exit 1).
The fork's clock stands still until it is told to move, and a move can land minutes short of where it was sent (measured:
up to about 190 s), so the clock is asked again until it is there.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))      # tests/_settle.py: the test signing key the test builds trust

from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from knos import chain  # noqa: E402
from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import oidc, pay, relay  # noqa: E402

try:
    from _settle import github_claims, modulus, sign_jwt, signing_key  # noqa: E402
except ImportError as why:  # pragma: no cover - the message is the point
    raise SystemExit(f"stopped: the test signing key comes from tests/_settle.py, which needs the repository's test requirements "
                     f"({why}). Run: pip install -e '.[dev]'") from None

FIX = ROOT / "tests" / "fixtures"
BUILDS = {"knos_oidc": "knos_oidc_v2_test.so", "knos_pay": "knos_pay_v2_nodevnet.so"}
USDC_MINT = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")     # Circle's USDC on mainnet-beta
SQUADS = Pubkey.from_string(oidc.IDS["squads_program"])
USDC, DAY = 1_000_000, 86_400
OWNER, MAINT = 424242, 555000                      # the repository owner (a Balance's owner), a maintainer who may spend the Balance
OWNER_REPO = 987654321                             # the repository's GitHub id
WF_REPO, WF_SHA, HEAD = "drexthealpha/Knos", "c" * 40, "a" * 40
TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge",
                        "paths": [], "reserve": 7, "v": 1})
_IDS = ("repository_id", "repository_owner_id", "actor_id", "run_number", "run_id", "run_attempt")
STEPS = 9
CODES = {82: "the account is not a job", 83: "not the time or state for it", 89: "devnet builds only"}      # knos-pay's errors, as lib.rs words them


class Failed(Exception):
    """What was not as it should be, in words."""


def usdc(units: int) -> str:
    return f"{units / USDC:,.6f}".rstrip("0").rstrip(".") + " USDC"


def day(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def code_of(why: BaseException) -> int | None:
    """The error code of one of the programs, as a cluster words it: `custom program error: 0x59`, `Custom(89)` or {"Custom": 89}."""
    text = f"{why} {getattr(why, 'data', '')}"
    m = re.search(r"custom program error: 0x([0-9a-fA-F]+)", text)
    if m:
        return int(m.group(1), 16)
    m = re.search(r"Custom\((\d+)\)|['\"]Custom['\"]: (\d+)", text)
    return int(m.group(1) or m.group(2)) if m else None


class Rehearsal:
    def __init__(self, url: str, say=print):
        self.url, self.ledger, self.say, self.n = url, chain.Ledger(url), say, 0
        self.relayer = Keypair()        # pays the fees, and relays every token
        self.key = None                 # the verifier's account of the test key
        self.github = modulus(signing_key())
        self.base = int(time.time()) % 1_000_000_000      # issue numbers that no earlier run on this fork used
        self.payee = 2_000_000 + self.base % 7_000_000    # a contributor's GitHub id that no earlier run on this fork used
        self._jti = 0

    # ---- plumbing ---------------------------------------------------------------------------------------------------
    def step(self, title: str) -> None:
        self.n += 1
        self.say(f"\n[{self.n}/{STEPS}] {title}")

    def ok(self, line: str) -> None:
        self.say(f"  ok  {line}")

    def expect(self, condition: bool, what: str) -> None:
        if not condition:
            raise Failed(what)

    @staticmethod
    def again(read, *args, **kw):
        """A read, tried up to three times: a fork reading an account from mainnet for the first time can be slow, or drop the first try."""
        for attempt in range(3):
            try:
                return read(*args, **kw)
            except (chain.RpcError, OSError):
                if attempt == 2:
                    raise
                time.sleep(2)

    def rpc(self, method: str, params: list, timeout: float = 90.0):
        return self.again(chain.call, self.url, method, params, timeout=timeout)

    def now(self) -> int:
        return self.again(self.ledger.now)

    def started(self, within: float = 30.0) -> int:
        """The fork's clock, once the fork has one: a Surfpool makes a block only when a transaction arrives, and has no block
        time before the first."""
        end = time.monotonic() + within
        while True:
            try:
                return self.ledger.now()
            except (chain.RpcError, OSError) as why:
                if time.monotonic() > end:
                    raise Failed(f"the fork at {self.url} gave no clock in {within:.0f} s ({why})") from None
                time.sleep(1)

    def send(self, ixs, payer: Keypair | None = None, signers=None) -> str:
        """The signature of a transaction that landed; a cluster that could not even try it is asked again, a program's refusal is not."""
        last: Exception | None = None
        for attempt in range(3):
            try:
                return self.ledger.send(ixs, payer or self.relayer, signers)
            except chain.RpcError as why:
                if isinstance(why.data, dict) and why.data.get("logs") or code_of(why) is not None:
                    raise          # a program ran and refused: that is an answer, not a cluster that was not ready
                last = why
            except (OSError, TimeoutError) as why:
                last = why
            time.sleep(2 * (attempt + 1))
        raise Failed(f"the fork did not take the transaction after three tries ({last})")

    def refusal(self, ixs, payer: Keypair | None = None, signers=None) -> chain.RpcError | None:
        """The program's refusal, or None if the transaction went through."""
        try:
            self.send(ixs, payer, signers)
        except chain.RpcError as why:
            return why
        return None

    @staticmethod
    def said(why: chain.RpcError | None) -> str:
        if why is None:
            return "accepted"
        code = code_of(why)
        return f"refused ({str(why)[:120]})" if code is None else f"refused with error {code}" + (f" ({CODES[code]})" if code in CODES else "")

    def logs(self, sig: str) -> list[str]:
        try:
            # version 1, as every reader of knos asks (src/knos/records.py): a transaction a relay sent to a 2.1 program is one
            got = chain.call(self.url, "getTransaction", [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}], timeout=30)
            return [line.split("Program log: ", 1)[1] for line in got["meta"]["logMessages"] if "Program log: knos2:" in line]
        except Exception:  # noqa: BLE001 - the logs are a courtesy; the accounts say what happened
            return []

    def closing(self, address: Pubkey, job, ixs) -> tuple[str, str]:
        """Sends the instruction that closes the job at `address`: the job must be gone, and its rent back with whoever paid it.
        Returns the signature and a few words on where the rent went."""
        rent_to, rent = job.rent_to, self.lamports(address)
        before = self.lamports(rent_to)
        sig = self.send(ixs)
        gain = self.lamports(rent_to) - before
        fee = 5_000 if rent_to == self.relayer.pubkey() else 0        # the relayer signs, and a signature costs 5,000 lamports
        self.expect(self.data(address) is None, f"the job {address} is still there after the instruction that closes it")
        self.expect(gain == rent - fee, f"the job's rent ({rent} lamports) did not go to {rent_to}: that account gained {gain}")
        who = "the wallet that funded it" if rent_to == self.funder.pubkey() else "the relayer that opened it" if rent_to == self.relayer.pubkey() else str(rent_to)
        return sig, f"the job is closed and its rent ({rent / 1e9:.6f} SOL) went back to {who}"

    def data(self, address: Pubkey) -> bytes | None:
        return self.again(self.ledger.account, address)

    def token_balance(self, account: Pubkey) -> int:
        d = self.data(account)
        return int.from_bytes(d[64:72], "little") if d and len(d) >= 165 else 0

    def lamports(self, address: Pubkey) -> int:
        return int(self.rpc("getBalance", [str(address), {"commitment": "confirmed"}])["value"])

    def airdrop(self, address: Pubkey, sol: int) -> None:
        sig = self.rpc("requestAirdrop", [str(address), sol * 10 ** 9])
        chain.wait(self.url, sig, 60.0)

    def travel_to(self, target: int) -> int:
        """Moves the fork's clock to `target` or later. surfnet_timeTravel can land minutes before the time it is given, and the
        clock stands still between calls, so it is asked again with what is still missing."""
        if self.now() >= target:
            return self.now()
        asked = target + 300
        for _ in range(6):
            self.rpc("surfnet_timeTravel", [{"absoluteTimestamp": asked * 1000}])
            have = self.now()
            if have >= target:
                return have
            asked += target - have + 300
        raise Failed(f"the fork's clock is at {day(self.now())} after six tries to move it to {day(target)}")

    # ---- tokens: the test key plays GitHub --------------------------------------------------------------------------------
    def gh(self, aud: str, file: str = "prove.yml", **over) -> Pubkey:
        """A GitHub Actions token for this audience, signed by the test key, written to the chain and verified there."""
        now = self.now()
        self._jti += 1
        claims = dict(aud=aud, iat=now, nbf=now - 600, exp=now + 300, jti=f"rehearsal-{self.base}-{self._jti}",
                      job_workflow_ref=f"{WF_REPO}/.github/workflows/{file}@refs/tags/v0.3.12", job_workflow_sha=WF_SHA)
        claims.update(over)
        jwt = sign_jwt(signing_key(), github_claims(**{k: str(v) if k in _IDS else v for k, v in claims.items()}))
        tid, me = oidc.token_id(jwt), self.relayer.pubkey()
        for ix in oidc.write_ixs(me, tid, jwt):
            self.send([ix])
        for squarings in oidc.step_plan(self.github.bit_length()):
            self.send([oidc.step_ix(me, tid, self.key, squarings)])
        token = oidc.token_pda(me, tid)
        self.expect(oidc.read_token(self.data(token)).stage == 2, "the token was written and stepped, but the verifier does not call it verified")
        self.jwt = jwt          # the pay token's single-use marker is derived from it (pay.used_pda)
        return token

    # ---- the steps --------------------------------------------------------------------------------------------------------
    def fork(self) -> None:
        self.step("the fork")
        genesis = self.rpc("getGenesisHash", [])
        named = mc.GENESIS.get(genesis, "a cluster of its own")
        self.ok(f"{self.url} copies {named} (genesis {genesis[:8]}...); slot {self.rpc('getSlot', [])}")
        self.expect(named == "mainnet-beta", f"the fork copies {named}, not mainnet-beta: start it without --offline and without another --fork")
        squads = self.rpc("getAccountInfo", [str(SQUADS), {"encoding": "base64", "commitment": "confirmed"}])["value"]
        self.expect(bool(squads and squads["executable"]), f"the Squads program {SQUADS} is not on the fork")
        self.ok(f"the real Squads program {SQUADS} is there, executable (governance.mjs and scripts/deploy_v2.sh --localnet run against it)")
        mint = self.data(USDC_MINT)
        self.expect(mint is not None and len(mint) >= 82, f"the USDC mint {USDC_MINT} is not on the fork")
        supply, decimals, freeze = int.from_bytes(mint[36:44], "little"), mint[44], mint[46:50] == (1).to_bytes(4, "little")
        self.ok(f"the real USDC mint {USDC_MINT}: {decimals} decimals, supply {usdc(supply)}, " + ("with" if freeze else "without") + " a freeze authority (Circle's)")
        # a fork that has just started has no block, so no clock, until its first transaction: this is it
        self.airdrop(self.relayer.pubkey(), 20)
        self.ok(f"the relayer {self.relayer.pubkey()} (it pays every fee and relays every token) was given {self.lamports(self.relayer.pubkey()) / 1e9:g} SOL "
                f"by requestAirdrop; the fork's clock reads {day(self.started())}")

    def programs(self) -> None:
        self.step("the programs, at their pinned ids")
        for name, build in BUILDS.items():
            elf = (FIX / build).read_bytes()
            address = pay.IDS[name]
            deployed, _authority, have = mc.program_data(lambda a: (lambda d: None if d is None else ("", d))(self.data(Pubkey.from_string(a))), address)
            if not (deployed and mc.elf_hash(have) == mc.elf_hash(elf)):
                self.rpc("surfnet_writeProgram", [address, elf.hex(), 0])
            deployed, _authority, have = mc.program_data(lambda a: (lambda d: None if d is None else ("", d))(self.data(Pubkey.from_string(a))), address)
            self.expect(deployed and mc.elf_hash(have) == mc.elf_hash(elf), f"{name} {address} does not hold tests/fixtures/{build} after it was written")
            self.ok(f"{name} {address}: tests/fixtures/{build}, executable hash {mc.elf_hash(elf)[:16]}...")
        no = self.refusal([pay.init_faucet_ix(self.relayer.pubkey())])
        self.expect(no is not None and code_of(no) == 89, f"InitFaucet should be refused with error 89 on the real-money build, and was {self.said(no)}")
        self.ok("InitFaucet is refused (error 89): this build has no test-USDC faucet; money enters only as real USDC")

    def register_key(self) -> None:
        self.step("a signing key")
        n = self.github
        self.key = oidc.key_pda(oidc.GITHUB, n)
        if oidc.read_key(self.data(self.key)) is None:
            self.send([oidc.register_key_ix(self.relayer.pubkey(), oidc.GITHUB, n)])
        if oidc.read_key(self.data(self.key)).state == 0:
            self.send([oidc.key_params_ix(self.relayer.pubkey(), oidc.GITHUB, n)])
        key = oidc.read_key(self.data(self.key))
        usable, why = oidc.key_usable(key, self.now())
        self.expect(usable, f"the test key is registered but not usable: {why}")
        self.ok(f"the test key (account {self.key}) is registered with knos-oidc and usable now; it expires {day(key.expires_at)}")

    def wallet(self) -> None:
        self.step("a wallet with real USDC")
        self.funder = Keypair()
        self.airdrop(self.funder.pubkey(), 10)
        self.rpc("surfnet_setTokenAccount", [str(self.funder.pubkey()), str(USDC_MINT), {"amount": 1_000 * USDC, "state": "initialized"}])
        self.funder_tok = pay.ata(self.funder.pubkey(), USDC_MINT)
        self.expect(self.token_balance(self.funder_tok) == 1_000 * USDC, "surfnet_setTokenAccount did not give the wallet 1,000 USDC")
        self.ok(f"wallet {self.funder.pubkey()}: {self.lamports(self.funder.pubkey()) / 1e9:g} SOL, {usdc(self.token_balance(self.funder_tok))} "
                f"in {self.funder_tok} (the cheatcode surfnet_setTokenAccount, on the real mint)")
        self.payee_wallet = Keypair().pubkey()
        for owner, what in ((self.payee_wallet, "the payee's"), (pay.FEE_OWNER, "the fee owner's")):
            if self.data(pay.ata(owner, USDC_MINT)) is None:
                self.send([pay.create_ata_ix(self.relayer.pubkey(), owner, USDC_MINT)])
            self.ok(f"{what} USDC account {pay.ata(owner, USDC_MINT)} exists")
        self.fee_tok = pay.ata(pay.FEE_OWNER, USDC_MINT)
        self.fee0 = self.token_balance(self.fee_tok)

    def wallet_funding(self) -> None:
        self.step("wallet funding: the wallet funds a bounty with its own USDC")
        issue, amount = self.base, 20 * USDC
        before, vault0 = self.token_balance(self.funder_tok), self.token_balance(pay.vault_pda(USDC_MINT))
        ix = pay.fund_wallet_ix(self.funder.pubkey(), self.funder_tok, USDC_MINT, OWNER_REPO, issue, amount, WF_REPO, WF_SHA, TERMS, work_s=14 * DAY)
        sig = self.send([ix], self.funder)
        self.job_a = pay.job_pda(OWNER_REPO, issue, self.funder.pubkey())
        job = pay.read_job(self.data(self.job_a))
        self.expect(job is not None and job.state == "open" and job.amount == amount and job.mint == USDC_MINT, "the bounty is not an open job of 20 USDC")
        self.expect(before - self.token_balance(self.funder_tok) == amount and self.token_balance(pay.vault_pda(USDC_MINT)) - vault0 == amount,
                    "the 20 USDC did not move from the wallet into the vault")
        self.ok(f"job {self.job_a}: open, {usdc(job.amount)} for issue {issue} of repository {OWNER_REPO}, deadline {day(job.deadline)}")
        self.ok(f"the wallet holds {usdc(self.token_balance(self.funder_tok))}; the vault {pay.vault_pda(USDC_MINT)} holds {usdc(self.token_balance(pay.vault_pda(USDC_MINT)))}")
        for line in self.logs(sig):
            self.ok(f"the program logged: {line[:150]}")

    def balance(self) -> None:
        self.step("a Balance: the wallet sets money aside for a repository owner's bounties")
        self.send([pay.open_balance_ix(self.funder.pubkey(), OWNER, USDC_MINT, spenders=[MAINT])], self.funder)
        self.bal = pay.balance_pda(OWNER, self.funder.pubkey(), USDC_MINT)
        self.baltok = pay.baltok_pda(self.bal)
        put = Instruction(pay.TOKEN, bytes([12]) + (100 * USDC).to_bytes(8, "little") + bytes([6]),
                          [AccountMeta(self.funder_tok, False, True), AccountMeta(USDC_MINT, False, False), AccountMeta(self.baltok, False, True),
                           AccountMeta(self.funder.pubkey(), True, False)])
        self.send([put], self.funder)
        b = pay.read_balance(self.data(self.bal))
        self.expect(b is not None and b.owner_id == OWNER and b.authority == self.funder.pubkey() and b.mint == USDC_MINT and b.spenders == (MAINT,),
                    "the Balance is not the one that was opened")
        self.expect(self.token_balance(self.baltok) == 100 * USDC, "the Balance's token account does not hold the 100 USDC")
        self.ok(f"Balance {self.bal} of owner {OWNER}: opened by the wallet, spendable by comment from owner {OWNER} and maintainer {MAINT}")
        self.ok(f"it holds {usdc(self.token_balance(self.baltok))} (in {self.baltok}: anyone adds money with a plain transfer)")

    def bounty_by_comment(self) -> None:
        self.step("a bounty by comment: a GitHub-signed comment funds a job from the Balance")
        issue, amount, work = self.base + 1, 5 * USDC, 600
        before = self.token_balance(self.baltok)
        aud = pay.fund_audience(issue, amount, pay.MERGE, pay.terms_hash(TERMS), self.bal, work)
        t0 = time.monotonic()
        token = self.gh(aud, "fund.yml", event_name="issue_comment", actor_id=MAINT, repository_id=OWNER_REPO, repository_owner_id=OWNER)
        self.ok(f"the comment's token {token} is verified on chain by knos-oidc ({time.monotonic() - t0:.0f} s, written in pieces and stepped, "
                f"no program of ours trusts anything but that)")
        sig = self.send([pay.fund_balance_ix(self.relayer.pubkey(), token, self.key, self.bal, USDC_MINT, OWNER_REPO, issue, TERMS)])
        self.job_b = pay.job_pda(OWNER_REPO, issue, self.bal)
        job = pay.read_job(self.data(self.job_b))
        self.expect(job is not None and job.from_balance and job.amount == amount and job.funder_id == MAINT, "the comment did not fund an open job from the Balance")
        self.expect(before - self.token_balance(self.baltok) == amount, "the Balance did not pay the 5 USDC")
        self.ok(f"job {self.job_b}: open, {usdc(job.amount)} from the Balance, funded by GitHub user {job.funder_id}; deadline {day(job.deadline)} (work time {work} s)")
        self.ok(f"the Balance holds {usdc(self.token_balance(self.baltok))} now")
        for line in self.logs(sig):
            self.ok(f"the program logged: {line[:150]}")
        self.balance_after_fund = self.token_balance(self.baltok)

    def payment(self) -> None:
        self.step("a payment: a GitHub-signed proof pays the wallet-funded bounty")
        job = pay.read_job(self.data(self.job_a))
        aud = pay.pay_audience(job.repo_id, job.issue, self.payee, HEAD, job.terms, job.mode, self.payee_wallet)
        token = self.gh(aud, "prove.yml", repository_id=job.repo_id)
        self.ok(f"the proof's token {token} is verified on chain; it names GitHub user {self.payee} and the wallet {self.payee_wallet}")
        vault0 = self.token_balance(pay.vault_pda(USDC_MINT))
        ix = pay.pay_ix(self.relayer.pubkey(), token, self.key, self.job_a, job, self.payee, self.payee_wallet, used=pay.used_pda(self.jwt))
        if relay.version(self.ledger, self.relayer) < 1:      # 2.0 knows no single-use marker: its Pay takes one account fewer
            ix = Instruction(ix.program_id, bytes(ix.data), list(ix.accounts)[:-1])
        sig, rent = self.closing(self.job_a, job, [ix])
        fee, got = pay.fee_of(job.amount), self.token_balance(pay.ata(self.payee_wallet, USDC_MINT))
        self.expect(got == job.amount - fee, f"the payee holds {usdc(got)}, not {usdc(job.amount - fee)}")
        self.expect(self.token_balance(self.fee_tok) - self.fee0 == fee, "the fee account did not receive the fee")
        self.expect(vault0 - self.token_balance(pay.vault_pda(USDC_MINT)) == job.amount, "the vault did not release the job's money")
        self.ok(f"the payee's wallet received {usdc(got)} and the fee account {usdc(fee)} ({pay.FEE_BPS / 100:g}%); {rent}")
        record = pay.read_rep(self.data(pay.rep_pda(self.payee)))
        self.ok(f"GitHub user {self.payee}'s record: {record.paid} payment(s) in real money, {usdc(record.total)} in all")
        for line in self.logs(sig):
            self.ok(f"the program logged: {line[:150]}")

    def refund(self) -> None:
        self.step("a refund: no proof arrives, the deadline passes, the money goes back to the Balance")
        job = pay.read_job(self.data(self.job_b))
        early = self.refusal([pay.refund_ix(self.relayer.pubkey(), self.job_b, job)])
        self.expect(early is not None and code_of(early) == 83, f"a refund before the deadline should be refused with error 83, and was {self.said(early)}")
        self.ok(f"before the deadline ({day(job.deadline)}; the fork's clock reads {day(self.now())}) the refund is refused (error 83)")
        arrived = self.travel_to(job.deadline + 1)
        self.ok(f"surfnet_timeTravel: the fork's clock now reads {day(arrived)}, {arrived - job.deadline} s past the deadline")
        sig, rent = self.closing(self.job_b, job, [pay.refund_ix(self.relayer.pubkey(), self.job_b, job)])
        back = self.token_balance(self.baltok)
        self.expect(back == self.balance_after_fund + job.amount == 100 * USDC, f"the Balance holds {usdc(back)}, not {usdc(100 * USDC)}")
        self.ok(f"the Balance holds {usdc(back)} again; {rent}")
        for line in self.logs(sig):
            self.ok(f"the program logged: {line[:150]}")
        late = self.refusal([pay.refund_ix(self.relayer.pubkey(), self.job_b, job)])
        self.expect(late is not None, "a second refund of the same job went through")
        self.ok(f"the same refund again is {self.said(late)}: a job is paid or refunded once")

    def run(self) -> None:
        self.fork()
        self.programs()
        self.register_key()
        self.wallet()
        self.wallet_funding()
        self.balance()
        self.bounty_by_comment()
        self.payment()
        self.refund()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rpc", required=True, help="the Surfpool fork's RPC address")
    a = ap.parse_args(argv)
    started = time.monotonic()
    r = Rehearsal(a.rpc)
    try:
        r.run()
    except Failed as why:
        print(f"\nSTOPPED at step {r.n} of {STEPS}: {why}", file=sys.stderr)
        return 1
    except (chain.RpcError, OSError) as why:          # a refused connection, a timeout, an answer that is an error
        print(f"\nSTOPPED at step {r.n} of {STEPS}: {type(why).__name__}: {why} (the fork is at {a.rpc}: is it running?)", file=sys.stderr)
        return 1
    print(f"\nall {STEPS} steps passed in {time.monotonic() - started:.0f} s. This proves the escrow's money flows on mainnet's USDC and clock, "
          "with a test key playing GitHub and no key of GitHub's or ours involved; it does not prove GitHub's signatures "
          "(the released build trusts GitHub's keys only) or the guardian and upgrade multisigs (scripts/deploy_v2.sh --localnet and scripts/governance.mjs do).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
