"""The safety paths of the second deployment, run on the bytes the cluster runs.

    python scripts/drills.py [--rpc URL] [--tokens FILE] [--upgrade-log FILE] [--out docs/DRILLS.md] [--strict]

It reads both programs from the cluster (the ProgramData accounts of knos_oidc and knos_pay, through getAccountInfo),
prints the sha256 of each with its trailing zeros trimmed (the hash `solana-verify get-program-hash` prints), and loads
exactly those bytes into LiteSVM at their real ids. LiteSVM is a simulator in this process: the programs are the
deployed ones, the clock is one this script moves, and nothing here sends a transaction to a cluster.

The deployed build trusts GitHub's own signing keys and nothing else, so nothing in this script can sign a token it
would accept. The drills are therefore of two kinds.

  no token needed   a wallet's job is refunded only after its deadline; a held payment goes back to the funder after
                    180 days; a key expires 30 days after it was registered and verifies nothing from then on; the
                    guardian's pause ends by itself after 7 days; nobody but the guardian revokes a key; only GitHub's
                    four keys are taken without an attestation.
  --tokens FILE     real GitHub Actions tokens with the key set of their day (JSON Lines, the format
                    scripts/replay_tokens.py writes; the release run captures them from public knos-e2e comments):
                    a key is refreshed; a bounty is funded and paid; the same tokens again are refused; a token under
                    a revoked key is refused. The clock is set to each token's issue time.
  --upgrade-log FILE  the lines scripts/drill_upgrade.sh wrote (KNOS_DRILL_LOG) when it ran the upgrade drill against
                    a local validator with the real Squads program: an upgrade proposed, refused before 48 hours,
                    executed after them, and a cancelled one that never runs. This script does not run that drill; it
                    puts its rows in the table.

What is simulated, and how. The guardian is the vault of a Squads multisig: it has no private key and signs only by a
cross-program call from the Squads program. A drill that needs its signature turns LiteSVM's signature check off for
that one transaction and names the vault as a signer; the program under test sees the same signer flag either way.
Those rows say "authority simulated" (the real multisig's vote is scripts/drill_upgrade.sh and governance.mjs). A held
payment exists only after a GitHub-signed proof, so without tokens that drill funds a job through the program and then
writes the three fields Pay writes when it holds a job (state, payee, hold time) into the job's account; the refund
that follows is the deployed program's. That row says "held state written". Money is a 6-decimal SPL Token mint made
in the simulator, standing in for test USDC, except in the token drills, which use the program's own faucet mint.

A second table, "When a dependency fails", is of another kind (`DEPENDENCIES`): GitHub's API down for ten minutes, a
signing key expired on chain, the relay killed between a send and its confirmation, an RPC endpoint that errors, the
evidence of a payment missing, and devnet reset. Each needs tokens signed on demand, so these rows run the programs'
TEST builds (tests/fixtures/*.so, which trust a key this repository holds) in LiteSVM, with the fakes of GitHub and
of the RPC that the tests use (tests/), under a clock the drill moves. They say so. Each row: what was broken, what
the customer sees, how it recovers, and the recovery measured in simulated seconds. `--dependencies-only` runs these
alone, reads no cluster, and replaces that one section of --out.

Each drill prints one line: its name, what was checked, and pass or the exact error. The table goes to docs/DRILLS.md
with the program hashes and this command. Exit 1 when a row fails (with --strict, also when a row was not run).
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import functools
import hashlib
import io
import json
import re
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from solders.account import Account  # noqa: E402
from solders.compute_budget import set_compute_unit_limit  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.litesvm import LiteSVM  # noqa: E402
from solders.message import MessageV0  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.signature import Signature  # noqa: E402
from solders.system_program import CreateAccountParams, create_account  # noqa: E402
from solders.transaction import VersionedTransaction  # noqa: E402

from knos import chain  # noqa: E402
from knos import mainnet_check as mc  # noqa: E402
from knos.chain import said  # noqa: E402
from knos.settle.relay import claims_of, header_of  # noqa: E402
from knos.settle.v2 import oidc, pay, relay  # noqa: E402

PROGRAMS = ("knos_oidc", "knos_pay")
JWKS = ROOT / "tests" / "fixtures" / "github_jwks_2026-10-02.json"      # GitHub's key set on the day the genesis keys were pinned
GITLAB_JWKS = ROOT / "tests" / "fixtures" / "gitlab_jwks_2026-10-02.json"
UPGRADE_VAULT = Pubkey.from_string(pay.IDS["upgrade_authority"])
USDC, DAY = 1_000_000, 86_400
REPO, ISSUE = 1_000_000_007, 1                    # a repository id and an issue no real job has
WF_REPO, WF_SHA = "drexthealpha/Knos", "3bf54a1" + "0" * 33      # 40 hex characters; a job that is only refunded needs no real commit
TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge",
                        "paths": [], "reserve": 7, "v": 1})
KEYS, SIMULATED, WRITTEN, REAL = "keys made here", "authority simulated", "held state written", "real GitHub tokens"
VOTED = "the multisig's vote, local validator"
UPGRADE = ("an upgrade is proposed", "no upgrade before 48 hours", "an upgrade after 48 hours", "a cancelled upgrade never runs")   # scripts/drill_upgrade.sh's rows


class Failed(Exception):
    """What was not as it should be, in words: the row's result."""


class Skipped(Exception):
    """Why a drill was not run."""


