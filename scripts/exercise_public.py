"""From "staging" to "public": what the 2.1 and 1.1 builds add, run once at the PUBLIC program ids, and written down.

    python scripts/exercise_public.py status --rpc URL
    python scripts/exercise_public.py run --rpc URL --keys DIR [--only CAPABILITY] [--resume] [--again ROUND --since TIME]
    python scripts/exercise_public.py record --keys DIR --rpc URL
    python scripts/exercise_public.py propose-oidc --rpc URL --keys DIR --so-dir DIR
    python scripts/exercise_public.py run --simulate --out FILE          the same rounds on a local simulator
    python scripts/exercise_public.py record --simulate --evidence FILE --root COPY

status   hashes the executable of each of the four public programs the way docs/PROVENANCE.md does (sha256 of the
         program data with its trailing zeros stripped) and says, per program: the build it runs, the proposal that
         build belongs to, and the slot of its last deployment. Exit 0: all four run the 2.1 / 1.1 builds (or a later
         build this repository names). Exit 3: an upgrade has not executed yet: skip the exercises and ship the rest;
         nothing here waits. Exit 1: anything else (a hash nobody recorded, a cluster that does not answer).

run      for every capability of docs/capabilities.json below `exercised` that has a round here, runs the round in
         test USDC with the smallest amounts the programs take, and keeps what it sent and what it checked in
         <keys>/exercise_public.json. A round is a list of steps, and a step that is done is never done again: run it as
         often as needed. A step that needs a token a forge signs (a workflow run) looks for it among the tokens the
         repository's workflows posted; when there is none it prints which workflow to start, writes
         "needs run: <workflow>" and goes on to the next round. `--resume` reads the repository's comments again. A
         refusal is evidence of its own: the transaction is sent without preflight so that it lands and fails on chain,
         and its error number is held to the program's source.

record   writes that evidence into the repository: docs/capabilities.json (a capability moves to `exercised` only with
         a transaction that succeeded at a public program id; `on_chain` moves only for a program whose hash on chain
         is the proposal's build), docs/provenance.json (the slot each build went live), web/upgrades.json (read again
         from the multisig by scripts/upgrade_feed.py when --rpc is given; a proposal stays `executed` there only when
         the program ran its build), then docs/CAPABILITIES.md, web/demo_data.json and docs/PROVENANCE.md through their
         own scripts. Evidence of a simulated run is refused for the repository
         itself: it is written only into a copy (`--root`), which is how the tests run this command.

propose-oidc   after proposals 3 to 6 have executed: takes the knos_oidc build in --so-dir, holds it to the record the
         upgrade gate keeps on chain for its hash (the verified build), writes that build into docs/provenance.json
         (`next`), checks that the plan is exactly [knos_oidc] (any other program whose bytes differ from what is live
         stops it with nothing sent), then calls scripts/deploy_v2.sh --propose and prints the proposal and the time
         from which it can be executed.

The rounds use the code a relay runs (knos.settle.v2.relay.submit, verify_only) and the instruction builders of
knos.settle.v2.pay; in the simulator the tokens are signed by the test key the test builds trust (tests/_settle.py)
and the chain is tests/_order.py and tests/_meter.py.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from knos import chain  # noqa: E402
from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import gate, meter, oidc, order_auto, pay, relay  # noqa: E402

PROGRAMS = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")
PROPOSALS = {"knos_oidc": 3, "knos_pay": 4, "knos_meter": 5, "knos_passkey": 6}       # the upgrades approved in 0.3.14
NEW = {"knos_oidc": "2.1", "knos_pay": "2.1", "knos_meter": "1.1", "knos_passkey": "1.1"}
OLD = {"knos_oidc": "2.0", "knos_pay": "2.0", "knos_meter": "1.0", "knos_passkey": "1.0"}
EVIDENCE = "exercise_public.json"
USDC = 1_000_000
AMOUNT = pay.ORDER_MIN_AMOUNT           # 5.00: the least an order takes
REPOSITORY = "drexthealpha/knos-e2e"    # where the rounds' comments are posted (override: <keys>/exercise.json "repository")
BEGIN, END = "<!-- public-round:start -->", "<!-- public-round:end -->"
_SIG = re.compile(r"[1-9A-HJ-NP-Za-km-z]{86,88}")


class Need(Exception):
    """A step needs a token only a forge signs: `workflow` is the one to start, `how` what to do, exactly."""
    def __init__(self, workflow: str, how: str):
        super().__init__(f"needs run: {workflow}")
        self.workflow, self.how = workflow, how


class Wait(Exception):
    """A step waits for the chain's clock."""
    def __init__(self, until: int, what: str):
        super().__init__(f"waiting until {day(until)}: {what}")
        self.until = until


class Skip(Exception):
    """A round that cannot run now, and why."""


class Failed(Exception):
    """What was not as it should be, in words."""


T = TypeVar("T")


def have(x: T | None, what: str = "an account this step reads") -> T:
    """`x`, which must be there."""
    if x is None:
        raise Failed(f"{what} is not there")
    return x