def day(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def usdc(units: int) -> str:
    return f"{units / USDC:,.6f}".rstrip("0").rstrip(".")


def code_of(text: str) -> int | None:
    m = re.search(r"Custom\((\d+)\)|custom program error: 0x([0-9a-fA-F]+)", text)
    return None if not m else int(m.group(1)) if m.group(1) else int(m.group(2), 16)


# ---- the deployed bytes -------------------------------------------------------------------------------------------------
@dataclass
class Program:
    name: str
    address: str
    data: str               # its ProgramData account
    elf: bytes              # the bytes the cluster runs, with the padding the deploy left
    authority: str | None
    slot: int               # the slot of its last deployment

    @property
    def sha256(self) -> str:
        return mc.elf_hash(self.elf)


def fetch(rpc: str, call: Callable = chain.call) -> list[Program]:
    """Both programs as the cluster holds them. Stops with words when one is not there."""
    def account(address: str):
        v = call(rpc, "getAccountInfo", [address, {"encoding": "base64", "commitment": "confirmed"}], timeout=90)["value"]
        return (v["owner"], base64.b64decode(v["data"][0])) if v else None
    out = []
    for name in PROGRAMS:
        address = pay.IDS[name]
        program = account(address)
        home = str(mc.programdata_address(address))
        if not program or program[0] != str(mc.LOADER) or program[1][:4] != (2).to_bytes(4, "little") or str(Pubkey.from_bytes(program[1][4:36])) != home:
            raise SystemExit(f"stopped: {name} {address} is not an upgradeable program on {rpc}. Pass --rpc for the cluster it is deployed on.")
        deployed, authority, elf = mc.program_data(account, address)
        if not deployed:
            raise SystemExit(f"stopped: the ProgramData account {home} of {name} is not on {rpc}.")
        out.append(Program(name, address, home, elf, authority, int.from_bytes(account(home)[1][4:12], "little")))
    return out


# ---- the simulator --------------------------------------------------------------------------------------------------------
class Svm:
    """LiteSVM with the given program bytes at the real ids, and a clock. It also has the interface knos.settle.v2.relay
    asks of a ledger (send, send_all, simulate, account, infos, now, program_accounts, log_of), so the relay the public
    worker runs can carry a token here, and asks these bytes which escrow they are (2.0 or 2.1) as it asks a cluster."""
    def __init__(self, elfs: dict[str, bytes], now: int):
        self.svm = LiteSVM()
        # what the relay remembers a cluster's version under: these bytes, so another build in the same process is asked anew
        self.url = "litesvm:" + hashlib.sha256(elfs.get("knos_pay", b"")).hexdigest()[:16]
        for name in PROGRAMS:
            if name in elfs:        # a replay of tokens needs the verifier alone
                self.svm.add_program(Pubkey.from_string(pay.IDS[name]), elfs[name])
        c = self.svm.get_clock(); c.unix_timestamp = now; self.svm.set_clock(c)
        self.payer = self.wallet()
        self.logs: list[str] = []
        self.said: dict[Pubkey, list[list[str]]] = {}
        self.n = 0

    def wallet(self, sol: int = 100) -> Keypair:
        k = Keypair(); self.svm.airdrop(k.pubkey(), sol * 10 ** 9); return k

    def now(self) -> int:
        return int(self.svm.get_clock().unix_timestamp)

    def clock(self, t: int) -> None:
        c = self.svm.get_clock(); c.unix_timestamp = t; self.svm.set_clock(c)

    def send(self, ixs, payer: Keypair | None = None, signers=None, unsigned: bool = False) -> str:
        """Runs a transaction; RuntimeError with the runtime's own words when it fails. unsigned: the signature check
        is off for this one transaction, so every account an instruction marks as a signer counts as one (a multisig
        vault, which has no key)."""
        payer, ixs = payer or self.payer, list(ixs)
        msg = MessageV0.try_compile(payer.pubkey(), [set_compute_unit_limit(1_400_000), *ixs], [], self.svm.latest_blockhash())
        if unsigned:
            self.svm.with_sigverify(False)
            try:
                r = self.svm.send_transaction(VersionedTransaction.populate(msg, [Signature.default()] * msg.header.num_required_signatures))
            finally:
                self.svm.with_sigverify(True)
        else:
            r = self.svm.send_transaction(VersionedTransaction(msg, list({bytes(k.pubkey()): k for k in [payer, *(signers or ())]}.values())))
        self.svm.expire_blockhash()
        ok = "Failed" not in type(r).__name__
        self.logs = list((r if ok else r.meta()).logs())
        if not ok:
            raise RuntimeError(str(r.err()))
        self.n += 1
        for key in {payer.pubkey(), *(ix.program_id for ix in ixs), *(a.pubkey for ix in ixs for a in ix.accounts)}:
            self.said.setdefault(key, []).append(self.logs)
        return f"simulated{self.n}"

    def send_all(self, groups, payer, signers=None) -> list[str]:
        return [self.send(ixs, payer, signers) for ixs in groups]

    def simulate(self, ixs, payer: Keypair | None = None, signers=None) -> list[str]:
        """The log the transaction would leave, with nothing sent (as knos.chain.Ledger.simulate)."""
        payer = payer or self.payer
        msg = MessageV0.try_compile(payer.pubkey(), [set_compute_unit_limit(1_400_000), *ixs], [], self.svm.latest_blockhash())
        r = self.svm.simulate_transaction(VersionedTransaction(msg, list({bytes(k.pubkey()): k for k in [payer, *(signers or ())]}.values())))
        if "Failed" in type(r).__name__:
            raise chain.RpcError(f"transaction failed: {r.err()}", {"logs": list(r.meta().logs())})
        return list(r.meta().logs())

    @property
    def version(self) -> int:
        """1 when the escrow loaded here is 2.1, 0 for 2.0: what its own Version instruction answers."""
        return relay.version(self, self.payer)

    def account(self, address: Pubkey) -> bytes | None:
        a = self.svm.get_account(address)
        return bytes(a.data) if a is not None and a.lamports > 0 else None

    def infos(self, addresses):
        got = [self.svm.get_account(a) for a in addresses]
        return [(a.owner, bytes(a.data)) if a is not None and a.lamports > 0 else None for a in got]

    def program_accounts(self, program, size: int | None = None, memcmp: dict[int, bytes] | None = None):
        return [(addr, bytes(acc.data)) for addr, acc in self.svm.get_program_accounts(program)
                if acc.lamports > 0 and (size is None or len(acc.data) == size) and all(bytes(acc.data)[o:o + len(b)] == b for o, b in (memcmp or {}).items())]

    def log_of(self, address, marker: str, check=None, by=None) -> str | None:
        for logs in reversed(self.said.get(address, [])):
            for line in said(logs, by):
                if line.startswith(marker) and (check is None or check(line)):
                    return line
        return None

    # -- what a drill asks ------------------------------------------------------------------------------------------------
    def refusal(self, ixs, payer: Keypair | None = None, signers=None, unsigned: bool = False) -> str | None:
        """None when the transaction went through; else the runtime's words for why it did not."""
        try:
            self.send(ixs, payer, signers, unsigned)
        except RuntimeError as why:
            return str(why)
        return None

    def must(self, what: str, ixs, payer: Keypair | None = None, signers=None, unsigned: bool = False) -> None:
        why = self.refusal(ixs, payer, signers, unsigned)
        if why is not None:
            raise Failed(f"{what} was refused: {why}")

    def must_not(self, what: str, code: int, ixs, payer: Keypair | None = None, signers=None, unsigned: bool = False) -> None:
        why = self.refusal(ixs, payer, signers, unsigned)
        if why is None:
            raise Failed(f"{what} went through; it should be refused with error {code}")
        if code_of(why) != code:
            raise Failed(f"{what} was refused, but not with error {code}: {why}")

    def balance(self, token_account: Pubkey) -> int:
        d = self.account(token_account)
        return int.from_bytes(d[64:72], "little") if d and len(d) >= 165 else 0

    def mint(self) -> Pubkey:
        """A 6-decimal SPL Token mint whose mint authority is the payer: it stands in for test USDC."""
        m, me = Keypair(), self.payer.pubkey()
        self.send([create_account(CreateAccountParams(from_pubkey=me, to_pubkey=m.pubkey(), lamports=self.svm.minimum_balance_for_rent_exemption(82),
                                                      space=82, owner=pay.TOKEN)),
                   Instruction(pay.TOKEN, bytes([20, 6]) + bytes(me) + b"\x00", [AccountMeta(m.pubkey(), False, True)])], signers=[m])
        return m.pubkey()

    def funded(self, mint: Pubkey, amount: int) -> tuple[Keypair, Pubkey]:
        """A new wallet with SOL and `amount` of the mint in its associated token account."""
        k = self.wallet(10)
        t = pay.ata(k.pubkey(), mint)
        self.send([pay.create_ata_ix(self.payer.pubkey(), k.pubkey(), mint),
                   Instruction(pay.TOKEN, b"\x07" + amount.to_bytes(8, "little"),
                               [AccountMeta(mint, False, True), AccountMeta(t, False, True), AccountMeta(self.payer.pubkey(), True, False)])])
        return k, t

    def job(self, mint: Pubkey, amount: int = 20 * USDC, work_s: int = 14 * DAY, issue: int = ISSUE) -> tuple[Keypair, Pubkey, Pubkey, pay.Job]:
        """A wallet funds a job with its own money (FundWallet): (the wallet, its token account, the job's address, the job)."""
        funder, tok = self.funded(mint, amount)
        self.must("FundWallet", [pay.fund_wallet_ix(funder.pubkey(), tok, mint, REPO, issue, amount, WF_REPO, WF_SHA, TERMS, work_s=work_s)], funder)
        address = pay.job_pda(REPO, issue, funder.pubkey())
        j = pay.read_job(self.account(address))
        if j is None or j.state != "open" or j.amount != amount or self.balance(tok) != 0:
            raise Failed("FundWallet went through, but there is no open job holding the money")
        return funder, tok, address, j

    def register(self, issuer: int, n: int) -> str | None:
        """RegisterKey and KeyParams with no attestation, as anyone may send them: None, or why the program refused."""
        me = self.payer.pubkey()
        return self.refusal([oidc.register_key_ix(me, issuer, n)]) or self.refusal([oidc.key_params_ix(me, issuer, n)])

    def key(self, issuer: int, n: int) -> oidc.Key | None:
        return oidc.read_key(self.account(oidc.key_pda(issuer, n)))

    def verify(self, jwt: str, issuer: int, n: int, payer: Keypair | None = None) -> tuple[Pubkey, int, str | None]:
        """Writes the token and runs the verifier's steps, as a relay does: (the token account, how many steps went
        through, None or the words of the step that refused)."""
        p = payer or self.payer
        tid, plan = oidc.token_id(jwt), oidc.step_plan(n.bit_length())
        for ix in oidc.write_ixs(p.pubkey(), tid, jwt):
            self.must("Write", [ix], p)
        for i, squarings in enumerate(plan):
            why = self.refusal([oidc.step_ix(p.pubkey(), tid, oidc.key_pda(issuer, n), squarings)], p)
            if why is not None:
                return oidc.token_pda(p.pubkey(), tid), i, why
        return oidc.token_pda(p.pubkey(), tid), len(plan), None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unsigned_token(n: int, kid: str, now: int, tag: str) -> str:
    """A token in the shape GitHub gives one, which GitHub did not sign: its signature is a number below the key's
    modulus that follows from the token's text. The verifier does the whole RSA arithmetic on it and then refuses it."""
    head = _b64(json.dumps({"typ": "JWT", "alg": "RS256", "kid": kid}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"iss": oidc.ISSUERS[oidc.GITHUB], "aud": f"knos-drill:{tag}", "iat": now, "nbf": now - 300, "exp": now + 300,
                            "repository_id": str(REPO), "jti": tag}, separators=(",", ":")).encode())
    k = len(oidc.modulus_bytes(n))
    s = int.from_bytes(hashlib.shake_256(f"{head}.{body}".encode()).digest(k), "big") % n
    return f"{head}.{body}.{_b64(s.to_bytes(k, 'big'))}"


def used(svm: Svm, kid: str, n: int, tag: str) -> str | None:
    """Whether the verifier still works with this key: an unsigned token is stepped under it. None when the key was
    used (every step but the last went through, and the last refused the signature, error 70); else the words of the
    refusal that came first."""
    _account, steps, why = svm.verify(unsigned_token(n, kid, svm.now(), tag), oidc.GITHUB, n, svm.wallet(1))
    last = len(oidc.step_plan(n.bit_length())) - 1
    if why is None:
        raise Failed("a token GitHub did not sign was VERIFIED by the deployed verifier")
    return None if steps == last and code_of(why) == 70 else why


# ---- the captured tokens ----------------------------------------------------------------------------------------------
@dataclass
class Captured:
    """One line of a token file: a token as GitHub signed it, the issuer's key set on that day, and for a fund token
    the terms its audience carries the hash of."""
    jwt: str
    jwks: dict
    terms: bytes | None = None
    source: str = ""
    c: dict = field(default_factory=dict)       # its claims
    kid: str = ""

    @property
    def aud(self) -> str:
        return self.c["aud"] if isinstance(self.c.get("aud"), str) else (self.c.get("aud") or [""])[0]

    @property
    def kind(self) -> str | None:
        return relay.kind_of(self.aud)

    @property
    def iat(self) -> int:
        return int(self.c.get("iat", 0))

    @property
    def issuer(self) -> int | None:
        return next((i for i, url in oidc.ISSUERS.items() if self.c.get("iss") == url), None)

    @property
    def n(self) -> int | None:
        """The modulus of the key its header names, from the key set of its day."""
        return dict(oidc.jwks_keys(self.jwks)).get(self.kid)


def corpus(path: Path) -> list[Captured]:
    """The tokens of a JSON Lines file: {"token": ..., "jwks": {"keys": [...]}, "terms": "<json>" (fund tokens),
    "source": "<where it was read>"} per line. A line that is not that stops the run with its number."""
    out = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            jwt, jwks = row["token"].strip(), row["jwks"]
            terms = row.get("terms")
            out.append(Captured(jwt, jwks, terms.encode() if isinstance(terms, str) and terms else None, str(row.get("source", "")),
                                claims_of(jwt), str(header_of(jwt).get("kid", ""))))
            if not isinstance(jwks.get("keys"), list):
                raise ValueError("jwks has no keys")
        except (ValueError, LookupError, TypeError, AttributeError) as why:
            raise SystemExit(f"stopped: line {i} of {path} is not a captured token ({type(why).__name__}: {why}). "
                             'Each line is {"token": "...", "jwks": {"keys": [...]}}; python scripts/replay_tokens.py --capture writes them.') from None
    return out


# ---- the drills -------------------------------------------------------------------------------------------------------
def refund_after_deadline(new: Callable[[], Svm], _tokens) -> str:
    svm = new()
    mint = svm.mint()
    funder, tok, address, j = svm.job(mint, work_s=14 * DAY)
    anyone = svm.wallet(1)
    refund = [pay.refund_ix(anyone.pubkey(), address, j)]
    svm.must_not("a refund on the day of funding", 83, refund, anyone)
    svm.clock(j.deadline)
    svm.must_not("a refund in the deadline's own second", 83, refund, anyone)
    thief = svm.funded(mint, 0)[1]
    svm.clock(j.deadline + 1)
    svm.must_not("a refund to someone else's token account", 88, [pay.refund_ix(anyone.pubkey(), address, j, refund_token=thief)], anyone)
    svm.must("the refund one second after the deadline", refund, anyone)
    if svm.balance(tok) != j.amount or svm.account(address) is not None or svm.balance(pay.vault_pda(mint)) != 0:
        raise Failed(f"after the refund the wallet holds {usdc(svm.balance(tok))} of {usdc(j.amount)}, and the job is {'still there' if svm.account(address) else 'gone'}")
    if svm.refusal(refund, anyone) is None:
        raise Failed("the same job was refunded twice")
    return (f"a wallet funded {usdc(j.amount)} for 14 days; Refund sent by a stranger is refused on day 0 and in the deadline's own second "
            "(error 83) and to another token account (88); one second later it returns all of it to the funder and closes the job; a second refund finds no job")


def held_returns_after_180_days(new: Callable[[], Svm], _tokens) -> str:
    svm = new()
    mint = svm.mint()
    funder, tok, address, j = svm.job(mint, work_s=DAY)
    until, payee = svm.now() + pay.HOLD, 4_242
    a = svm.svm.get_account(address)
    d = bytearray(a.data)
    d[0] = 3; d[48:56] = until.to_bytes(8, "little", signed=True); d[56:64] = payee.to_bytes(8, "little")   # what Pay writes when it holds a job
    svm.svm.set_account(address, Account(a.lamports, bytes(d), a.owner, a.executable, a.rent_epoch))
    held = pay.read_job(svm.account(address))
    if held is None or held.state != "held" or held.hold_until != until:
        raise Failed("the job's account was written, and does not read as held")
    anyone = svm.wallet(1)
    refund = [pay.refund_ix(anyone.pubkey(), address, held)]
    svm.clock(j.deadline + 1)
    svm.must_not("a refund past the work deadline while the job is held", 83, refund, anyone)
    svm.clock(until)
    svm.must_not("a refund in the last second of the 180 days", 83, refund, anyone)
    svm.clock(until + 1)
    svm.must("the refund after 180 days", refund, anyone)
    if svm.balance(tok) != j.amount or svm.account(address) is not None:
        raise Failed(f"after the refund the funder holds {usdc(svm.balance(tok))} of {usdc(j.amount)}")
    return (f"a funded job of {usdc(j.amount)} marked held for a payee with no wallet; Refund is refused past the work deadline and in the "
            f"last second of the {pay.HOLD // DAY} days (error 83); one second later all of it is back with the funder and the job is closed")


def _genesis(svm: Svm) -> list[tuple[str, int]]:
    """GitHub's keys of 2 Oct 2026 that this build takes with no attestation, registered: [(kid, modulus)]."""
    keys = [(kid, n) for kid, n in oidc.jwks_keys(json.loads(JWKS.read_text(encoding="utf-8"))) if svm.register(oidc.GITHUB, n) is None]
    if not keys:
        raise Failed(f"the build took none of the keys of {JWKS.name} without an attestation")
    return keys


def genesis_keys_only(new: Callable[[], Svm], _tokens) -> str:
    svm = new()
    taken = _genesis(svm)
    hashes = {oidc.key_hash(n).hex() for _kid, n in taken}
    if hashes != relay.GENESIS:
        raise Failed(f"the build took {len(taken)} keys with no attestation, and they are not the four pinned ones: {sorted(hashes)}")
    kid, n = taken[0]
    if (again := svm.register(oidc.GITHUB, n)) is None or code_of(again) != 67:
        raise Failed(f"a key was registered a second time: {again}")
    refused = 0
    for _kid, m in oidc.jwks_keys(json.loads(GITLAB_JWKS.read_text(encoding="utf-8"))):
        for issuer in (oidc.GITLAB, oidc.GITHUB):
            svm.must_not("RegisterKey for one of GitLab's keys with no attestation", 73, [oidc.register_key_ix(svm.payer.pubkey(), issuer, m)])
            refused += 1
    svm.must_not("RegisterKey for one of GitHub's four keys under GitLab's name", 73, [oidc.register_key_ix(svm.payer.pubkey(), oidc.GITLAB, n)])
    return (f"RegisterKey with no attestation takes exactly the four GitHub keys pinned on 2 Oct 2026, each once (a second time: error 67); "
            f"GitLab's keys ({refused} tries) and a GitHub key under GitLab's name are refused (73)")


def key_expires_after_30_days(new: Callable[[], Svm], _tokens) -> str:
    svm = new()
    t0 = svm.now()
    kid, n = _genesis(svm)[0]
    key = svm.key(oidc.GITHUB, n)
    if key.expires_at != t0 + oidc.KEY_TTL:
        raise Failed(f"the key expires {day(key.expires_at)}, not 30 days after it was registered ({day(t0 + oidc.KEY_TTL)})")
    if (why := used(svm, kid, n, "day0")) is not None:
        raise Failed(f"the key did not verify on the day it was registered: {why}")
    svm.clock(key.expires_at - 1)
    if (why := used(svm, kid, n, "last")) is not None:
        raise Failed(f"the key did not verify in its last second: {why}")
    for t, name in ((key.expires_at, "at its expiry"), (key.expires_at + 365 * DAY, "a year later")):
        svm.clock(t)
        why = used(svm, kid, n, name)
        if why is None or code_of(why) != 77:
            raise Failed(f"{name} the key should be refused with error 77, and was {why or 'used'}")
    if svm.register(oidc.GITHUB, n) is None:
        raise Failed("an expired key was registered a second time for a new life")
    return (f"a genesis key registered at {day(t0)} expires exactly {oidc.KEY_TTL // DAY} days later; the verifier works with it on day 0 and "
            "in its last second (an unsigned token is stepped, then refused as not GitHub's, error 70); from its expiry on the first step is "
            "refused (77), a year later too, and it cannot be registered again")


def pause_lapses_after_7_days(new: Callable[[], Svm], _tokens) -> str:
    svm = new()
    mint, me = svm.mint(), svm.payer.pubkey()
    _f, _tok, early, j0 = svm.job(mint, work_s=pay.MIN_WORK, issue=ISSUE)
    stranger = svm.wallet(1)
    svm.must_not("Pause signed by a stranger", 97, [pay.pause_ix(stranger.pubkey(), stranger.pubkey(), 3600)], stranger)
    named = pay.pause_ix(pay.GUARDIAN, me, 3600)
    named = Instruction(named.program_id, named.data, [AccountMeta(pay.GUARDIAN, False, False), *named.accounts[1:]])
    svm.must_not("Pause that names the guardian without its signature", 97, [named])
    svm.must_not("Pause by another vault (the upgrade authority)", 97, [pay.pause_ix(UPGRADE_VAULT, me, 3600)], unsigned=True)
    svm.must_not("a pause of 7 days and one second", 81, [pay.pause_ix(pay.GUARDIAN, me, pay.PAUSE_MAX + 1)], unsigned=True)
    t0 = svm.now()
    svm.must("the guardian's pause of 7 days", [pay.pause_ix(pay.GUARDIAN, me, pay.PAUSE_MAX)], unsigned=True)
    until = pay.read_pause(svm.account(pay.pause_pda()))
    if until != t0 + pay.PAUSE_MAX:
        raise Failed(f"the pause ends {day(until)}, not 7 days after it was set")
    funder, tok = svm.funded(mint, 20 * USDC)
    fund = [pay.fund_wallet_ix(funder.pubkey(), tok, mint, REPO, ISSUE + 1, 20 * USDC, WF_REPO, WF_SHA, TERMS)]
    svm.must_not("FundWallet during the pause", 96, fund, funder)
    svm.clock(j0.deadline + 1)
    svm.must("a refund during the pause", [pay.refund_ix(me, early, j0)])
    svm.clock(until - 1)
    svm.must_not("FundWallet in the pause's last second", 96, fund, funder)
    svm.clock(until)
    svm.must("FundWallet once the 7 days are over", fund, funder)
    return ("Pause is refused from a stranger, from the guardian's address without its signature and from another vault (error 97), and for "
            "more than 7 days (81); the guardian's 7-day pause refuses FundWallet (96) to its last second while a refund still goes through; "
            "at 7 days funding works again with no further instruction")