def day(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def money(units: int) -> str:
    return f"{units / USDC:,.2f}"


def code_of(text: object) -> int | None:
    """A program's error number, as a cluster or the simulator words it."""
    s = str(text)
    m = re.search(r"custom program error: 0x([0-9a-fA-F]+)", s)
    if m:
        return int(m.group(1), 16)
    m = re.search(r"Custom\((\d+)\)|['\"]Custom['\"]: (\d+)", s)
    return int(m.group(1) or m.group(2)) if m else None


def program_error(name: str, root: Path = ROOT) -> tuple[int, str]:
    """An error of knos_pay by its constant, read from the program's source: (number, the words after it)."""
    src = (root / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    m = re.search(rf"pub const {name}: u32 = (\d+);\s*//\s*(.+)", src)
    if not m:
        raise Failed(f"programs-v2/knos_pay/src/lib.rs no longer defines {name}")
    return int(m.group(1)), m.group(2).strip()


def single_use(root: Path = ROOT) -> tuple[int, str]:
    """The single-use rule's error: its number and the short words the source ends its comment with."""
    number, words = program_error("E_REPLAY", root)
    return number, words.rsplit(": ", 1)[-1]


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _write(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="")


# ---- status ----------------------------------------------------------------------------------------------------------
def read_programs(account: Callable, root: Path = ROOT) -> dict[str, dict]:
    """What each public program runs, held to what this repository records. `account(address)` returns (owner, data)
    or None, as knos.mainnet_check._rpc gives it. Per program: id, hash, slot (of its last deployment), build (the
    version, or None), proposal, and `is`: "new" (the 2.1 / 1.1 build), "next" (a later build docs/provenance.json
    names), "old" (the build read before the upgrade) or "unknown"."""
    ids = _json(root / "programs-v2" / "program_ids.json")
    entries = (_json(root / "web" / "upgrades.json") or {}).get("entries", [])
    seen = _json(root / "docs" / "provenance.json") or {}
    out = {}
    for name in PROGRAMS:
        got = account(str(mc.programdata_address(ids[name])))
        row: dict = {"id": ids[name], "hash": None, "slot": None, "build": None, "proposal": None, "is": "unknown"}
        if got and len(got[1]) > mc.PROGRAMDATA_HEADER and got[1][:4] == (3).to_bytes(4, "little"):
            row["hash"] = gate.executable_hash(got[1][mc.PROGRAMDATA_HEADER:]).hex()
            row["slot"] = int.from_bytes(got[1][4:12], "little")
        mine = [e for e in entries if e.get("program") == name and e.get("build_hash") == row["hash"] and e.get("status") in ("pending", "executed")]
        nxt = (seen.get("next") or {}).get(name) or {}
        before = (seen.get("programs") or {}).get(name) or {}
        if row["hash"] is None:
            pass
        elif mine and int(mine[0]["index"]) == PROPOSALS[name]:
            row.update(build=NEW[name], proposal=PROPOSALS[name], **{"is": "new"})
        elif nxt.get("build_hash") == row["hash"]:
            row.update(build=str(nxt.get("version") or "?"), proposal=nxt.get("proposal"), **{"is": "next"})
        elif before.get("on_chain_hash") == row["hash"] and before.get("proposal_status") != "Executed":
            row.update(build=OLD[name], **{"is": "old"})
        out[name] = row
    return out


def status_code(rows: dict[str, dict]) -> int:
    kinds = {r["is"] for r in rows.values()}
    return 1 if "unknown" in kinds else 3 if "old" in kinds else 0


def status(url: str, say: Callable[[str], None] = print, account: Callable | None = None, root: Path = ROOT) -> int:
    try:
        rows = read_programs(account or mc._rpc(url), root)
    except Exception as why:  # noqa: BLE001 - a cluster that does not answer is not an answer
        say(f"stopped: {url} could not be read ({type(why).__name__}: {why})")
        return 1
    for name, r in rows.items():
        what = {"new": f"{name} {r['build']}, the build of proposal {r['proposal']}",
                "next": f"{name} {r['build']}, the later build docs/provenance.json names" + (f" (proposal {r['proposal']})" if r["proposal"] else ""),
                "old": f"{name} {r['build']}: proposal {PROPOSALS[name]} has not executed",
                "unknown": "a build no file of this repository records" if r["hash"] else "nothing: no program data at this id"}[r["is"]]
        say(f"{name} {r['id']}: runs {what}; hash {r['hash']}; last deployed in slot {r['slot']}")
    code = status_code(rows)
    say({0: "all four run the upgraded builds: run the exercises",
         3: "the upgrade has not executed for every program: skip the exercises and ship the rest; run them later (exit 3)",
         1: "unexpected: nothing is exercised or recorded until this is understood (exit 1)"}[code])
    return code


# ---- the two worlds ---------------------------------------------------------------------------------------------------
class Tok:
    """One signed token: the JWT, its claims, its audience, and the terms posted beside it."""
    def __init__(self, jwt: str, terms: str | None = None, source: str = ""):
        self.jwt, self.terms, self.source = jwt.strip(), terms, source
        self.c = relay.claims_of(self.jwt)
        aud = self.c.get("aud")
        self.aud = str(aud if isinstance(aud, str) else (aud or [""])[0])
        self.kind = relay.kind_of(self.aud)

    def held(self) -> dict:
        return {"jwt": self.jwt, "terms": self.terms, "source": self.source}


class World:
    mode = "public"
    ledger: Any
    relayer: Keypair
    jwks: dict | None = None
    repository = REPOSITORY
    mint: Pubkey
    funder: Any             # the wallet of the round that needs no token, and its token account
    funder_token: Any

    def pin(self) -> tuple[str, str, int]:     # pragma: no cover - overridden
        raise NotImplementedError

    def now(self) -> int:
        return int(self.ledger.now())

    def clock(self) -> float | None:        # what a relay is told the time is: the chain's in the simulator
        return None

    def account(self, address: Pubkey) -> bytes | None:
        return self.ledger.account(address)

    def tokens(self, account: Pubkey) -> int:
        d = self.account(account)
        return int.from_bytes(d[64:72], "little") if d and len(d) >= 165 else 0

    def submit(self, tok: Tok, payer: Keypair | None = None) -> dict:
        return relay.submit(self.ledger, payer or self.relayer, tok.jwt, tok.terms.encode() if tok.terms else None, self.jwks, now=self.clock())

    def verified(self, tok: Tok) -> tuple[Pubkey, Pubkey, list[str]]:
        """The token verified into its account by knos_oidc and left there: (the account, its key's account, the transactions)."""
        r = relay.verify_only(self.ledger, self.relayer, tok.jwt, self.jwks, now=self.clock())
        if not r.get("ok"):
            raise Failed(f"the verifier did not take the token again: {r.get('why')}")
        at = Pubkey.from_string(r["account"])
        return at, have(oidc.read_token(self.account(at)), "the verified token").key, list(r.get("sigs", []))

    def send(self, ixs, payer: Keypair | None = None, signers=None) -> str:
        return self.ledger.send(list(ixs), payer or self.relayer, signers)

    def refused(self, ixs, payer: Keypair | None = None) -> tuple[str, int | None]:     # pragma: no cover - overridden
        raise NotImplementedError

    def wait_until(self, t: int, what: str) -> None:    # pragma: no cover - overridden
        raise NotImplementedError

    def find(self, kind: str, pick: Callable[[Tok], bool], forge: Callable[[], Tok] | None, taken: set[str]) -> Tok | None:     # pragma: no cover
        raise NotImplementedError


class Public(World):
    """Devnet, at the pinned program ids, with the keys of a folder: relayer.json pays the fees; funder.json is a
    wallet that holds test USDC (Circle's devnet mint) for the round that needs no token."""

    def __init__(self, url: str, keys: Path, say: Callable[[str], None] = print, since: str | None = None):
        if mc._cluster(url) == "mainnet-beta":
            raise SystemExit("refused: this is mainnet-beta. The exercises run on devnet, in test USDC.")
        self.url, self.keys, self.say = url, keys, say
        self.ledger = chain.Ledger(url)
        self.relayer = chain.wallet(keys / "relayer.json")
        self.cfg = _json(keys / "exercise.json") or {}
        self.repository = self.cfg.get("repository", REPOSITORY)
        self.mint = Pubkey.from_string(self.cfg.get("mint", str(pay.USDC_DEVNET)))
        # only tokens issued since then are taken (default: three days back): a round started over takes new comments
        self.since = since or self.cfg.get("since") or datetime.fromtimestamp(time.time() - 3 * 86_400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._rows: list[Tok] | None = None
        self._funder: Keypair | None = None

    @property
    def funder(self) -> Keypair:
        if self._funder is None:
            if not (self.keys / "funder.json").is_file():
                raise Skip(f"{self.keys / 'funder.json'} is missing: a wallet holding 10 test USDC ({self.mint}) funds this round")
            self._funder = chain.wallet(self.keys / "funder.json")
        return self._funder

    @property
    def funder_token(self) -> Pubkey:
        return pay.ata(self.funder.pubkey(), self.mint)

    def pin(self) -> tuple[str, str, int]:
        """The workflows a wallet's order pins, and the repository it is for: what .github/workflows/knos.yml calls."""
        m = re.search(r"uses: ([\w.-]+/[\w.-]+)/\.github/workflows/prove\.yml@([0-9a-f]{40})", (ROOT / ".github" / "workflows" / "knos.yml").read_text(encoding="utf-8"))
        if not m:
            raise Skip(".github/workflows/knos.yml names no pinned prove.yml")
        repo_id = self.cfg.get("repository_id") or oidc.IDS["attest_repo_ids"][0]
        return m.group(1), m.group(2), int(repo_id)

    def refused(self, ixs, payer: Keypair | None = None) -> tuple[str, int | None]:
        """Sends a transaction the program is expected to refuse, WITHOUT preflight, so that the refusal is a
        transaction on chain: (its signature, the program's error number). Raises if it went through."""
        payer = payer or self.relayer
        raw = base64.b64encode(bytes(chain.sign(list(ixs), payer, None, self.ledger._blockhash()))).decode()
        sig = chain.call(self.url, "sendTransaction", [raw, {"encoding": "base64", "skipPreflight": True, "maxRetries": 5}])
        try:
            chain.wait(self.url, sig, 90.0)
        except chain.RpcError as why:
            return sig, code_of(f"{why} {why.data}")
        raise Failed(f"the transaction {sig} was expected to be refused and it went through")

    def wait_until(self, t: int, what: str) -> None:
        left = t - self.now()
        if left > 150:
            raise Wait(t, what)
        while self.now() <= t:
            time.sleep(5)

    def rows(self) -> list[Tok]:
        """Every token the round's repository posted in the last days, and those of <keys>/tokens.jsonl: oldest first."""
        if self._rows is None:
            import replay_tokens
            found: list[dict] = []
            kept = self.keys / "tokens.jsonl"
            if kept.is_file():
                found += [json.loads(line) for line in kept.read_text(encoding="utf-8").splitlines() if line.strip()]
            try:
                new = replay_tokens.capture(self.repository, self.since, say=self.say)
                replay_tokens.append(kept, new)
                found += new
            except Exception as why:  # noqa: BLE001 - GitHub did not answer: the kept tokens are what there is
                self.say(f"{self.repository}: its comments could not be read ({type(why).__name__}: {why}); using {kept.name} alone")
            once = {r["token"]: r for r in found}
            floor = datetime.strptime(self.since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            rows = [Tok(r["token"], r.get("terms"), r.get("source", "")) for r in once.values()]
            self._rows = sorted((t for t in rows if int(t.c.get("iat", 0)) >= floor), key=lambda t: int(t.c.get("iat", 0)))
        return self._rows

    def find(self, kind: str, pick: Callable[[Tok], bool], forge: Callable[[], Tok] | None, taken: set[str]) -> Tok | None:
        for t in self.rows():
            try:
                if t.kind == kind and t.jwt not in taken and pick(t):
                    return t
            except (ValueError, LookupError, TypeError):
                continue
        return None


class Simulated(World):
    """The local simulator (LiteSVM) with the test builds of tests/fixtures at the pinned ids, the chain of
    tests/_order.py and tests/_meter.py, and tokens signed by the seed key those builds trust. Nothing here is
    evidence of anything on a cluster: `record` refuses it for the repository itself."""
    mode = "simulated"

    def __init__(self):
        sys.path.insert(0, str(ROOT / "tests"))
        import _meter
        import _order
        import _settle

        class Both(_meter.Meter, _order.OrderChain):
            pass

        self._undo = (relay.ATTESTERS, chain.__dict__.get("V1_BUDGET_IX"), os.environ.get("KNOS_NO_SAS"))
        os.environ["KNOS_NO_SAS"] = "1"                 # no attestation service is asked from a simulator
        chain.V1_BUDGET_IX = True                       # LiteSVM reads a v1 transaction's limit from a compute budget instruction
        self.o, self.m, self.s = _order, _meter, _settle
        c = self.c = Both()
        assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
        relay.ATTESTERS = relay.ATTESTERS | {(_order.OWNER, _order.REPO)}
        self.relayer, self.mint = c.payer, c.usdc
        self.funder, self.funder_token = c.funder, c.funder_tok
        self.jwks = {oidc.GITHUB: {"keys": [{"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": "k",
                                             "n": _settle.b64(oidc.modulus_bytes(_settle.modulus(_settle.signing_key())))}]}}
        self.ledger = _Lite(c)
        self._issue = 5000
        _wallet, self.credits = c.open(self.mint, _meter.BUYER, 50 * USDC)

    def close(self) -> None:
        relay.ATTESTERS, budget, sas = self._undo
        chain.V1_BUDGET_IX = bool(budget)
        if sas is None:
            os.environ.pop("KNOS_NO_SAS", None)
        else:
            os.environ["KNOS_NO_SAS"] = sas

    def clock(self) -> float | None:
        return self.c.now()

    def pin(self) -> tuple[str, str, int]:
        return self.o.WF_REPO, self.o.WF_SHA, self.o.REPO

    def issue(self) -> int:
        self._issue += 1
        return self._issue

    def forge(self, aud: str, file: str = "prove.yml", terms: bytes | None = None, raw: Callable[[bytes], bytes] | None = None, **over) -> Any:
        """What GitHub would sign for a run of the pinned <file>, issued now, signed by the test key."""
        from _pay2 import github_claims
        c = self.c
        c.warp(1)
        now = c.now()
        c._n += 1
        claims = dict(aud=aud, iat=now, nbf=now - 600, exp=now + 300, jti=f"x{c._n}",
                      job_workflow_ref=f"{self.o.WF_REPO}/.github/workflows/{file}@refs/tags/v0.3.12", job_workflow_sha=self.o.WF_SHA)
        claims.update(over)
        body = json.dumps(github_claims(**claims), separators=(",", ":")).encode()
        jwt = self.s.sign_jwt(self.s.signing_key(), {}, raw_payload=raw(body) if raw else body)
        return Tok(jwt, terms.decode() if terms else None, "simulated") if raw is None else _Raw(jwt)

    def refused(self, ixs, payer: Keypair | None = None) -> tuple[str, int | None]:
        return self.ledger.refused(list(ixs), payer or self.relayer)

    def wait_until(self, t: int, what: str) -> None:
        self.c.warp(max(0, t - self.c.now()) + 1)

    def find(self, kind: str, pick: Callable[[Tok], bool], forge: Callable[[], Tok] | None, taken: set[str]) -> Tok | None:
        return forge() if forge else None


class _Raw:
    """A token whose payload is not JSON: only its text is held."""
    def __init__(self, jwt: str):
        self.jwt = jwt


class _Lite(chain.Ledger):
    """knos.chain.Ledger over LiteSVM: a transaction is signed exactly as the real Ledger signs it."""

    def __init__(self, c):
        super().__init__("litesvm")
        self.c = c
        self.said: dict[str, list[str]] = {}
        self.when: dict[str, int] = {}
        self.named: dict[Pubkey, list[str]] = {}

    def _one(self, ixs, payer, signers, v1=False, refuse=False):
        tx = chain.sign(ixs, payer, signers, self.c.svm.latest_blockhash(), v1)
        r = self.c.svm.send_transaction(tx)
        self.c.svm.expire_blockhash()
        ok = "Failed" not in type(r).__name__
        logs = list((r if ok else r.meta()).logs())
        sig = str(tx.signatures[0])
        if refuse:
            if ok:
                raise Failed(f"the transaction {sig} was expected to be refused and it went through")
            return sig, code_of(r.err())
        if not ok:
            raise chain.RpcError(f"transaction failed: {r.err()}", {"logs": logs})
        self.said[sig], self.when[sig] = logs, self.c.now()
        for key in tx.message.account_keys:
            self.named.setdefault(key, []).append(sig)
        return sig

    def refused(self, ixs, payer) -> tuple[str, int | None]:
        return self._one(ixs, payer, None, refuse=True)

    def send(self, ixs, payer, signers=None, v1=False) -> str:
        return self._one(list(ixs), payer, signers, v1)

    def send_all(self, groups, payer, signers=None, v1=False) -> list[str]:
        return [self._one(list(ixs), payer, signers, v1) for ixs in groups]

    def simulate(self, ixs, payer, signers=None, v1=False) -> list[str]:
        r = self.c.svm.simulate_transaction(chain.sign(ixs, payer, signers, self.c.svm.latest_blockhash(), v1))
        if "Failed" in type(r).__name__:
            raise chain.RpcError(f"transaction failed: {r.err()}", {"logs": list(r.meta().logs())})
        return list(r.meta().logs())

    def infos(self, addresses):
        got = [self.c.svm.get_account(a) for a in addresses]
        return [(a.owner, bytes(a.data)) if a is not None and a.lamports > 0 else None for a in got]

    def account(self, address):
        got = self.infos([address])[0]
        return got[1] if got else None

    def program_accounts(self, program, size=None, memcmp=None):
        out = []
        for addr, acc in self.c.svm.get_program_accounts(program):
            d = bytes(acc.data)
            if acc.lamports > 0 and (size is None or len(d) == size) and all(d[o:o + len(b)] == b for o, b in (memcmp or {}).items()):
                out.append((addr, d))
        return out

    def recent(self, address, limit=20):
        return [(sig, self.when[sig]) for sig in list(reversed(self.named.get(address, [])))[:limit]]

    def history(self, address, most=500):
        yield from list(reversed(self.named.get(address, [])))[:most]

    def logs(self, signature):
        return self.said.get(signature, [])

    def touched(self, address):
        return self.when[self.named[address][-1]] if self.named.get(address) else None

    def now(self) -> int:
        return self.c.now()


# ---- the book: what a run keeps ---------------------------------------------------------------------------------------
class Book:
    def __init__(self, ev: dict, w: World, say: Callable[[str], None]):
        self.ev, self.w, self.say = ev, w, say

    def taken(self) -> set[str]:
        return {t["jwt"] for st in self.ev["rounds"].values() for t in st.get("tokens", {}).values()}

    def token(self, st: dict, key: str, kind: str, pick: Callable[[Tok], bool], forge: Callable[[], Tok] | None, need: tuple[str, str]) -> Tok:
        """The token of one step: the one this round took before, else one found now (and kept), else Need."""
        held = st.setdefault("tokens", {})
        if key not in held:
            got = self.w.find(kind, pick, forge, self.taken())
            if got is None:
                raise Need(*need)
            held[key] = got.held()
        return Tok(**held[key])

    def tx(self, st: dict, what: str, sig: str, program: str, error: int | None = None, means: str = "") -> None:
        row: dict[str, Any] = {"signature": sig, "what": what, "program": program}
        if error is not None:
            row.update(refused=error, means=means)
        st.setdefault("transactions", []).append(row)
        self.say(f"  {'refused ' + str(error) if error is not None else 'ok     '}  {what}: {sig}")

    def done(self, st: dict, capability: str, program: str, sig: str, asserted: list[str], refusals: list[dict] | None = None) -> None:
        """A capability exercised: one transaction that succeeded at `program`, and what was checked around it."""
        self.ev["exercises"][capability] = {"status": "exercised", "round": st["round"], "program": program, "signature": sig, "asserted": asserted,
                                            **({"refusals": refusals} if refusals else {})}


def _check(condition: bool, what: str) -> None:
    if not condition:
        raise Failed(what)


def fund_parts(t: Tok) -> dict:
    """What a fund token of an order names (pay.order_fund_audience), and the order's address."""
    p = t.aud.split(":")
    if len(p) != 10 or p[:2] != ["knos3", "fund"]:
        raise ValueError("not an order's fund audience")
    balance, options, repo = Pubkey.from_string(p[7]), bytes.fromhex(p[9]), int(t.c["repository_id"])
    return {"issue": int(p[2]), "amount": int(p[3]), "work": int(p[6]), "balance": balance, "seq": int(p[8]), "flags": options[0],
            "holdback": int.from_bytes(options[1:3], "little"), "warranty": int.from_bytes(options[3:5], "little"), "repo": repo,
            "order": pay.order_pda(pay.scope_of(repo, int(p[2])), balance, int(p[8]))}


def _fund(book: Book, st: dict, key: str, tok: Tok, what: str) -> tuple[dict, Pubkey]:
    """Relays a fund token; the order is funded with its fee on top. Returns the relay's answer and the order."""
    w, f = book.w, fund_parts(tok)
    source = pay.baltok_pda(f["balance"])
    before = w.tokens(source)
    r = w.submit(tok)
    _check(bool(r.get("ok")), f"{what}: the relay answered: {r.get('why')}")
    order = Pubkey.from_string(r["order"])
    _check(order == f["order"] and r["amount"] == f["amount"], f"{what}: the order funded is not the one the token names")
    o = pay.read_order(w.account(order))
    if not r.get("already"):
        _check(o is not None and o.state == "open" and w.tokens(pay.ov_pda(order)) == o.amount + o.fee == before - w.tokens(source),
               f"{what}: the order does not hold its amount and its fee, or they did not come from the Balance")
    st[key] = {"order": str(order), "amount": r["amount"], "fee": r["fee"], "signature": r["sigs"][-1], "already": bool(r.get("already"))}
    book.tx(st, what, r["sigs"][-1], "knos_pay")
    if len(r["sigs"]) > 1:
        st.setdefault("verify", r["sigs"][0])
    return r, order


# ---- the rounds --------------------------------------------------------------------------------------------------------
def round_order(book: Book, st: dict) -> None:
    """One order funded by a comment, paid on its proof; every second use refused; a second funding of the same
    address is not paid by the first proof; what nobody proves goes back at the deadline."""
    w = book.w
    replay, words = single_use()
    plain = lambda t: not fund_parts(t)["flags"] & (order_auto.F_AUTO | order_auto.F_QUORUM) and not fund_parts(t)["holdback"]  # noqa: E731
    sim = w if isinstance(w, Simulated) else None
    if sim and "issue" not in st:
        st["issue"], st["payee"], st["wallet"] = sim.issue(), sim.o.user(), str(Keypair.from_seed(bytes([41]) * 32).pubkey())
    how = (f"in {w.repository}: open an issue, comment `/knos fund {AMOUNT // USDC}` on it TWICE, merge a pull request that closes it, and run "
           "this again within five minutes of the merge (`--resume`)")

    def fund_token(key: str, work: int = 14 * 86_400) -> Tok:
        forge = (lambda: sim.forge(pay.order_fund_audience(st["issue"], AMOUNT, pay.MERGE, sim.o.TH, sim.c.bal, work), "fund.yml", sim.o.TERMS,
                                   event_name="issue_comment", actor_id=sim.o.MAINT, repository_id=sim.o.REPO, repository_owner_id=sim.o.OWNER)) if sim else None
        pick = plain if "fund1" not in st else lambda t: plain(t) and str(fund_parts(t)["order"]) == st["fund1"]["order"]
        return book.token(st, key, "fund", pick, forge, ("fund.yml", how))

    t1 = fund_token("fund1")
    f = fund_parts(t1)
    if "fund1" not in st:
        r, order = _fund(book, st, "fund1", t1, "the fund token is relayed: the order is funded, its fee on top")
        st["comment"] = f"/knos fund {f['amount'] // USDC}"
        book.done(st, "work_orders", "knos_pay", st["fund1"]["signature"],
                  [f"order {order} holds {money(r['amount'])} and its fee of {money(r['fee'])} on top", "the money left the Balance the comment named"])
        if st.get("verify"):
            book.done(st, "verify_github", "knos_oidc", st["verify"], ["knos_oidc verified GitHub's signature on the fund token; knos_pay then took the token account"])
    order = Pubkey.from_string(st["fund1"]["order"])
    source = pay.baltok_pda(f["balance"])

    proof_pick = lambda t: t.aud.startswith(f"knos3:pay:{order}:")  # noqa: E731
    forge = (lambda: sim.forge(pay.order_pay_audience(order, sim.o.HEAD, sim.o.TH, pay.MERGE, 7, [(st["payee"], 10_000, Pubkey.from_string(st["wallet"]))]),
                               repository_id=sim.o.REPO)) if sim else None
    proof = book.token(st, "proof", "pay", proof_pick, forge, ("prove.yml", how))
    payees = pay.payees_of(proof.aud)
    wallets = [(i, pay.order_destination(pay.read_bind(w.account(pay.bind_pda(i))), a)) for i, _b, a in payees]
    dest = [pay.ata(wallet, w.mint) if wallet else None for _i, wallet in wallets]
    if "paid" not in st:
        had = [w.tokens(d) if d else 0 for d in dest]
        r = w.submit(proof)
        _check(bool(r.get("ok")), f"the proof: the relay answered: {r.get('why')}")
        total = sum(p["amount"] for p in r["paid"])
        _check(total == st["fund1"]["amount"], "the payees were not paid the order's amount")
        if not r.get("already"):
            _check(w.account(order) is None and [w.tokens(d) - h for d, h in zip(dest, had) if d] == [p["amount"] for p in r["paid"] if p["to"]],
                   "the order is not closed, or a payee's account did not grow by its share")
        st["paid"] = {"signature": r["sigs"][-1], "amount": total}
        book.tx(st, "the merged pull request's proof is relayed: the payee is paid", r["sigs"][-1], "knos_pay")
        book.done(st, "order_pay", "knos_pay", r["sigs"][-1], [f"{money(total)} paid to the payee the token names", "the order's account is closed"])

    def unmoved(what: str, act: Callable[[], Any]):
        before = (w.tokens(source), w.tokens(pay.ov_pda(order)), [w.tokens(d) for d in dest if d])
        out = act()
        _check(before == (w.tokens(source), w.tokens(pay.ov_pda(order)), [w.tokens(d) for d in dest if d]), f"{what}: money moved")
        return out

    if "duplicate" not in st:        # the same proof from another relayer, one with no SOL: it could not send anything
        r = unmoved("the proof relayed a second time", lambda: w.submit(proof, Keypair.from_seed(bytes([42]) * 32)))
        _check(bool(r.get("ok") and r.get("already")) and r["sigs"] == [st["paid"]["signature"]],
               f"a second relay of the proof was not answered with the first payment: {r}")
        st["duplicate"] = {"answer": "already", "names": r["sigs"][0]}
    if "replay" not in st:           # the fund token again, while the address is free: only its marker stands in the way
        tok, key, _ = w.verified(t1)
        b = have(pay.read_balance(w.account(f["balance"])), "the Balance the comment named")
        _check(w.account(order) is None, "the order's address is not free: the fund token's second use would be refused for another reason")
        ix = pay.fund_order_balance_ix(w.relayer.pubkey(), tok, key, f["balance"], b.mint, b.owner_id, f["repo"], f["issue"], (t1.terms or "").encode(),
                                       have(w.account(tok)), f["seq"], w.ledger.infos([b.mint])[0][0])
        sig, code = unmoved("the fund token sent again", lambda: w.refused([ix]))
        _check(code == replay, f"the fund token sent again was refused with error {code}, not the single-use error {replay} ({sig})")
        _check(w.account(order) is None, "a second order was funded by one comment")
        st["replay"] = {"signature": sig, "error": code, "means": words}
        book.tx(st, "the fund token, sent again", sig, "knos_pay", code, words)
        book.done(st, "single_use_tokens", "knos_pay", st["fund1"]["signature"],
                  [f"the fund token's second use is refused with error {replay} ({words}) and funds nothing",
                   "the proof relayed a second time is answered with the first payment and sends nothing"],
                  [{"signature": sig, "error": code, "means": words, "what": "the fund token, sent again"}])
    try:        # a second funding of the same address, and the first proof against it: the double payment of 0.3.13
        t2 = fund_token("fund2", 600 if sim else 14 * 86_400)
    except Need as need:
        st["pending"] = f"the double payment was not attempted: {need} ({need.how})"
        return
    st.pop("pending", None)
    if "fund2" not in st:
        _fund(book, st, "fund2", t2, "a second fund token funds the same address again")
    if "double" not in st:
        o = have(pay.read_order(w.account(order)), "the second order")
        tok, key, _ = w.verified(proof)
        ix = order_auto.with_quorum(pay.pay_order_ix(w.relayer.pubkey(), tok, key, order, o, wallets, used=w.account(tok)), order, o)
        sig, code = unmoved("the first proof against the second order", lambda: w.refused([ix]))
        means = pay.ERRORS.get(code or 0, "")
        st["double"] = {"signature": sig, "error": code, "means": means}
        book.tx(st, "the first proof, sent again against the second funding", sig, "knos_pay", code, means)
        book.ev["exercises"]["single_use_tokens"].setdefault("refusals", []).append(
            {"signature": sig, "error": code, "means": means, "what": "the first proof against a second funding of the same address: nothing is paid twice"})
    if "refund" not in st:
        o = have(pay.read_order(w.account(order)), "the second order, to go back")
        w.wait_until(o.deadline, "the second order's deadline, after which it goes back to its Balance")
        before = w.tokens(source)
        sig = w.send([pay.refund_order_ix(w.relayer.pubkey(), order, o)])
        _check(w.tokens(source) - before == o.amount + o.fee and w.account(order) is None, "the expired order did not go back whole")
        st["refund"] = {"signature": sig, "amount": o.amount + o.fee}
        book.tx(st, "the unproven order, past its deadline, goes back to its Balance with its fee", sig, "knos_pay")


def round_expiry(book: Book, st: dict) -> None:
    """A wallet funds a job and an order for one minute of work, tops the order up, and both go back whole."""
    w = book.w
    wf_repo, wf_sha, repo = w.pin()
    funder, source = w.funder, w.funder_token
    terms = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "mode": "merge", "v": 2})
    need = pay.MIN_AMOUNT + AMOUNT + pay.order_fee(AMOUNT) + USDC + pay.order_fee(AMOUNT + USDC)
    if "issue" not in st:
        _check(w.tokens(source) >= need, f"the funding wallet {funder.pubkey()} holds {money(w.tokens(source))} test USDC; this round needs {money(need)} (it all comes back)")
        st["issue"], st["start"] = w.now(), w.tokens(source)
    n = st["issue"]
    job, order = pay.job_pda(repo, n, funder.pubkey()), pay.order_pda(pay.scope_of(repo, n), funder.pubkey(), 0)
    if "job" not in st:
        sig = w.send([pay.fund_wallet_ix(funder.pubkey(), source, w.mint, repo, n, pay.MIN_AMOUNT, wf_repo, wf_sha, terms, work_s=pay.MIN_WORK)], funder)
        j = have(pay.read_job(w.account(job)), "the job")
        _check(j.amount == pay.MIN_AMOUNT, "the job does not hold its amount")
        st["job"] = {"signature": sig, "address": str(job), "deadline": j.deadline}
        book.tx(st, "a wallet funds a job with its own money", sig, "knos_pay")
        book.done(st, "fund_from_wallet", "knos_pay", sig, [f"job {job} holds {money(pay.MIN_AMOUNT)} of the wallet's own test USDC"])
    if "order" not in st:
        sig = w.send([pay.fund_order_wallet_ix(funder.pubkey(), source, w.mint, repo, n, AMOUNT, wf_repo, wf_sha, terms, work_s=pay.MIN_WORK)], funder)
        o = have(pay.read_order(w.account(order)), "the order")
        _check(w.tokens(pay.ov_pda(order)) == AMOUNT + o.fee, "the order does not hold its amount and its fee")
        st["order"] = {"signature": sig, "address": str(order), "deadline": o.deadline}
        book.tx(st, "the wallet funds an order, its fee on top", sig, "knos_pay")
    if "top_up" not in st:
        o = have(pay.read_order(w.account(order)), "the order")
        sig = w.send([pay.top_up_ix(funder.pubkey(), order, o, USDC, source)], funder)
        o2 = have(pay.read_order(w.account(order)), "the order")
        _check(o2.amount == AMOUNT + USDC and w.tokens(pay.ov_pda(order)) == o2.amount + o2.fee, "the top-up is not in the order with its fee")
        st["top_up"] = {"signature": sig}
        book.tx(st, "the funder adds 1.00 to the open order", sig, "knos_pay")
        book.done(st, "top_up", "knos_pay", sig, [f"the order's amount went from {money(AMOUNT)} to {money(o2.amount)}, and it holds the fee on the whole"])
    if "refund" not in st:
        w.wait_until(max(st["job"]["deadline"], st["order"]["deadline"]), "the deadline of the job and the order nobody proves")
        s1 = w.send([pay.refund_ix(w.relayer.pubkey(), job, have(pay.read_job(w.account(job)), "the job"))])
        s2 = w.send([pay.refund_order_ix(w.relayer.pubkey(), order, have(pay.read_order(w.account(order)), "the order"))])
        _check(w.account(job) is None and w.account(order) is None and w.tokens(source) == st["start"], "the expired job and order did not go back whole to the wallet")
        st["refund"] = {"job": s1, "order": s2}
        book.tx(st, "the expired job goes back to its wallet", s1, "knos_pay")
        book.tx(st, "the expired order goes back to its wallet with its fee", s2, "knos_pay")
        book.done(st, "refund", "knos_pay", s1, ["a job past its deadline went back whole to the wallet that funded it", "so did the order, with the fee paid on top",
                                                 "the wallet holds what it held before the round"])


def round_quorum(book: Book, st: dict) -> None:
    """An order that pays on two judges and holds a fifth back: one judge moves nothing, the second pays, and a
    neutral judge's revert inside the warranty returns what was held back."""
    w = book.w
    sim = w if isinstance(w, Simulated) else None
    how = (f"in {w.repository}: comment `/knos fund {AMOUNT // USDC} quorum 2 holdback 20 warranty 1` on a new issue and merge a pull request that closes it; then, in a "
           "repository of another owner, start the pinned attest.yml by hand (`gh workflow run attest.yml -f repository=<owner/name> -f pull=<n> -f order=<address> "
           "-f kind=pay`), revert the merge, and start it again with `-f kind=revert`")
    if sim and "issue" not in st:
        st["issue"], st["payee"], st["wallet"], st["judge"] = sim.issue(), sim.o.user(), str(Keypair.from_seed(bytes([43]) * 32).pubkey()), sim.o.user()
    options = pay.opts(flags=pay.F_NEUTRAL | order_auto.quorum_flags(2), holdback_bps=2000, warranty_days=1)
    wanted = lambda t: order_auto.quorum_of(fund_parts(t)["flags"]) == 2 and fund_parts(t)["holdback"] > 0  # noqa: E731
    forge = (lambda: sim.forge(pay.order_fund_audience(st["issue"], AMOUNT, pay.MERGE, sim.o.TH, sim.c.bal, options=options), "fund.yml", sim.o.TERMS,
                               event_name="issue_comment", actor_id=sim.o.MAINT, repository_id=sim.o.REPO, repository_owner_id=sim.o.OWNER)) if sim else None
    t = book.token(st, "fund", "fund", wanted, forge, ("fund.yml", how))
    f = fund_parts(t)
    if "fund1" not in st:
        _fund(book, st, "fund1", t, "a comment funds an order that needs two judges and holds a fifth back")
    order, source = Pubkey.from_string(st["fund1"]["order"]), pay.baltok_pda(f["balance"])

    def aud() -> str:           # the simulator's: what both judges sign
        s = have(sim)
        return pay.order_pay_audience(order, s.o.HEAD, s.o.TH, pay.MERGE, 7, [(st["payee"], 10_000, Pubkey.from_string(st["wallet"]))])

    def by_hand() -> dict:      # the simulator's: attest.yml started by hand in a repository of the judge's own
        return dict(file="attest.yml", event_name="workflow_dispatch", actor_id=st["judge"], repository_owner_id=st["judge"],
                    repository_id=40_000_000 + st["judge"] % 1_000_000)
    own = lambda x: x.aud.startswith(f"knos3:pay:{order}:") and int(x.c["repository_id"]) == f["repo"]  # noqa: E731
    other = lambda x: x.aud.startswith(f"knos3:pay:{order}:") and int(x.c["repository_id"]) != f["repo"]  # noqa: E731
    first = book.token(st, "judge1", "pay", own, (lambda: sim.forge(aud(), repository_id=sim.o.REPO)) if sim else None, ("prove.yml", how))
    payees = pay.payees_of(first.aud)
    dest = pay.ata(payees[0][2], w.mint) if payees[0][2] else None
    if "one" not in st:
        had, held = (w.tokens(dest) if dest else 0), w.tokens(pay.ov_pda(order))
        r = w.submit(first)
        _check(bool(r.get("ok")), f"the first judge: the relay answered: {r.get('why')}")
        o = pay.read_order(w.account(order))
        _check(o is not None and o.state == "open" and o.paid == 0 and w.tokens(pay.ov_pda(order)) == held and (w.tokens(dest) if dest else 0) == had,
               "one judge out of two moved money")
        st["one"] = {"signature": r["sigs"][-1]}
        book.tx(st, "the first judge's token is recorded: one of two, nothing is paid", r["sigs"][-1], "knos_pay")
    second = book.token(st, "judge2", "pay", other, (lambda: sim.forge(aud(), **by_hand())) if sim else None, ("attest.yml", how))
    if "two" not in st:
        had = w.tokens(dest) if dest else 0
        r = w.submit(second)
        _check(bool(r.get("ok")), f"the second judge: the relay answered: {r.get('why')}")
        paid, back = sum(p["amount"] for p in r["paid"]), int(r.get("held_back", 0))
        _check(paid + back == st["fund1"]["amount"] and back > 0, "the second judge did not pay the order less its holdback")
        if not r.get("already") and dest:
            _check(w.tokens(dest) - had == paid and have(pay.read_order(w.account(order)), "the order").state == "warranty",
                   "the payee was not paid, or the order is not in its warranty")
        st["two"] = {"signature": r["sigs"][-1], "paid": paid, "held_back": back}
        book.tx(st, "the second judge, a neutral run in another repository, pays the order less its holdback", r["sigs"][-1], "knos_pay")
        said = [f"after one judge of two: nothing paid, the order holds what it held ({st['one']['signature'][:8]}...)",
                f"after the second: {money(paid)} paid, {money(back)} held back for the warranty"]
        book.done(st, "order_quorum", "knos_pay", r["sigs"][-1], said)
        book.done(st, "neutral_attest", "knos_pay", r["sigs"][-1], ["the paying token is from attest.yml, started by hand in a repository that is not the order's"])
    head = second.aud.split(":")[3]
    gone = book.token(st, "revert", "revert", lambda x: x.aud == pay.revert_audience(order, head) and int(x.c["repository_id"]) != f["repo"],
                      (lambda: sim.forge(pay.revert_audience(order, head), **by_hand())) if sim else None, ("attest.yml", how))
    if "revert" not in st:
        before = w.tokens(source)
        r = w.submit(gone)
        _check(bool(r.get("ok")), f"the revert: the relay answered: {r.get('why')}")
        if not r.get("already"):
            _check(w.tokens(source) - before == r["amount"] and w.account(order) is None, "the holdback did not go back to its funder")
        _check(r["amount"] >= st["two"]["held_back"], "less than the holdback went back")
        st["revert"] = {"signature": r["sigs"][-1], "amount": r["amount"]}
        book.tx(st, "a neutral judge signs the revert inside the warranty: the holdback and its fee go back", r["sigs"][-1], "knos_pay")
        for cap in ("order_challenge", "warranty_revert"):
            book.done(st, cap, "knos_pay", r["sigs"][-1], [f"{money(r['amount'])} (the holdback and the fee on it) went back to the funder's Balance",
                                                          "the revert token is from a run in another repository than the order's"])


def round_auto(book: Book, st: dict) -> None:
    """An order that pays the first pull request its black-box suite passes, with no merge."""
    w = book.w
    sim = w if isinstance(w, Simulated) else None
    how = (f"in {w.repository}: comment `/knos fund {AMOUNT // USDC} auto` on an issue that has a black-box suite (.knos/acceptance/<issue>/blackbox.sh), "
           "and open a pull request that passes it; do not merge")
    if sim and "issue" not in st:
        st["issue"], st["payee"], st["wallet"] = sim.issue(), sim.o.user(), str(Keypair.from_seed(bytes([44]) * 32).pubkey())
    wanted = lambda t: bool(fund_parts(t)["flags"] & order_auto.F_AUTO) and not order_auto.quorum_of(fund_parts(t)["flags"])  # noqa: E731
    suite = sim.o.SUITE if sim else b""
    forge = (lambda: sim.forge(pay.order_fund_audience(st["issue"], AMOUNT, pay.TESTS, pay.terms_hash(suite), sim.c.bal, options=pay.opts(order_auto.F_AUTO)),
                               "fund.yml", suite, event_name="issue_comment", actor_id=sim.o.MAINT, repository_id=sim.o.REPO, repository_owner_id=sim.o.OWNER)) if sim else None
    t = book.token(st, "fund", "fund", wanted, forge, ("fund.yml", how))
    if "fund1" not in st:
        _fund(book, st, "fund1", t, "a comment funds an order that pays on its black-box suite, with no merge")
    order = Pubkey.from_string(st["fund1"]["order"])
    forge = (lambda: sim.forge(order_auto.auto_audience(order, sim.o.HEAD, pay.terms_hash(suite), 7, st["payee"], Pubkey.from_string(st["wallet"])),
                               repository_id=sim.o.REPO, event_name="workflow_run")) if sim else None
    proof = book.token(st, "proof", "pay", lambda x: x.aud.startswith(f"knos3:auto:{order}:"), forge, ("prove.yml", how))
    if "paid" not in st:
        r = w.submit(proof)
        _check(bool(r.get("ok")), f"the suite's token: the relay answered: {r.get('why')}")
        total = sum(p["amount"] for p in r["paid"])
        _check(total == st["fund1"]["amount"], "the author was not paid the order's amount")
        st["paid"] = {"signature": r["sigs"][-1], "amount": total, "event": str(proof.c.get("event_name"))}
        book.tx(st, "the suite passed on an open pull request: its author is paid with no merge", r["sigs"][-1], "knos_pay")
        said = [f"{money(total)} paid on a token of the event `{proof.c.get('event_name')}`: a check finishing, not a merge",
                "the order was funded in tests mode, on the hash of its black-box suite"]
        book.done(st, "order_auto_accept", "knos_pay", r["sigs"][-1], said)
        book.done(st, "tests_mode", "knos_pay", r["sigs"][-1], said[1:])


def _batch_parts(t: Tok) -> dict:
    p = t.aud.split(":")
    return {"kind": p[1], "buyer": int(p[2]), "seller": int(p[3]), "month": int(p[4]), "seq": int(p[5]), "count": int(p[6])}


def round_meter(book: Book, st: dict) -> None:
    """The buyer's count in batches and the seller's own claim of the same month, both on chain, and how far apart."""
    w = book.w
    sim = w if isinstance(w, Simulated) else None
    how = ("in the buyer's repository: `knos meter batch <evaluations> --ledger meter/<seller>.jsonl`, commit, and start the pinned attest.yml with `-f kind=batch "
           "-f order=meter/<seller>.jsonl -f pull=0`; in the seller's: the same with `--claim` and `-f kind=claim`. The buyer's credits must be open "
           "(`knos meter open`)")
    month = meter.yyyymm(w.now())
    for kind, cap, claim in (("batch", "meter_batch", False), ("claim", "meter_seller_claim", True)):
        for n in range(2):
            key = f"{kind}{n}"
            if key in st:
                continue
            if sim:
                count = 3 + (claim and n)
                aud = meter.batch_audience(sim.m.BUYER, sim.m.SELLER, month, n, count, count, count * 2 * USDC, bytes([0xA0 + n + 2 * claim]) * 32, kind)
                forge = lambda aud=aud, claim=claim: sim.forge(aud, "attest.yml", repository_owner_id=sim.m.SELLER if claim else sim.m.BUYER, run_attempt=1)  # noqa: E731
            else:
                forge = None
            same = lambda x, n=n: _batch_parts(x)["seq"] == n and ("pair" not in st or [_batch_parts(x)[k] for k in ("buyer", "seller", "month")] == st["pair"])  # noqa: E731
            try:
                t = book.token(st, key, kind, same, forge, ("attest.yml", how))
            except Need:
                if n == 0:
                    raise
                break                   # one batch is the round; a second is taken when it is there
            p = _batch_parts(t)
            st.setdefault("pair", [p["buyer"], p["seller"], p["month"]])
            before = meter.book(w.ledger, p["buyer"], p["seller"], p["month"], bool(claim))
            r = w.submit(t)
            _check(bool(r.get("ok")), f"the {kind}: the relay answered: {r.get('why')}")
            after = meter.book(w.ledger, p["buyer"], p["seller"], p["month"], bool(claim))
            if not r.get("already"):
                _check(after.evaluations - before.evaluations == p["count"] and after.next_seq == p["seq"] + 1, f"the {kind} is not in the ledger on chain")
            st[key] = {"signature": r["sigs"][-1], "count": p["count"]}
            book.tx(st, f"the {'seller' if claim else 'buyer'}'s {kind} {n + 1} of {p['count']} evaluations is anchored", r["sigs"][-1], "knos_meter")
        total = meter.book(w.ledger, st["pair"][0], st["pair"][1], st["pair"][2], claim).evaluations
        st["seller" if claim else "buyer"] = total
        book.done(st, cap, "knos_meter", st[f"{kind}0"]["signature"],
                  [f"the {'seller' if claim else 'buyer'}'s ledger on chain counts {total} evaluations for {st['pair'][2]}"])
    st["apart"] = st["seller"] - st["buyer"]


def round_strict(book: Book, st: dict) -> None:
    """A token whose payload holds NaN, signed by a key the verifier trusts: refused by the strict build."""
    w = book.w
    build = book.ev["programs"].get("knos_oidc", {}).get("is")
    if not isinstance(w, Simulated):
        if build != "next":
            raise Skip("knos_oidc with strict JSON is not live at the public id (it will be proposed after proposals 3 to 6 execute): a NaN claim is accepted until then")
        raise Skip("no forge signs a NaN claim: this needs a key Knos holds, admitted as an issuer at the public id, and the release run has none")
    if "refused" in st:
        return
    not_json = int(have(re.search(r"pub const E_JSON: u32 = (\d+);", (ROOT / "programs-v2" / "knos_oidc" / "src" / "claims.rs").read_text(encoding="utf-8")))[1])
    me, n = w.relayer, w.s.modulus(w.s.signing_key())
    plan = oidc.step_plan(n.bit_length())

    def steps(jwt: str):
        """The token written and stepped, all but the last step: (its id, the last step)."""
        tid = oidc.token_id(jwt)
        for ix in oidc.write_ixs(me.pubkey(), tid, jwt):
            w.send([ix])
        for sq in plan[:-1]:
            w.send([oidc.step_ix(me.pubkey(), tid, oidc.key_pda(oidc.GITHUB, n), sq)])
        return tid, oidc.step_ix(me.pubkey(), tid, oidc.key_pda(oidc.GITHUB, n), plan[-1])

    # the control: the same token with a number where the NaN will be is verified, so the NaN is what is refused
    tid, last = steps(w.forge("knos:strict", raw=lambda body: body[:-1] + b',"x":1}').jwt)
    good = w.send([last])
    _check(bool(have(oidc.read_token(w.account(oidc.token_pda(me.pubkey(), tid))), "the control token").verified), "the control token was not verified")
    book.tx(st, "the control: the same token with a number in that place is verified", good, "knos_oidc")
    _tid, last = steps(w.forge("knos:strict", raw=lambda body: body[:-1] + b',"x":NaN}').jwt)
    try:
        sig, code = w.refused([last])
    except Failed:
        raise Skip("the knos_oidc build in the simulator (tests/fixtures/knos_oidc_v2_test.so) verified a NaN claim: it is not the strict build") from None
    _check(code == not_json, f"the NaN claim was refused with error {code}, not the verifier's not-JSON error {not_json}")
    st["refused"] = {"signature": sig, "error": code}
    book.tx(st, "a signed token whose payload holds NaN is refused by the verifier", sig, "knos_oidc", code, "the payload is not JSON")
    book.ev["exercises"]["oidc_strict_json"] = {"status": "refused as it should be", "round": st["round"], "program": "knos_oidc",
                                                "note": "a refusal alone: no transaction succeeded, so the capability's stage does not move",
                                                "refusals": [{"signature": sig, "error": code, "means": "the payload is not JSON", "what": "a NaN claim"}]}


# name -> (the round, the programs whose upgraded build it needs, the capabilities it can exercise)
ROUNDS: dict[str, tuple[Callable[[Book, dict], None], tuple[str, ...], tuple[str, ...]]] = {
    "expiry": (round_expiry, ("knos_pay",), ("fund_from_wallet", "top_up", "refund")),
    "order": (round_order, ("knos_oidc", "knos_pay"), ("work_orders", "order_pay", "single_use_tokens", "verify_github")),
    "quorum": (round_quorum, ("knos_oidc", "knos_pay"), ("order_quorum", "neutral_attest", "order_challenge", "warranty_revert")),
    "auto": (round_auto, ("knos_oidc", "knos_pay"), ("order_auto_accept", "tests_mode")),
    "meter": (round_meter, ("knos_oidc", "knos_meter"), ("meter_batch", "meter_seller_claim")),
    "strict": (round_strict, ("knos_oidc",), ("oidc_strict_json",)),
}
NOT_ON_CHAIN = {"fuzz_rsa_diff_target", "kani_fee_conservation", "rust_handler_tests"}      # about a program's source, with nothing to send
# what has no round here, and why: said by `run`, never guessed at
NO_ROUND = {
    "fee_tiers": "the second tier starts above 1,000.00: not an amount to run in a tiny round; a 5.00 order shows the minimum fee only",
    "passkey_funder": "needs run: the site's Buy page (a passkey signs in a browser; the relay carries the comment)",
    "passkey_fund_relay": "needs run: the site's Buy page (a passkey signs in a browser; the relay carries the comment)",
    "buyer_page": "needs run: the site's Buy page (a passkey signs in a browser; the relay carries the comment)",
    "verify_gitlab": "needs run: a pipeline on gitlab.com (Knos has no project there)",
    "gitlab_pay": "needs run: a pipeline on gitlab.com (Knos has no project there)",
    "verify_any_issuer": "needs run: the rotate workflow naming a key of an issuer Knos runs (there is none yet)",
    "holdback_release": "a holdback is released a day after payment at the earliest: fund one, then `knos` releases it; no round here waits a day",
    "x402_knos_order": "needs run: node examples/x402_attested/live.mjs run (docs/X402.md)",
}


def exercisable(root: Path = ROOT) -> dict[str, str]:
    """Every capability of docs/capabilities.json below `exercised` that is about a program: its round's name, or
    the reason there is none."""
    by = {cap: name for name, (_f, _p, caps) in ROUNDS.items() for cap in caps}
    out = {}
    for c in _json(root / "docs" / "capabilities.json")["capabilities"]:
        if c["stage"] in ("exercised", "reproduced"):
            continue
        if c["id"] in by:
            out[c["id"]] = by[c["id"]]
        elif c["id"] in NO_ROUND:
            out[c["id"]] = "none: " + NO_ROUND[c["id"]]
        elif c["id"] not in NOT_ON_CHAIN and ("deployed" in c["evidence"] or str(c["evidence"].get("implemented", {}).get("path", "")).startswith("programs-v2/")):
            out[c["id"]] = "none: no round is written for it yet"
    return out


def new_evidence(w: World, programs: dict) -> dict:
    return {"v": 1, "mode": w.mode, "cluster": "devnet" if w.mode == "public" else "simulator", "started": w.now(), "programs": programs,
            "exercises": {}, "rounds": {}}


def run(w: World, ev: dict, only: str | None = None, say: Callable[[str], None] = print) -> dict:
    """Runs every round that still has something to do. Returns the evidence, changed in place."""
    book = Book(ev, w, say)
    plan = exercisable()
    for name, (fn, needs, caps) in ROUNDS.items():
        if only and only not in caps and only != name:
            continue
        if all(ev["exercises"].get(c, {}).get("status") == "exercised" for c in caps) and "pending" not in ev["rounds"].get(name, {}) \
                and (name != "order" or "refund" in ev["rounds"].get(name, {})):
            say(f"[{name}] done before: nothing is sent again")
            continue
        st = ev["rounds"].setdefault(name, {"round": name})
        say(f"[{name}] {' '.join((fn.__doc__ or '').split())}")
        why: str | None = None
        behind = [p for p in needs if ev["programs"].get(p, {}).get("is") not in ("new", "next")]
        try:
            if behind:
                raise Skip(f"{', '.join(behind)} does not run its upgraded build at the public id")
            fn(book, st)
            st.pop("stopped", None)
        except Need as need:
            why = str(need)
            say(f"  NEEDS A RUN of {need.workflow}: {need.how}")
        except Wait as wait:
            why = str(wait)
            say(f"  {why}; run this again after it")
        except Skip as skip:
            why = f"skipped: {skip}"
            say(f"  {why}")
        except Failed as bad:
            why = f"failed: {bad}"
            say(f"  FAILED: {bad}")
        except Exception as bad:  # noqa: BLE001 - one round's trouble does not stop the others; it is written down
            why = f"failed: {type(bad).__name__}: {str(bad)[:300]}"
            say(f"  FAILED: {why}")
        if why:
            st["stopped"] = why
            for c in caps:
                if ev["exercises"].get(c, {}).get("status") != "exercised" and c in plan:
                    ev["exercises"][c] = {"status": why, "round": name}
    for cap, where in plan.items():
        if where.startswith("none: ") and (not only or only == cap):
            ev["exercises"].setdefault(cap, {"status": where[6:] if where.startswith("none: needs run") else "no round: " + where[6:]})
    ev["finished"] = w.now()
    done = sorted(c for c, e in ev["exercises"].items() if e.get("status") == "exercised")
    say(f"exercised: {', '.join(done) or 'nothing'}")
    for c, e in sorted(ev["exercises"].items()):
        if e.get("status") != "exercised":
            say(f"  {c}: {e['status']}")
    return ev


# ---- record -----------------------------------------------------------------------------------------------------------
def round_section(ev: dict) -> str:
    """The run as a section of docs/CAPABILITIES.md, markers included: every transaction and what was checked."""
    date = datetime.fromtimestamp(ev["finished"], timezone.utc)
    out = [BEGIN, "", "## The round on the public program ids", "",
           f"On {date.day} {date:%B %Y} `scripts/exercise_public.py` ran the rounds below on devnet at the PUBLIC program ids, in test USDC, with the smallest "
           "amounts the programs take. Every transaction opens in the explorer; a refusal is a transaction that landed and failed, with the program's error.", ""]
    for name, st in ev["rounds"].items():
        rows = st.get("transactions") or []
        if not rows:
            continue
        out += [f"**{name}.** {' '.join((ROUNDS[name][0].__doc__ or '').split())}", "", "| Step | Transaction | Result |", "| --- | --- | --- |"]
        for r in rows:
            link = f"[{r['signature'][:8]}...](https://explorer.solana.com/tx/{r['signature']}?cluster=devnet)"
            out.append(f"| {r['what']} | {link} | " + (f"refused, error {r['refused']}: {r['means']}" if "refused" in r else f"succeeded at {r['program']}") + " |")
        out.append("")
    out += ["What was checked, by capability:", ""]
    for cap, e in sorted(ev["exercises"].items()):
        if e.get("status") == "exercised":
            out.append(f"- `{cap}`: " + "; ".join(e["asserted"]) + ".")
    out += ["", END]
    return "\n".join(out)


def demo_round(ev: dict) -> dict | None:
    """What web/demo_data.json shows of the run (scripts/demo_data.py reads it from docs/capabilities.json): the
    order's funding, its payment, the single-use refusal and the two counts. None unless all four are there."""
    o, m = ev["rounds"].get("order", {}), ev["rounds"].get("meter", {})
    if not all(k in o for k in ("fund1", "paid", "replay")) or "apart" not in m:
        return None
    date = datetime.fromtimestamp(ev["finished"], timezone.utc)
    return {"date": f"{date.day} {date:%B %Y}",
            "fund": {"comment": o["comment"], "tx": o["fund1"]["signature"], "order": o["fund1"]["order"], "amount": money(o["fund1"]["amount"]),
                     "fee": money(o["fund1"]["fee"])},
            "paid": {"tx": o["paid"]["signature"], "amount": money(o["paid"]["amount"])},
            "replay": {"tx": o["replay"]["signature"], "error": o["replay"]["error"], "means": o["replay"]["means"]},
            "count": {"buyer": m["buyer"], "seller": m["seller"], "apart": m["apart"],
                      "buyer_tx": [m[k]["signature"] for k in ("batch0", "batch1") if k in m], "seller_tx": [m[k]["signature"] for k in ("claim0", "claim1") if k in m]}}


def record(ev: dict, root: Path = ROOT, say: Callable[[str], None] = print, refresh: Callable[[Path], None] | None = None) -> int:
    """Writes the evidence of a run into the tree at `root`. Returns 0, or 1 with what was refused. `refresh(root)`
    writes root/web/upgrades.json from the cluster (scripts/upgrade_feed.py)."""
    if ev.get("mode") != "public" and root.resolve() == ROOT.resolve():
        say("refused: this evidence is from the simulator. Only a run at the public program ids is written into the repository.")
        return 1
    import capabilities as cap
    live = {n: p for n, p in ev["programs"].items() if p.get("is") == "new"}
    for n, p in ev["programs"].items():
        if p.get("is") != "new":
            say(f"{n}: not the build of proposal {PROPOSALS[n]} at the public id ({p.get('is')}): its version, its proposal and its capabilities stay as they are")

    manifest = _json(root / "docs" / "capabilities.json")
    for n in live:
        manifest["programs"][n]["on_chain"] = NEW[n]
    moved = []
    for c in manifest["capabilities"]:
        e = ev["exercises"].get(c["id"]) or {}
        if e.get("status") != "exercised" or c["stage"] in ("exercised", "reproduced"):
            continue
        prog = e["program"]
        if prog not in live or not _SIG.fullmatch(e["signature"]) or "tested" not in c["evidence"]:
            say(f"{c['id']}: not moved ({prog} is not on its upgraded build, or the evidence is not a transaction)")
            continue
        version = c["evidence"].get("deployed", {}).get("version") or NEW[prog]
        c["evidence"]["deployed"] = {"program": prog, "id": manifest["programs"][prog]["id"], "version": version}
        c["evidence"]["exercised"] = {"signature": e["signature"], "ids": "public", "round": e["round"], "asserted": e["asserted"],
                                      **({"refusals": e["refusals"]} if e.get("refusals") else {})}
        c["stage"] = "exercised"
        note = c.get("note", "")
        if note.startswith("Rehearsed on "):        # the rehearsal stays named, as what came before; what it says of the public ids is no longer so
            sig = _SIG.search(note)
            note = (f'Before the upgrade it was rehearsed on a staging deployment (signature {sig.group(0)}; docs/CAPABILITIES.md, "The 0.3.14 rehearsal on '
                    'devnet"); the transaction here is at the public program id.') if sig else ""
        note = re.sub(r"^Runs at the public ids? only once .*?\(the live state is in web/upgrades\.json\)\.\s*", "", note)
        if note:
            c["note"] = note
        else:
            c.pop("note", None)
        moved.append(c["id"])
    shown = demo_round(ev)
    if shown and {"knos_pay", "knos_oidc", "knos_meter"} <= set(live):
        manifest["public_round"] = shown
    _write(root / "docs" / "capabilities.json", manifest)

    # web/upgrades.json is the feed's: scripts/upgrade_feed.py reads the multisig again (`refresh`), and an entry stays
    # `executed` here only where the hash this run read at the public id is that proposal's build
    seen = _json(root / "docs" / "provenance.json") or {"programs": {}}
    before = {e["index"]: e for e in (_json(root / "web" / "upgrades.json") or {"entries": []})["entries"]}
    if refresh:
        refresh(root)
    else:
        say("web/upgrades.json: left as it is (it is the feed's own file: `record --rpc URL` reads the multisig again)")
    up = _json(root / "web" / "upgrades.json") or {"entries": []}
    wrong: list[str] = []
    for at, entry in enumerate(up["entries"]):
        n = entry["program"]
        if entry["index"] != PROPOSALS.get(n):
            continue
        if n in live and entry["build_hash"] == live[n]["hash"]:
            row = seen.setdefault("programs", {}).setdefault(n, {"address": live[n]["id"]})
            row.update(on_chain_hash=live[n]["hash"], live_slot=live[n]["slot"], proposal=PROPOSALS[n], proposal_status="Executed")
            for key, value in (("on_chain_commit", entry.get("source_commit")), ("on_chain_run", entry.get("gate_run"))):
                row.pop(key, None)
                if value:
                    row[key] = value
        elif entry["status"] == "executed" and entry != before.get(entry["index"]):
            wrong.append(f"proposal {entry['index']}")
            say(f"web/upgrades.json: the feed says proposal {entry['index']} executed, and {n} did not run its build when the exercises ran: its entry is kept as it was")
            up["entries"][at] = before[entry["index"]]
    if up["entries"] and refresh:
        up["pending"] = sum(e["status"] == "pending" for e in up["entries"])
        _write(root / "web" / "upgrades.json", up)
    _write(root / "docs" / "provenance.json", seen)

    doc = root / "docs" / "CAPABILITIES.md"
    text = doc.read_text(encoding="utf-8")
    section = round_section(ev)
    if BEGIN in text:
        text = text.split(BEGIN)[0] + section + text.split(END, 1)[1]
    else:
        at = text.index("## The 0.3.14 rehearsal on devnet")
        text = text[:at] + section + "\n\n" + text[at:]
    doc.write_text(text, encoding="utf-8", newline="")
    cap.render(root)
    for line in cap.problems(_json(root / "docs" / "capabilities.json"), root):
        wrong.append(line)
        say("capabilities: " + line)
    for script, args in (("demo_data.py", []), ("provenance.py", ["--write"])):
        done = subprocess.run([sys.executable, str(root / "scripts" / script), *args], capture_output=True, text=True, encoding="utf-8", cwd=root)  # noqa: S603
        say(f"{script}: " + (done.stdout.strip().splitlines() or [done.stderr.strip()[-300:]])[0])
        if done.returncode not in (0,) and script == "demo_data.py":
            wrong.append(script)
    say((f"moved to exercised: {', '.join(moved) or 'nothing'}; versions on chain: " + ", ".join(f"{n} {NEW[n]}" for n in live)) if live
        else "no program is on its upgraded build: nothing moved")
    return 1 if wrong else 0


# ---- propose-oidc -----------------------------------------------------------------------------------------------------
def propose_oidc(url: str, keys: Path, so_dir: Path, say: Callable[[str], None] = print, account: Callable | None = None,
                 call: Callable[..., int] | None = None, root: Path = ROOT) -> int:
    """Proposes the knos_oidc build of `so_dir`, and nothing else. `call(argv, env)` runs deploy_v2.sh (the tests pass their own)."""
    import upgrade_feed as feed
    account = account or mc._rpc(url)
    rows = read_programs(account, root)
    behind = [n for n, r in rows.items() if r["is"] not in ("new", "next")]
    if behind:
        say(f"refused: {', '.join(behind)} does not run its upgraded build: proposals 3 to 6 have not all executed. Nothing was proposed.")
        return 3 if all(rows[n]["is"] == "old" for n in behind) else 1
    built = {}
    for n in PROGRAMS:
        so = so_dir / f"{n}.so"
        if not so.is_file():
            say(f"refused: {so} is missing: the verified builds of program.yml's run go there. Nothing was proposed.")
            return 1
        built[n] = gate.executable_hash(so.read_bytes()).hex()
    plan = [n for n in PROGRAMS if built[n] != rows[n]["hash"]]
    if plan != ["knos_oidc"]:
        other = [n for n in plan if n != "knos_oidc"]
        say("refused: " + (f"the build of {', '.join(other)} in {so_dir} is not the one live at the public id: this release changes knos_oidc alone. " if other else
                           "knos_oidc runs this build already: there is nothing to propose. ") + "Nothing was proposed.")
        return 1
    rec = feed.gate_record(account, rows["knos_oidc"]["id"], built["knos_oidc"])
    if rec is None:
        say(f"refused: the upgrade gate holds no record of the build {built['knos_oidc']}: it is not a verified build of program.yml. Nothing was proposed.")
        return 1
    seen = _json(root / "docs" / "provenance.json") or {}
    seen.setdefault("next", {})["knos_oidc"] = {"version": "2.2", "build_hash": built["knos_oidc"], "source_commit": rec.sha, "gate_run": rec.run_id}
    _write(root / "docs" / "provenance.json", seen)
    say(f"the plan: propose knos_oidc ({built['knos_oidc']}, built from {rec.sha} in run {rec.run_id}); the other three run the builds of {so_dir} already")
    env = {**os.environ, "KNOS_KEYS": str(keys), "KNOS_RPC": url, "KNOS_SO_DIR": str(so_dir), "KNOS_CHANGES": "knos_oidc"}
    argv = ["bash", (root / "scripts" / "deploy_v2.sh").as_posix(), "--propose"]      # bash takes / on every OS
    code = call(argv, env) if call else subprocess.run(argv, env=env, check=False).returncode  # noqa: S603
    if code:
        say(f"scripts/deploy_v2.sh --propose stopped with exit {code}: read its last lines; it can be run again")
        return code
    mine = [q for q in (_json(keys / "upgrade-schedule.json") or {}).get("proposals", []) if q.get("program") == "knos_oidc"]
    for q in mine:      # what deploy_v2.py's `schedule` wrote for scripts/schedule_upgrade.sh
        say(f"proposal {q['index']} for knos_oidc (build {q.get('hash')}, buffer {q.get('buffer')}): can be executed from "
            f"{day(int(q['executable_from']))}; scripts/schedule_upgrade.sh arranges it")
    if not mine:
        say(f"{keys / 'upgrade-schedule.json'} names no proposal for knos_oidc: read what deploy_v2.sh printed above")
    return 0


# ---- the command ------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("command", choices=("status", "run", "record", "propose-oidc", "list"))
    ap.add_argument("--rpc", help="the cluster (devnet)")
    ap.add_argument("--keys", type=Path, help="the key folder: relayer.json, funder.json, and where the evidence is kept")
    ap.add_argument("--only", help="one capability (or one round) alone")
    ap.add_argument("--resume", action="store_true", help="go on from the evidence kept; read the repository's comments again")
    ap.add_argument("--fresh", action="store_true", help="forget the evidence kept and start over")
    ap.add_argument("--again", help="forget what one round kept (its tokens and its steps) and run it with new tokens; give --since with it")
    ap.add_argument("--since", help="take only tokens issued since this time (2026-10-06T22:30:00Z); default: three days back")
    ap.add_argument("--simulate", action="store_true", help="the local simulator and the test builds, with fixture tokens")
    ap.add_argument("--out", "--evidence", dest="evidence", type=Path, help="the evidence file (default: <keys>/exercise_public.json)")
    ap.add_argument("--root", type=Path, default=ROOT, help="record: the tree to write into (a copy, for simulated evidence)")
    ap.add_argument("--so-dir", type=Path, default=Path(os.environ["KNOS_SO_DIR"]) if os.environ.get("KNOS_SO_DIR") else None)
    a = ap.parse_args(argv)
    if a.command == "list":
        for cap, how in exercisable().items():
            say(f"{cap}: {how}")
        return 0
    if a.command == "status":
        if not a.rpc:
            ap.error("status needs --rpc")
        return status(a.rpc, say)
    where = a.evidence or (a.keys / EVIDENCE if a.keys else None)
    if a.command == "propose-oidc":
        if not (a.rpc and a.keys and a.so_dir):
            ap.error("propose-oidc needs --rpc, --keys and --so-dir (or KNOS_SO_DIR)")
        return propose_oidc(a.rpc, a.keys, a.so_dir, say)
    if where is None:
        ap.error("give --keys (the evidence is kept there) or --out")
    if a.command == "record":
        ev = _json(where)
        if ev is None:
            say(f"{where} does not exist: `run` writes it")
            return 1
        refresh: Callable[[Path], None] | None = None
        if a.rpc:
            import upgrade_feed as feed
            ids = _json(ROOT / "programs-v2" / "program_ids.json")

            def refresh(root: Path) -> None:
                feed.write(root / "web", mc._rpc(a.rpc), ids, chain.Ledger(a.rpc).now(), mc._cluster(a.rpc))
        return record(ev, a.root, say, refresh)
    if a.simulate:
        w: World = Simulated()
        programs = {n: {"id": oidc.IDS[n], "hash": None, "slot": None, "build": NEW[n], "proposal": PROPOSALS[n], "is": "new"} for n in PROGRAMS}
    else:
        if not (a.rpc and a.keys):
            ap.error("run needs --rpc and --keys, or --simulate")
        code = status(a.rpc, say)
        if code == 1:
            return 1
        w, programs = Public(a.rpc, a.keys, say, a.since), read_programs(mc._rpc(a.rpc))
        if code == 3 and not any(r["is"] == "new" for r in programs.values()):
            return 3
    try:
        old = None if a.fresh or a.simulate else _json(where)
        ev = old if old and old.get("mode") == w.mode else new_evidence(w, programs)
        ev["programs"] = programs
        if a.again:
            if a.again not in ROUNDS:
                ap.error(f"--again takes a round: {', '.join(ROUNDS)}")
            ev["rounds"].pop(a.again, None)
            for cap in ROUNDS[a.again][2]:
                ev["exercises"].pop(cap, None)
        run(w, ev, a.only, say)
    finally:
        if isinstance(w, Simulated):
            w.close()
    _write(where, ev)
    say(f"wrote {where}")
    bad = [c for c, e in ev["exercises"].items() if str(e.get("status", "")).startswith("failed")]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