def only_the_guardian_revokes(new: Callable[[], Svm], _tokens) -> str:
    svm = new()
    kid, n = _genesis(svm)[0]
    stranger = svm.wallet(1)
    svm.must_not("Revoke signed by a stranger", 79, [oidc.revoke_ix(stranger.pubkey(), oidc.GITHUB, n)], stranger)
    svm.must_not("Revoke that names the guardian without its signature", 79,
                 [Instruction(oidc.OIDC_ID, b"\x07", [AccountMeta(oidc.GUARDIAN, False, False), AccountMeta(oidc.key_pda(oidc.GITHUB, n), False, True)])])
    svm.must_not("Revoke by another vault (the upgrade authority)", 79, [oidc.revoke_ix(UPGRADE_VAULT, oidc.GITHUB, n)], unsigned=True)
    if svm.key(oidc.GITHUB, n).revoked or (why := used(svm, kid, n, "before")) is not None:
        raise Failed(f"the key stopped verifying after refused revocations: {why}")
    svm.must("the guardian's Revoke", [oidc.revoke_ix(oidc.GUARDIAN, oidc.GITHUB, n)], unsigned=True)
    if not svm.key(oidc.GITHUB, n).revoked:
        raise Failed("Revoke went through, and the key does not read as revoked")
    why = used(svm, kid, n, "after")
    if why is None or code_of(why) != 78:
        raise Failed(f"a revoked key should be refused with error 78, and was {why or 'used'}")
    svm.must_not("the guardian's Approve of a revoked key", 78, [oidc.approve_ix(oidc.GUARDIAN, oidc.GITHUB, n)], unsigned=True)
    if svm.register(oidc.GITHUB, n) is None:
        raise Failed("a revoked key was registered again")
    svm.clock(svm.now() + oidc.KEY_TTL + DAY)
    why = used(svm, kid, n, "later")
    if why is None or code_of(why) != 78:
        raise Failed(f"31 days later a revoked key should still be refused with error 78, and was {why or 'used'}")
    return ("Revoke is refused from a stranger, from the guardian's address without its signature and from another vault (error 79), and the "
            "key goes on verifying; the guardian's Revoke ends it: the first step is refused (78), Approve and RegisterKey do not bring it "
            "back, and 31 days later it is still refused as revoked")


# -- with real tokens -----------------------------------------------------------------------------------------------------
def _admitted(svm: Svm, t: Captured) -> int:
    """The modulus of the key that signed this token, registered on this chain as the build allows with no attestation."""
    if t.issuer != oidc.GITHUB or t.n is None:
        raise Failed(f"the token's key {t.kid[:16]!r} is not in the GitHub key set captured with it")
    if svm.key(oidc.GITHUB, t.n) is None and (why := svm.register(oidc.GITHUB, t.n)) is not None:
        raise Failed(f"the key that signed this token (sha256 {oidc.key_hash(t.n).hex()[:16]}...) is not one this build takes without an "
                     f"attestation ({why}); admitting it takes the rotate workflow's token and the guardian")
    return t.n


def _faucet_fund(tokens: list[Captured]) -> list[Captured]:
    """The fund tokens that came with their terms and spend the faucet's Balance of their repository's owner: the ones
    a chain with no Balance of real money on it can carry."""
    out = []
    for t in tokens:
        try:
            if t.kind == "fund" and t.terms and pay.named_balance(t.aud) == pay.faucet_balance_pda(int(t.c["repository_owner_id"])):
                out.append(t)
        except (ValueError, KeyError):
            continue
    return sorted(out, key=lambda t: t.iat)


def _pair(tokens: list[Captured]) -> tuple[Captured, Captured]:
    """A fund token and the pay token of the same bounty: same repository, issue, terms and mode, the proof issued later."""
    for f in _faucet_fund(tokens):
        fp = f.aud.split(":")
        for p in sorted((t for t in tokens if t.kind == "pay"), key=lambda t: t.iat):
            pp = p.aud.split(":")
            if len(pp) == 9 and (pp[2], pp[3], pp[6], pp[7]) == (str(f.c.get("repository_id")), fp[2], fp[5], fp[4]) and f.iat < p.iat < f.iat + int(fp[6]):
                return f, p
    raise Skipped("the token file has no fund token (with its terms, spending the faucet) and pay token of one bounty")


def _carry(svm: Svm, t: Captured) -> dict:
    """The token carried by the relay the public worker runs, with the chain's clock at the token's issue time."""
    svm.clock(max(svm.now(), t.iat))
    _admitted(svm, t)
    r = relay.submit(svm, svm.payer, t.jwt, t.terms, {oidc.GITHUB: t.jwks}, now=svm.now())
    if not r.get("ok"):
        raise Failed(f"the {t.kind} token of {t.c.get('repository')} was refused: {r.get('why')}")
    return r


def _paid(new: Callable[[int], Svm], tokens: list[Captured]) -> tuple[Svm, Captured, Captured, dict, dict, Pubkey, pay.Job]:
    f, p = _pair(tokens)
    svm = new(f.iat)
    svm.must("InitFaucet", [pay.init_faucet_ix(svm.payer.pubkey())])
    funded = _carry(svm, f)
    address = Pubkey.from_string(str(funded["job"]))
    j = pay.read_job(svm.account(address))
    if j is None or j.state != "open" or j.amount != int(funded["amount"]) or svm.balance(pay.vault_pda(j.mint)) != j.amount:
        raise Failed("the fund token was carried, and there is no open job holding its amount")
    paid = _carry(svm, p)
    return svm, f, p, funded, paid, address, j


def a_payment(new, tokens: list[Captured]) -> str:
    svm, f, p, _funded, paid, address, j = _paid(new, tokens)
    done = [x for x in paid.get("paid", []) if str(x.get("job")) == str(address)]
    if not done:
        raise Failed("the pay token was carried, and it did not pay the job its fund token made")
    fee, to = pay.fee_of(j.amount), done[0].get("to")
    if to is None:
        held = pay.read_job(svm.account(address))
        if held is None or held.state != "held" or held.payee_id != int(paid["payee_id"]) or svm.balance(pay.vault_pda(j.mint)) != j.amount:
            raise Failed("the proof names no wallet, and the job is not held for its payee with the money still in the vault")
        where = f"held for GitHub user {held.payee_id} until {day(held.hold_until)} (the proof names no wallet and none is bound here)"
    else:
        got, fees = svm.balance(pay.ata(Pubkey.from_string(str(to)), j.mint)), svm.balance(pay.ata(pay.FEE_OWNER, j.mint))
        if (got, fees) != (j.amount - fee, fee) or svm.account(address) is not None or svm.balance(pay.vault_pda(j.mint)) != 0:
            raise Failed(f"the payee holds {usdc(got)} and the fee account {usdc(fees)}; they should hold {usdc(j.amount - fee)} and {usdc(fee)}")
        where = f"{usdc(got)} to the wallet the proof names and {usdc(fees)} to the fee account; the job is closed and the vault empty"
    return (f"the fund token of {f.c.get('repository')} issue {j.issue} (issued {day(f.iat)}) opened a job of {usdc(j.amount)} test USDC from the "
            f"faucet; the pay token issued {day(p.iat)} was verified in {len(oidc.step_plan(p.n.bit_length()))} steps and paid it: {where}")


def a_replay_is_refused(new, tokens: list[Captured]) -> str:
    svm, f, p, _funded, paid, address, j = _paid(new, tokens)
    me, held = svm.payer.pubkey(), pay.read_job(svm.account(address))
    before = (svm.balance(pay.vault_pda(j.mint)), svm.balance(pay.ata(pay.FEE_OWNER, j.mint)))
    seen = []
    for t, name in ((p, "pay"), (f, "fund")):
        account, _steps, why = svm.verify(t.jwt, oidc.GITHUB, t.n)
        if why is not None:
            raise Failed(f"the {name} token did not verify a second time: {why}")
        key = oidc.key_pda(oidc.GITHUB, t.n)
        if name == "pay":
            wallet = pay.destination(pay.read_bind(svm.account(pay.bind_pda(int(paid["payee_id"])))), p.aud)
            ix = pay.pay_ix(me, account, key, address, held or j, int(paid["payee_id"]), wallet, used=pay.used_pda(p.jwt))
            if svm.version < 1:         # 2.0 knows no single-use marker: its Pay takes one account fewer
                ix = Instruction(ix.program_id, bytes(ix.data), list(ix.accounts)[:-1])
        else:
            ix = pay.fund_balance_ix(me, account, key, pay.named_balance(f.aud), j.mint, j.repo_id, j.issue, f.terms, used=f.jwt)
        why = svm.refusal([ix])
        if why is None:
            raise Failed(f"the {name} token worked a second time")
        seen.append(f"the {name} token again: error {code_of(why)}" if code_of(why) is not None else f"the {name} token again: {why}")
    if before != (svm.balance(pay.vault_pda(j.mint)), svm.balance(pay.ata(pay.FEE_OWNER, j.mint))):
        raise Failed("a refused replay moved money")
    return ("after the payment both tokens are verified again (the verifier keeps no memory) and sent to the escrow once more: "
            + "; ".join(seen) + "; no money moved")


def a_revoked_key_signs_nothing(new, tokens: list[Captured]) -> str:
    funds = _faucet_fund(tokens)
    if not funds:
        raise Skipped("the token file has no fund token that spends the faucet")
    t = funds[0]
    svm = new(t.iat)
    svm.must("InitFaucet", [pay.init_faucet_ix(svm.payer.pubkey())])
    n = _admitted(svm, t)
    account, _steps, why = svm.verify(t.jwt, oidc.GITHUB, n)
    if why is not None:
        raise Failed(f"the token did not verify before the revocation: {why}")
    key, me = oidc.key_pda(oidc.GITHUB, n), svm.payer.pubkey()
    svm.must("the guardian's Revoke", [oidc.revoke_ix(oidc.GUARDIAN, oidc.GITHUB, n)], unsigned=True)
    svm.must_not("FaucetOpen with a token verified before its key was revoked", 78,
                 [pay.faucet_open_ix(me, account, key, int(t.c["repository_owner_id"]), int(t.c["repository_id"]), used=t.jwt)])
    svm.must_not("FundBalance with a token verified before its key was revoked", 78,
                 [pay.faucet_open_ix(me, account, key, int(t.c["repository_owner_id"]), int(t.c["repository_id"]), used=t.jwt),
                  pay.fund_balance_ix(me, account, key, pay.named_balance(t.aud), pay.faucet_mint(), int(t.c["repository_id"]), int(t.aud.split(":")[2]), t.terms, used=t.jwt)])
    _again, steps, why = svm.verify(t.jwt, oidc.GITHUB, n, svm.wallet(5))
    if why is None or steps != 0 or code_of(why) != 78:
        raise Failed(f"a new verification under the revoked key should stop at its first step with error 78, and {why or 'went through'}")
    return (f"the fund token of {t.c.get('repository')} is verified; the guardian revokes the key that signed it; the escrow then refuses "
            "that verified token (error 78: no test USDC is minted, no job is funded) and the verifier refuses to verify it again (78)")


def a_key_is_refreshed(new, tokens: list[Captured]) -> str:
    for t in sorted((t for t in tokens if t.kind == "key"), key=lambda t: t.iat):
        parts = t.aud.split(":")
        named = next((n for _kid, n in oidc.jwks_keys(t.jwks) if len(parts) == 4 and parts[2] == str(oidc.GITHUB) and oidc.key_hash(n).hex() == parts[3]), None)
        if named is not None:
            break
    else:
        raise Skipped("the token file has no rotate-workflow token (audience knos-oidc:key:0:...) that names a GitHub key of its key set")
    t0 = t.iat - 10 * DAY
    svm = new(t0)
    for n in {named, _admitted(svm, t)}:
        if svm.key(oidc.GITHUB, n) is None and (why := svm.register(oidc.GITHUB, n)) is not None:
            raise Failed(f"the key the token names is not one this build takes without an attestation ({why})")
    svm.clock(t.iat)
    account, _steps, why = svm.verify(t.jwt, oidc.GITHUB, t.n)
    if why is not None:
        raise Failed(f"the rotate workflow's token did not verify: {why}")
    # 2.1 also asks for the key that verified the attestation, usable now; 2.0 does not read past the attestation
    refresh = [oidc.refresh_ix(svm.payer.pubkey(), oidc.GITHUB, named, account, oidc.key_pda(oidc.GITHUB, t.n))]
    before = svm.key(oidc.GITHUB, named).expires_at
    svm.must("Refresh", refresh)
    after = svm.key(oidc.GITHUB, named).expires_at
    if (before, after) != (t0 + oidc.KEY_TTL, t.iat + oidc.KEY_TTL):
        raise Failed(f"Refresh moved the key's expiry from {day(before)} to {day(after)}, not to 30 days after the attestation ({day(t.iat + oidc.KEY_TTL)})")
    svm.clock(int(t.c["exp"]) + oidc.LATE)
    svm.must_not("Refresh with the same token an hour after it expired", 75, refresh)
    return (f"a key registered {day(t0)} would expire {day(before)}; the rotate workflow's token issued {day(t.iat)} "
            f"({t.c.get('repository')}) is verified and Refresh moves the expiry to {day(after)}; the same token an hour past its own expiry is refused (75)")


DRILLS: list[tuple[str, str, bool, Callable]] = [       # (name, how its signatures come about, needs tokens, the drill)
    ("refund only after the deadline", KEYS, False, refund_after_deadline),
    ("a held payment returns after 180 days", WRITTEN, False, held_returns_after_180_days),
    ("only GitHub's four keys without an attestation", KEYS, False, genesis_keys_only),
    ("a key expires after 30 days", KEYS, False, key_expires_after_30_days),
    ("the guardian's pause lapses after 7 days", SIMULATED, False, pause_lapses_after_7_days),
    ("nobody but the guardian revokes", SIMULATED, False, only_the_guardian_revokes),
    ("a key is refreshed", REAL, True, a_key_is_refreshed),
    ("a payment", REAL, True, a_payment),
    ("a replay is refused", REAL, True, a_replay_is_refused),
    ("a token under a revoked key is refused", REAL + "; " + SIMULATED, True, a_revoked_key_signs_nothing),
]


@dataclass
class Row:
    name: str
    how: str
    checked: str
    result: str         # "pass", "FAIL: <the exact error>", or "not run: <why>"


def run(elfs: dict[str, bytes], now: int, tokens: list[Captured] | None = None, say: Callable[[str], None] = print) -> list[Row]:
    rows = []
    for name, how, needs_tokens, drill in DRILLS:
        if needs_tokens and tokens is None:
            row = Row(name, how, "", "not run: it needs real GitHub tokens (--tokens FILE); the deployed build trusts GitHub's keys only")
        else:
            try:
                row = Row(name, how, drill((lambda t=now: Svm(elfs, t)), tokens), "pass")
            except Skipped as why:
                row = Row(name, how, "", f"not run: {why}")
            except Failed as why:
                row = Row(name, how, "", f"FAIL: {why}")
            except Exception as why:  # noqa: BLE001 - a drill that broke is a row that failed, with the exact error
                row = Row(name, how, "", f"FAIL: {type(why).__name__}: {why}")
        say(f"{row.name} [{row.how}]: {row.checked + ': ' if row.checked else ''}{row.result}")
        rows.append(row)
    return rows


def upgrade_rows(log: Path | None, say: Callable[[str], None] = print) -> list[Row]:
    """The rows of the upgrade drill, from the log scripts/drill_upgrade.sh wrote: one line per step, tab separated
    (name, what was checked, pass). A step with no line was not run; a line that is not one of the steps stops the run."""
    seen: dict[str, tuple[str, str]] = {}
    for i, line in enumerate(log.read_text(encoding="utf-8").splitlines() if log else [], 1):
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] not in UPGRADE:
            raise SystemExit(f"stopped: line {i} of {log} is not a line scripts/drill_upgrade.sh writes (a step's name, what was checked, pass; tab separated).")
        seen[parts[0]] = (parts[1], parts[2] if parts[2] == "pass" else f"FAIL: {parts[2]}")
    why = (f"{log} has no line for it: scripts/drill_upgrade.sh stopped before it" if log else
           "bash scripts/drill_upgrade.sh runs it against a local validator (KNOS_DRILL_LOG=FILE), and --upgrade-log FILE puts it here")
    rows = [Row(name, VOTED, *seen.get(name, ("", f"not run: {why}"))) for name in UPGRADE]
    for row in rows:
        say(f"{row.name} [{row.how}]: {row.checked + ': ' if row.checked else ''}{row.result}")
    return rows


# ---- when a dependency fails ---------------------------------------------------------------------------------------------
# On the programs' test builds, with the fakes the tests use: nothing but GitHub can sign a token the deployed build
# takes, and these drills need a token for every step. Time is the simulator's: a drill moves the chain's clock and
# hands the same time to the relay, so "recovered in N s" is N simulated seconds, not this machine's.
HEADING = "## When a dependency fails"
EVERY = 3           # seconds between two passes of the relay, as worker.yml runs it


@dataclass
class Outage:
    name: str
    broken: str         # what was broken
    sees: str           # what the customer sees
    recovers: str       # how it recovers
    seconds: str        # measured recovery, in simulated seconds
    result: str = "pass"


def _harness() -> None:
    """The tests' harness on the import path. Skipped when this script is run without the repository's tests/."""
    tests = ROOT / "tests"
    if not (tests / "_pay2.py").is_file():
        raise Skipped("tests/ is not beside this script: these drills use its LiteSVM harness and its fakes")
    if str(tests) not in sys.path:
        sys.path.insert(0, str(tests))


@contextlib.contextmanager
def _relaying(repos: str = "octo/widgets"):
    """A chain of the test builds with the faucet open, a fake GitHub behind the worker's reader, and notes of its
    own: (chain, ledger, GitHub, the notes' file, GitHub's test key set). Everything patched is put back."""
    _harness()
    try:
        import test_worker as tw
        from _pay2 import Chain
        from test_relay2 import JWKS, Net
    except ImportError as why:
        raise Skipped(f"the tests' harness could not be imported ({why}): pip install -e '.[dev]'") from None
    from knos.proof import ghrelay
    from knos.settle import relay as first

    class GitHub(tw.GitHub):
        out = False                 # the whole API answers 502

        def _route(self, method, path, data):
            return (502, None) if self.out else super()._route(method, path, data)

    c = Chain()
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    gh = GitHub()
    gh.issues[ghrelay.HOME_REPO] = [{"number": 1, "state": "open", "labels": [ghrelay.LOG_LABEL]}]
    with tempfile.TemporaryDirectory() as home:
        notes = Path(home) / "ghrelay.json"
        kept = (ghrelay._HUB, ghrelay._LOG, ghrelay._state_path, first.fetch_jwks, relay._KEPT, dict(os.environ))
        ghrelay._HUB, ghrelay._LOG, ghrelay._state_path = ghrelay.Hub(gh.open, clock=c.now), {}, lambda: notes
        first.fetch_jwks, relay._KEPT = (lambda issuer: JWKS[issuer]), {}
        os.environ.update(KNOS_RELAY_REPOS=repos, KNOS_NO_SAS="1")
        os.environ.pop("GITHUB_RUN_ID", None)
        try:
            yield c, Net(c), gh, notes, JWKS
        finally:
            ghrelay._HUB, ghrelay._LOG, ghrelay._state_path, first.fetch_jwks, relay._KEPT = kept[:5]
            os.environ.clear()
            os.environ.update(kept[5])


def _funded(c, net, gh, n: int, count: int = 1) -> list[tuple[int, int, int, Pubkey]]:
    """`count` bounties funded by comment, each in a repository of its own (the faucet serves one once a minute), and
    carried by one pass: [(repository id, issue, payee id, the payee's wallet)]."""
    from test_relay2 import TERMS as terms, faucet_jwt, user
    from knos.proof import ghrelay
    out = []
    for i in range(count):
        org, repo, payee, wallet = user(), user(), user(), Keypair().pubkey()
        gh.comment("octo/widgets", n + i, ghrelay.token_comment("fund", faucet_jwt(c, n + i, org, repo), terms), at=c.now())
        out.append((repo, n + i, payee, wallet))
    lines = ghrelay.once(net, c.payer, now=c.now(), crank=False)
    if sum(" ok sig=" in ln for ln in lines) != count:
        raise Failed(f"the fundings were not all carried: {lines}")
    return out


def _proof(c, gh, job: tuple[int, int, int, Pubkey], pull: int) -> str:
    from test_relay2 import pay_jwt
    from knos.proof import ghrelay
    repo, n, payee, wallet = job
    jwt = pay_jwt(c, repo, n, payee, wallet)
    gh.comment("octo/widgets", pull, ghrelay.token_comment("proof", jwt), at=c.now())
    return jwt


def _got(c, wallet: Pubkey) -> int:
    account = pay.ata(wallet, pay.faucet_mint())
    return c.balance(account) if c.data(account) is not None else 0


def _passes(c, net, seconds: int, until: Callable[[list[str]], bool] = lambda lines: False) -> tuple[int, list[str]]:
    """Passes of the relay every EVERY seconds of the chain's clock, for `seconds` or until `until(lines of the pass)`:
    (the seconds that went by, every line logged)."""
    from knos.proof import ghrelay
    began, said = c.now(), []
    while c.now() - began < seconds:
        c.warp(EVERY)
        lines = ghrelay.once(net, c.payer, now=c.now(), crank=False)
        said += lines
        if until(lines):
            break
    return c.now() - began, said


def github_down_ten_minutes() -> Outage:
    """GitHub's API answers nothing for 600 s while three proofs wait in comments."""
    from knos.proof import ghrelay
    net_of = 4_875_000
    with _relaying() as (c, net, gh, notes, _jwks):
        jobs = _funded(c, net, gh, 21, 3)
        c.warp(120)
        gh.out = True
        proofs = [_proof(c, gh, job, 40 + i) for i, job in enumerate(jobs)]       # merged just as the API went away
        posted = c.now()
        down, said = _passes(c, net, 600)
        if said or any(_got(c, w) for *_x, w in jobs):
            raise Failed(f"something moved while GitHub was down: {said}")
        gh.out = False
        took, said = _passes(c, net, 60, until=lambda lines: bool(lines))
        if [_got(c, w) for *_x, w in jobs] != [net_of] * 3 or len(said) != 3 or not all(any(f" {ghrelay.token_id(p)} ok sig=" in ln for ln in said) for p in proofs):
            raise Failed(f"not every proof was paid once GitHub answered: {said}")
        txs = net.txs
        _extra, again = _passes(c, net, 30)
        if again or net.txs != txs or [_got(c, w) for *_x, w in jobs] != [net_of] * 3:
            raise Failed(f"a token was carried twice: {again}")
        waited = c.now() - 30 - posted
    return Outage("GitHub's API is down for ten minutes",
                  f"every request the relay made to GitHub answered 502 for {down} s; three merged pull requests had their proof tokens posted just before",
                  "the pull request is merged and no payment comment appears; `knos bounty` still shows the money in escrow",
                  f"nothing to do. The relay asks again every {EVERY} s; a token is good for an hour past its expiry, so an outage under an hour "
                  "loses none. Longer than that: run the workflow again (`/knos settle`) for a fresh token",
                  f"all 3 paid on the first pass after GitHub answered, {took} s later ({waited} s after their comments); none paid twice in the passes that followed")


def signing_key_expired_on_chain() -> Outage:
    """The key GitHub signs with is past its 30 days in the verifier; a stranger's Refresh brings it back."""
    _harness()
    try:
        from _oidc2 import attest_claims
        from _pay2 import Chain
        from _settle import modulus, sign_jwt
        from test_relay2 import JWKS, TERMS as terms, Net, faucet_jwt, pay_jwt, user
    except ImportError as why:
        raise Skipped(f"the tests' harness could not be imported ({why}): pip install -e '.[dev]'") from None
    kept, os.environ["KNOS_NO_SAS"] = os.environ.get("KNOS_NO_SAS"), "1"
    try:
        c = Chain()
        net = Net(c)
        assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
        newer = c.second_key()                              # GitHub publishes several keys: this one is a day younger
        expires = oidc.read_key(c.data(c.key)).expires_at
        c.warp(expires - c.now() - 240)
        org, repo, payee, wallet = user(), user(), user(), Keypair().pubkey()
        r = relay.submit(net, c.payer, faucet_jwt(c, 31, org, repo), terms, JWKS, now=c.now())
        if not r.get("ok"):
            raise Failed(f"the funding was refused: {r.get('why')}")
        c.warp(expires - c.now() + 1)                       # the key's 30 days are over
        proof = pay_jwt(c, repo, 31, payee, wallet)
        txs = net.txs
        r = relay.submit(net, c.payer, proof, None, JWKS, now=c.now())
        if r.get("ok") or _got(c, wallet):
            raise Failed("a token under an expired key was paid")
        why, free = str(r.get("why")), net.txs == txs
        c.warp(120)
        anyone = c.fund()                                   # a key that is nobody's in particular
        c._n += 1
        claims = attest_claims(oidc.GITHUB, c.github, iat=c.now(), nbf=c.now() - 600, exp=c.now() + 300, jti=f"drill{c._n}")
        named = c.verify(sign_jwt(newer, claims), oidc.GITHUB, modulus(newer), anyone)
        if named is None or not c.send([oidc.refresh_ix(anyone.pubkey(), oidc.GITHUB, c.github, named, c.key_of(named))], anyone):
            raise Failed(f"a stranger's refresh was refused: {c.err}")
        r = relay.submit(net, c.payer, proof, None, JWKS, now=c.now())
        if not r.get("ok") or _got(c, wallet) != 4_875_000:
            raise Failed(f"the same proof was not paid after the refresh: {r.get('why')}")
        took = c.now() - expires
    finally:
        os.environ.pop("KNOS_NO_SAS") if kept is None else os.environ.__setitem__("KNOS_NO_SAS", kept)
    return Outage("GitHub's signing key has expired on chain",
                  "the verifier's 30 days for the key GitHub signs with ran out (no refresh landed); a second key of GitHub's was still good",
                  f"a merged pull request is not paid, and the relay's log says why before any fee is spent ({'no transaction was sent' if free else 'after a transaction that failed'}): {why}",
                  "anyone refreshes the key: a run of the pinned rotate workflow in which GitHub names the key, verified under a key that is "
                  "still good, then `Refresh` (drills_recovery.md, case C). The proof that was refused is then paid; nothing is signed again",
                  f"paid {took} s after the key expired: the refresh was sent 120 s in, by a key that holds nothing, and the same token paid on the next send")


def relay_killed_mid_token() -> Outage:
    """The relay's process ends after its transactions landed and before it wrote down or logged anything."""
    from knos.proof import ghrelay
    with _relaying() as (c, net, gh, notes, _jwks):
        [job] = _funded(c, net, gh, 41)
        c.warp(60)
        proof = _proof(c, gh, job, 50)
        real = ghrelay.relay_one

        def killed(*a, **kw):
            real(*a, **kw)
            raise KeyboardInterrupt("the runner was stopped")      # after the chain took it, before the relay heard so
        ghrelay.relay_one = killed
        try:
            c.warp(EVERY)
            ghrelay.once(net, c.payer, now=c.now(), crank=False)
            raise Failed("the relay was not killed")
        except KeyboardInterrupt:
            pass
        finally:
            ghrelay.relay_one = real
        died = c.now()
        entry = next(iter(json.loads(notes.read_text(encoding="utf-8"))["journal"].values()), {}) if notes.is_file() else {}
        mid = [e for e in json.loads(notes.read_text(encoding="utf-8"))["journal"].values() if e.get("id") == ghrelay.token_id(proof)]
        if not mid or mid[0].get("state") != "sending" or _got(c, job[3]) != 4_875_000:
            raise Failed(f"the notes do not show the token in flight, or the chain did not take it: {entry}")
        took, said = _passes(c, net, 30, until=lambda lines: bool(lines))
        if len(said) != 1 or f" {ghrelay.token_id(proof)} ok " not in said[0] or _got(c, job[3]) != 4_875_000:
            raise Failed(f"the token was not answered once after the restart: {said}")
        _extra, again = _passes(c, net, 15)
        if again or _got(c, job[3]) != 4_875_000:
            raise Failed(f"the token was carried again: {again}")
    return Outage("the relay is killed between a send and its confirmation",
                  "the relay's process ended after the paying transaction landed and before it noted or logged anything (its notes said the token was being sent)",
                  "the money arrives; the payment comment is late by one pass of the relay",
                  "nothing to do. The token was written to the relay's notes before it was sent, so the next pass (or the next run) sends it "
                  "again; the chain's single-use marker answers that it is done, nothing moves twice, and the log gets its line",
                  f"answered {c.now() - 15 - died} s after the kill ({took} s of passes); the payee holds 4.875 once, after two sends of the same token")


def rpc_errors_and_stale_blockhashes() -> Outage:
    """Every transaction the relay sends fails for a minute: the endpoint does not answer, or says the blockhash is stale."""
    from knos.proof import ghrelay
    with _relaying() as (c, net, gh, notes, _jwks):
        [job] = _funded(c, net, gh, 51)
        c.warp(60)
        proof = _proof(c, gh, job, 60)
        began, bad = c.now(), 60

        class Flaky:
            """The ledger, whose sends fail while the endpoint is bad: in turn an error of the connection and Solana's
            own "Blockhash not found". Reads answer, as they did on devnet when sends were dropped."""
            failed = 0

            def __getattr__(self, name):
                return getattr(net, name)

            def _fail(self):
                Flaky.failed += 1
                raise OSError("the RPC endpoint closed the connection") if Flaky.failed % 2 else chain.RpcError("Transaction simulation failed: Blockhash not found")

            def send(self, ixs, payer, signers=None, v1=False):
                return self._fail() if c.now() - began < bad else net.send(ixs, payer, signers, v1)

            def send_all(self, groups, payer, signers=None, v1=False):
                return self._fail() if c.now() - began < bad else net.send_all(groups, payer, signers, v1)
        flaky = Flaky()
        tried, said = [], []
        while c.now() - began < 300 and not said:
            c.warp(EVERY)
            before = Flaky.failed
            said = ghrelay.once(flaky, c.payer, now=c.now(), crank=False)
            if Flaky.failed != before or said:
                tried.append(c.now() - began)
        if len(said) != 1 or f" {ghrelay.token_id(proof)} ok " not in said[0] or _got(c, job[3]) != 4_875_000:
            raise Failed(f"the token was not paid once the endpoint answered: {said}")
        if any(" fail " in ln for ln in gh.log()):
            raise Failed("a failure of the endpoint was logged as a verdict on the token")
        tries = int(re.search(r" tries=(\d+) ", said[0]).group(1))
        _extra, again = _passes(c, net, 15)
        if again or _got(c, job[3]) != 4_875_000:
            raise Failed(f"the token was carried again: {again}")
    return Outage("the RPC endpoint errors and returns stale blockhashes",
                  f"for {bad} s every transaction the relay sent failed: a closed connection, or \"Blockhash not found\"; reads still answered",
                  "the payment comment is late; nothing says \"failed\", because the failure says nothing about the token",
                  "nothing to do. The relay tries the token again on its next pass, then after 10, 20, ... 60 s, and every 60 s from then "
                  "while the chain would still take it; a failure of the endpoint never ends a token",
                  f"paid {tried[-1] - bad} s after the endpoint answered again, on try {tries} (tries at {', '.join(str(t) for t in tried)} s); paid once")


def evidence_missing() -> Outage:
    """A required check run of the merged commit is gone from GitHub: nothing is signed, so nothing can be paid."""
    _harness()
    try:
        import test_flow as tf
        from _flow import check
    except ImportError as why:
        raise Skipped(f"the tests' harness could not be imported ({why}): pip install -e '.[dev]'") from None
    from knos import flow
    with tempfile.TemporaryDirectory() as tmp:
        w = tf.bounty(Path(tmp))
        w.chain.bind(tf.MONA)
        head = w.hub.pulls[12]["head"]["sha"]
        w.hub.checks[head] = [check("build")]                   # `test` ran and passed; its check run was deleted
        t0 = w.clock()
        code = flow.settle(w.run(w.hub.merge(12)))
        said = w.hub.knos(12)[-1]
        if code != 0 or w.signer.asked or len(w.chain.jobs(7)) != 1 or "- `test`: did not run on this commit" not in said or not said.startswith("Knos: not paid."):
            raise Failed(f"a payment without its evidence was not refused with the reason: {said!r}")
        refused = round(w.clock() - t0)
        w.hub.checks[head] = [check("build"), check("test")]    # the check is run again on the same commit, and passes
        t1 = w.clock()
        code = flow.settle(w.run(w.hub.commented(12, tf.EVE, "/knos settle")))
        paid = w.hub.knos(12)[-1]
        if code != 0 or not paid.startswith("Knos: paid.") or len(w.signer.asked) != 1:
            raise Failed(f"the payment did not follow once the evidence was back: {paid!r}")
        took = round(w.clock() - t1)
    return Outage("the evidence is missing (a required check run was deleted)",
                  "the bounty's terms require the checks `build` and `test` at the merged commit; GitHub no longer lists `test` there",
                  "one comment on the pull request: \"Knos: not paid.\", each required check with what GitHub shows (`test`: did not run on this "
                  "commit), and what to do. No token is signed, so no relay and no program is asked to pay",
                  "run the check again on that commit and comment `/knos settle` (anyone may); or a maintainer pays with `/knos tip`. "
                  "Otherwise the money goes back to the funder at the deadline",
                  f"refused by the job the merge started, after {refused} s of waiting (a check that is absent is not waited for); paid {took} s after `/knos settle`, "
                  "once the check was back")


def devnet_reset() -> Outage:
    """The cluster forgets everything. What was paid before is still provable from the bundle and the receipt mirror."""
    _harness()
    try:
        import test_bundle as tb
    except ImportError as why:
        raise Skipped(f"the tests' harness could not be imported ({why}): pip install -e '.[dev]'") from None
    from knos import bundle, receipt
    net = tb.Chain()
    r, files = bundle.gather(net.call, net.events(), tb.ORDER, tb.host())
    blob = bundle.make(files, r["order"])
    with tempfile.TemporaryDirectory() as tmp:
        mirror = Path(tmp) / "receipts"
        receipt.mirror_write([r], mirror)                       # what `knos receipt mirror` writes while the chain has the record
        net.reset = True
        try:
            bundle.gather(net.call, net.events(), tb.ORDER, tb.host())
            raise Failed("the reset chain still gave the order")
        except bundle.Unavailable:
            pass
        receipt.mirror_write([], mirror)                        # a mirror run after the reset finds nothing, and keeps what it has
        held = receipt.mirror_find(str(mirror), tb.ORDER)
        got, done = bundle.verify(blob, mirror=str(mirror))     # no cluster is asked
        if held != [r] or got != r or receipt.check(r) is not None:
            raise Failed("the receipt or the bundle did not verify from the mirror after the reset")
    return Outage("devnet is reset",
                  "the cluster lost every account: the programs, every order and Balance, every binding and signing key, and the test USDC itself",
                  "`knos status` says the programs are not deployed; open orders are gone and cannot be refunded (it was test USDC from a faucet); "
                  "explorer links to old transactions stop working",
                  "what was accepted and paid stays provable: `knos bundle verify FILE --mirror DIR` and `knos receipt verify ORDER --mirror DIR` "
                  "check the saved bundle and the mirrored receipt with no cluster. A funder waits until `knos status` passes again, then funds "
                  "anew (drills_recovery.md, case A)",
                  f"0 s for the record: {len(done)} checks of the bundle and the mirror's receipt passed with the chain gone. The orders are not "
                  "recovered: redeploying is by hand and was not timed")


DEPENDENCIES: list[tuple[str, Callable[[], Outage]]] = [
    ("GitHub's API is down for ten minutes", github_down_ten_minutes),
    ("GitHub's signing key has expired on chain", signing_key_expired_on_chain),
    ("the relay is killed between a send and its confirmation", relay_killed_mid_token),
    ("the RPC endpoint errors and returns stale blockhashes", rpc_errors_and_stale_blockhashes),
    ("the evidence is missing (a required check run was deleted)", evidence_missing),
    ("devnet is reset", devnet_reset),
]


@functools.lru_cache(maxsize=1)
def _dependencies() -> tuple[Outage, ...]:
    out = []
    for name, drill in DEPENDENCIES:
        try:
            with contextlib.redirect_stdout(io.StringIO()):     # the relay and the job print their own lines: the row says what matters
                out.append(drill())
        except Skipped as why:
            out.append(Outage(name, "", "", "", "", f"not run: {why}"))
        except Failed as why:
            out.append(Outage(name, "", "", "", "", f"FAIL: {why}"))
        except Exception as why:  # noqa: BLE001 - a drill that broke is a row that failed, with the exact error
            out.append(Outage(name, "", "", "", "", f"FAIL: {type(why).__name__}: {why}"))
    return tuple(out)


def dependency_rows(say: Callable[[str], None] = print) -> list[Outage]:
    """The rows of "When a dependency fails": run once in a process (they are the same every time: the harness's
    clock and keys are fixed)."""
    rows = list(_dependencies())
    for r in rows:
        say(f"when {r.name}: {r.seconds + ': ' if r.seconds else ''}{r.result}")
    return rows


def dependency_section(rows: list[Outage]) -> str:
    cell = lambda s: s.replace("|", "\\|").replace("\n", " ")  # noqa: E731
    fixtures = ROOT / "tests" / "fixtures"
    builds = [f"`{name}` `{mc.elf_hash((fixtures / f'{name}_v2_test.so').read_bytes())}`" for name in PROGRAMS if (fixtures / f"{name}_v2_test.so").is_file()]
    lines = [HEADING, "",
             "These rows are of another kind than the ones above. Each breaks one thing Knos depends on and follows a payment through it. "
             "They need a token signed for every step, and nothing but GitHub can sign one the deployed programs take, so they run the "
             "programs' test builds (" + ("; ".join(builds) or "tests/fixtures") + ": the same source built with a key this repository holds) "
             "in LiteSVM, with the relay's own code and the fakes of GitHub and of the RPC endpoint that the tests use. Seconds are the "
             "simulator's: the drill moves the clock, and the relay makes a pass every " + f"{EVERY} s as the public worker does. No cluster and "
             "no GitHub is touched, and none of these failures has been rehearsed on devnet.", "",
             f"{sum(r.result == 'pass' for r in rows)} of {len(rows)} rows passed, {sum(r.result.startswith('FAIL') for r in rows)} failed, "
             f"{sum(r.result.startswith('not run') for r in rows)} were not run.", "",
             "| Failure | What was broken | What the customer sees | How it recovers | Measured recovery, simulated seconds | Result |", "|---|---|---|---|---|---|"]
    lines += [f"| {cell(r.name)} | {cell(r.broken)} | {cell(r.sees)} | {cell(r.recovers)} | {cell(r.seconds)} | {cell(r.result)} |" for r in rows]
    lines += ["", "These rows alone, with no cluster: `python scripts/drills.py --dependencies-only` (it rewrites this section, and appends the hand-written half of the page anew). "
              "What each means for someone who is waiting for a payment is at the end of this page."]
    return "\n".join(lines) + "\n"


def with_dependencies(doc: str, section: str) -> str:
    """`doc` with its dependency section replaced by `section` (put before "## Reproduce" when it has none)."""
    start = doc.find(HEADING)
    end = doc.find("\n## ", start + 1) + 1 if start >= 0 else doc.find("## Reproduce")
    if end <= 0:
        return doc.rstrip("\n") + "\n\n" + section
    return doc[:start if start >= 0 else end] + section + "\n" + doc[end:]


def document(programs: list[Program], rows: list[Row], rpc: str, cluster: str, now: int, tokens: str | None, n_tokens: int, upgrade_log: str | None = None) -> str:
    cell = lambda s: s.replace("|", "\\|").replace("\n", " ")  # noqa: E731
    ran = [r for r in rows if not r.result.startswith("not run")]
    lines = ["# Drills on the deployed programs", "",
             f"Written by `scripts/drills.py` on {day(now)}. Do not edit: run the command at the end.", "",
             "Each row is a safety path of the second deployment, run on the bytes the cluster runs. The script reads both programs from "
             f"{cluster} with `getAccountInfo`, loads exactly those bytes into LiteSVM (a simulator inside the script's process) at their real "
             "ids, and moves the simulator's clock. No transaction is sent to a cluster, so a row is a log of the deployed code, not a "
             "transaction a block explorer can show. The last four rows are the upgrade drill, which this script does not run: "
             "`scripts/drill_upgrade.sh` runs it against a validator on the machine it is run on, with the real Squads program.", "",
             f"{sum(r.result == 'pass' for r in rows)} of {len(rows)} rows passed, {sum(r.result.startswith('FAIL') for r in rows)} failed, "
             f"{len(rows) - len(ran)} were not run.", "",
             "## The programs", "",
             "| Program | Address | ProgramData account | sha256, trailing zeros trimmed | Upgrade authority | Deployed in slot |", "|---|---|---|---|---|---|"]
    lines += [f"| `{p.name}` | `{p.address}` | `{p.data}` | `{p.sha256}` | `{p.authority or 'none'}` | {p.slot} |" for p in programs]
    lines += ["", "The hash is the one `solana-verify get-program-hash` prints, and the one [ASSURANCE.md](ASSURANCE.md) says how to compare "
              "with a build of this repository's source.", "",
              "## The drills", "", "| Drill | Signatures | What was checked | Result |", "|---|---|---|---|"]
    lines += [f"| {cell(r.name)} | {cell(r.how)} | {cell(r.checked)} | {cell(r.result)} |" for r in rows]
    lines += ["", "## What the second column means", "",
              f"- **{KEYS}**: every signature is a real one, by a key the script made. These drills use only instructions that anyone may send.",
              f"- **{SIMULATED}**: the guardian (`{pay.IDS['guardian']}`) is the vault of a Squads multisig. It has no private key: on a cluster "
              "it signs only by a cross-program call from the Squads program, after the members' vote. The script turns the simulator's "
              "signature check off for that one transaction and names the vault as a signer. The program under test sees the same signer "
              "flag either way; the multisig's vote is not exercised here (`scripts/drill_upgrade.sh` and `scripts/governance.mjs` do that "
              "against the real Squads program). The same switch is used to show that another vault, signing, is refused.",
              f"- **{WRITTEN}**: a job is held only after a GitHub-signed proof for a payee with no wallet. Without a token the script funds a "
              "job through the program and writes the three fields `Pay` writes when it holds one (state, payee, hold time) into the job's "
              "account. The refusals and the refund are the deployed program's.",
              f"- **{REAL}**: tokens GitHub signed, read from a file with GitHub's key set of their day, carried by the same relay code the "
              "public worker runs, with the simulator's clock at each token's issue time. "
              + (f"This run read {n_tokens} tokens from `{tokens}`." if tokens else
                 "This run was given no token file, so these rows were not run: the deployed build trusts GitHub's keys only, and nothing "
                 "but GitHub can sign a token it accepts."), "",
              f"- **{VOTED}**: `scripts/drill_upgrade.sh`, on a validator on the machine it is run on, which holds the real Squads program and "
              "both multisigs. The upgrade is proposed, approved, executed and cancelled by member keys through the Squads program, with "
              "`scripts/governance.mjs`; the validator's clock is moved 48 hours. The first of these rows says what that validator held: "
              "with `--from-devnet`, devnet's bytes of both programs and both multisig accounts, each member's key replaced by a key made "
              "for the drill (the members' real keys are not used). "
              + (f"This run read those rows from `{upgrade_log}`." if upgrade_log else "This run was given no log of it, so these rows were not run."), "",
              "Money in the rows without tokens is a 6-decimal SPL Token mint made in the simulator, standing in for test USDC. The rows "
              "with tokens use the program's own faucet mint.", "",
              "## Reproduce", "", "```", "pip install -e '.[dev]'",
              *(["npm ci --prefix scripts", f"KNOS_DRILL_LOG={upgrade_log} bash scripts/drill_upgrade.sh --from-devnet"] if upgrade_log else []),
              f"python scripts/drills.py --rpc {rpc}" + (f" --tokens {tokens}" if tokens else "") + (f" --upgrade-log {upgrade_log}" if upgrade_log else ""), "```", "",
              "The script exits 1 when a row fails. With `--strict` it also exits 1 when a row was not run.", ""]
    return "\n".join(lines)


def recovery() -> str:
    """The hand-written half of the page, what a funder does in three failures: docs/drills_recovery.md, appended as it is."""
    path = ROOT / "docs" / "drills_recovery.md"
    return "\n" + path.read_text(encoding="utf-8") if path.is_file() else ""


def main(argv: list[str] | None = None, call: Callable = chain.call, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rpc", default="https://api.devnet.solana.com", help="the cluster the programs are read from")
    ap.add_argument("--tokens", type=Path, help="real GitHub tokens with the key set of their day, JSON Lines (scripts/replay_tokens.py --capture)")
    ap.add_argument("--upgrade-log", type=Path, help="the lines scripts/drill_upgrade.sh wrote (KNOS_DRILL_LOG): its rows go in the table")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "DRILLS.md")
    ap.add_argument("--now", type=int, help="the simulator's clock at the start of a drill without tokens (default: this machine's)")
    ap.add_argument("--strict", action="store_true", help="exit 1 also when a row was not run")
    ap.add_argument("--dependencies-only", action="store_true", help="run only the rows of \"When a dependency fails\" and replace that section of --out; no cluster is read")
    a = ap.parse_args(argv)
    if a.dependencies_only:
        outages = dependency_rows(say)
        doc, tail = a.out.read_text(encoding="utf-8"), recovery()
        cut = doc.find(tail.lstrip("\n").split("\n", 1)[0]) if tail else -1      # the hand-written half begins at its own first heading: it is appended anew
        a.out.write_text(with_dependencies(doc[:cut].rstrip("\n") + "\n" if cut > 0 else doc, dependency_section(outages)) + (tail if cut > 0 else ""), encoding="utf-8")
        bad = [r for r in outages if r.result != "pass"]
        say(f"{len(outages) - len(bad)} of {len(outages)} dependency rows passed; the section is in {a.out}")
        return 1 if [r for r in bad if r.result.startswith("FAIL")] or (a.strict and bad) else 0
    cluster = mc.GENESIS.get(call(a.rpc, "getGenesisHash", []), "a cluster of its own")
    programs = fetch(a.rpc, call)
    for p in programs:
        say(f"{p.name} {p.address} on {cluster}: {len(p.elf)} bytes in {p.data}, sha256 with trailing zeros trimmed {p.sha256}")
    tokens = corpus(a.tokens) if a.tokens else None
    now = a.now if a.now is not None else int(time.time())
    rows = run({p.name: p.elf for p in programs}, now, tokens, say) + upgrade_rows(a.upgrade_log, say)
    outages = dependency_rows(say)
    doc = document(programs, rows, a.rpc, cluster, now, str(a.tokens) if a.tokens else None, len(tokens or []), str(a.upgrade_log) if a.upgrade_log else None)
    a.out.write_text(with_dependencies(doc, dependency_section(outages)) + recovery(), encoding="utf-8")
    failed, skipped = [r for r in rows if r.result.startswith("FAIL")], [r for r in rows if r.result.startswith("not run")]
    broke, left = [r for r in outages if r.result.startswith("FAIL")], [r for r in outages if r.result.startswith("not run")]
    say(f"when a dependency fails: {len(outages) - len(broke) - len(left)} passed, {len(broke)} failed, {len(left)} not run")
    say(f"{len(rows) - len(failed) - len(skipped)} passed, {len(failed)} failed, {len(skipped)} not run; the table is in {a.out}")
    return 1 if failed or broke or (a.strict and (skipped or left)) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (chain.RpcError, TimeoutError, OSError) as why:
        print(f"stopped: the cluster did not answer ({why}). Run the same command again.", file=sys.stderr)
        raise SystemExit(1) from None
