"""From "staging" to "public": what the 2.1 and 1.1 builds add, run once at the PUBLIC program ids, and written down.

    python scripts/exercise_public.py status --rpc URL [--json]
    python scripts/exercise_public.py run --rpc URL --keys DIR [--only CAPABILITY] [--resume] [--again ROUND --since TIME]
    python scripts/exercise_public.py note ROUND --keys DIR key=value ...     what a step done outside this script printed
    python scripts/exercise_public.py record --keys DIR --rpc URL
    python scripts/exercise_public.py rehearse --rc --rpc URL --keys DIR --live-so-dir DIR --so-dir DIR [--resume]
    python scripts/exercise_public.py propose --rpc URL --keys DIR --so-dir DIR
    python scripts/exercise_public.py run --simulate --out FILE          the same rounds on a local simulator
    python scripts/exercise_public.py rehearse --rc --simulate           the same rehearsal on a local simulator
    python scripts/exercise_public.py record --simulate --evidence FILE --root COPY

status   hashes the executable of each of the four public programs the way docs/PROVENANCE.md does (sha256 of the
         program data with its trailing zeros stripped) and says, per program: the build it runs, the proposal that
         build belongs to, and the slot of its last deployment. Exit 0: all four run the 2.1 / 1.1 builds (or a later
         build this repository names). Exit 3: an upgrade has not executed yet: skip the exercises and ship the rest;
         nothing here waits. Exit 1: anything else (a hash nobody recorded, a cluster that does not answer). `--json`
         prints the same as one object, with the exit code in `exit`.

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

A round ends one of five ways, said per capability: `exercised`; `needs run: <workflow>` (a token only a forge signs,
or a step only a person does: the line says exactly what to start); `needs time: <when>` (the chain's clock: `--resume`
after it finishes the round, and nothing waits meanwhile); `cannot: <why>` (the release run has no means to do it: it is
said and never worked around); `failed: <what>`. A step done outside this script (a browser, node, a pull request) is
written down with `note` and then held to the chain: the transaction exists, succeeded, and names the program at its
public id. A fee is asserted against the rule of the build the PUBLIC id runs, written out here (FEE_RULES), never
against this tree's client.

rehearse --rc   the staging rehearsal of knos_pay's new build, as one command: the LIVE builds to fresh staging ids
         (deploy_v2.sh --rc), an order funded there, the staging ids upgraded in place to this release's builds, then:
         that order still reads as written and pays; the new fee (0.30 on 100.00, the 0.05 floor on 5.00); a quorum
         of two with ONE owner for both judges moves no money; with two owners it pays (on devnet: `cannot: needs a
         second repository owner` when there is none; nothing is sent in anyone else's name); an address funded again
         in the same second is not paid by one judge (the simulator's step: devnet's clock cannot be arranged); every
         open order goes back; staging is closed. `--simulate` runs all of it on the local simulator, starting on the
         test build of the live source (tests/fixtures/live) and upgrading in place to the tree's.

propose  after proposals 3 to 6 have executed: the plan is every program whose verified build in --so-dir is not the
         build its public id runs, and it must be exactly this release's set, [knos_oidc, knos_pay] (RELEASE_CHANGES in
         scripts/provenance.py); any other plan stops it with nothing sent. Each build is held to the record the
         upgrade gate keeps on chain for its hash, its bytes to the room of its program's data account (printed), and
         both are written into docs/provenance.json (`next`). Then scripts/deploy_v2.sh --propose, and it prints each
         proposal and the time from which it can be executed; scripts/schedule_upgrade.sh arranges ONE run for both.
         `propose-oidc`, the command of the release before, says so and does the same.

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
OUTSIDE = "outside.json"                # <keys>/outside.json: what a step done outside this script left (`note` writes it)
REHEARSAL = "rehearse_rc.json"          # <keys>/rehearse_rc.json: what the staging rehearsal kept
LIVE_BUILDS = ROOT / "tests" / "fixtures" / "live_builds.json"     # the test builds made from the source that is live at the public ids
SITE = "https://drexthealpha.github.io/Knos/"
PLAYGROUND = "drexthealpha/knos-playground"
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
    """A step waits for the chain's clock: `--resume` after `until` finishes it."""
    def __init__(self, until: int, what: str):
        super().__init__(f"needs time: {day(until)}: {what}")
        self.until = until


class Cannot(Exception):
    """What the release run has no means to do, and why: said, never worked around."""


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


STATUS_SAYS = {0: "all four run the upgraded builds: run the exercises",
               3: "the upgrade has not executed for every program: skip the exercises and ship the rest; run them later (exit 3)",
               1: "unexpected: nothing is exercised or recorded until this is understood (exit 1)"}


def status(url: str, say: Callable[[str], None] = print, account: Callable | None = None, root: Path = ROOT, as_json: bool = False) -> int:
    """What each public id runs, in lines or (`as_json`) as one JSON object with the same exit code in `exit`."""
    try:
        rows = read_programs(account or mc._rpc(url), root)
    except Exception as why:  # noqa: BLE001 - a cluster that does not answer is not an answer
        if as_json:
            say(json.dumps({"exit": 1, "says": f"{url} could not be read ({type(why).__name__}: {why})", "programs": {}}, indent=1))
        else:
            say(f"stopped: {url} could not be read ({type(why).__name__}: {why})")
        return 1
    if as_json:
        code = status_code(rows)
        say(json.dumps({"exit": code, "says": STATUS_SAYS[code], "programs": rows}, indent=1))
        return code
    for name, r in rows.items():
        what = {"new": f"{name} {r['build']}, the build of proposal {r['proposal']}",
                "next": f"{name} {r['build']}, the later build docs/provenance.json names" + (f" (proposal {r['proposal']})" if r["proposal"] else ""),
                "old": f"{name} {r['build']}: proposal {PROPOSALS[name]} has not executed",
                "unknown": "a build no file of this repository records" if r["hash"] else "nothing: no program data at this id"}[r["is"]]
        say(f"{name} {r['id']}: runs {what}; hash {r['hash']}; last deployed in slot {r['slot']}")
    code = status_code(rows)
    say(STATUS_SAYS[code])
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

    def either(self, ixs, payer: Keypair | None = None) -> tuple[str, int | None]:     # pragma: no cover - overridden
        """Sends a transaction whose outcome is the question: (its signature, None when it went through or the program's error number)."""
        raise NotImplementedError

    def outside(self, name: str) -> dict | None:
        """What a step done outside this script left for the round `name` (`note` writes it), or None."""
        return None

    def consumed(self, tok: Tok, line: str) -> tuple[str, str] | None:
        """The transaction in which knos_pay took this token and itself logged a line starting with `line`, as
        (its signature, that line); None when there is none. At a public id the repository's own run carries its
        tokens to the chain before a round does, so a round finds the token's work done and its marker set: what the
        token did is then read from the transactions that set the marker, never assumed."""
        used = pay.used_pda(tok.jwt)
        for sig in self.ledger.history(used, 50):
            said = [x for x in chain.said(self.ledger.logs(sig), pay.PAY_ID) if x.startswith(line)]
            if said:
                return sig, said[0]
        return None

    def landed(self, signature: str) -> dict | None:    # pragma: no cover - overridden
        """A transaction as the chain has it: {"ok": it succeeded, "accounts": every address it names}. None: no such transaction."""
        raise NotImplementedError

    def comments(self, pull: str) -> list[str]:
        """The comments of owner/name#number, oldest first."""
        return []

    def outcome(self) -> dict | None:
        """The artifact of one run of outcome-k8s.yml: {"jwt", "jwks", "issuer", "audience"}, or None when there is none."""
        return None

    def preflight(self, ask: dict) -> dict:     # pragma: no cover - overridden
        """The report of `knos preflight --json` for {"issue": owner/name#n, "tree": a checkout, "by": a login}."""
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

    def either(self, ixs, payer: Keypair | None = None) -> tuple[str, int | None]:
        payer = payer or self.relayer
        raw = base64.b64encode(bytes(chain.sign(list(ixs), payer, None, self.ledger._blockhash()))).decode()
        sig = chain.call(self.url, "sendTransaction", [raw, {"encoding": "base64", "skipPreflight": True, "maxRetries": 5}])
        try:
            chain.wait(self.url, sig, 90.0)
        except chain.RpcError as why:
            return sig, code_of(f"{why} {why.data}") or -1
        return sig, None

    def outside(self, name: str) -> dict | None:
        return ((_json(self.keys / OUTSIDE) or {}).get(name)) or (self.cfg.get("outside") or {}).get(name)

    def landed(self, signature: str) -> dict | None:
        got = chain.call(self.url, "getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
        if not got:
            return None
        meta = got.get("meta") or {}
        more = meta.get("loadedAddresses") or {}
        named = [*got["transaction"]["message"]["accountKeys"], *more.get("writable", []), *more.get("readonly", [])]
        return {"ok": meta.get("err") is None, "accounts": sorted(set(named))}

    def comments(self, pull: str) -> list[str]:
        repo, _, number = pull.partition("#")
        done = subprocess.run(["gh", "api", "--paginate", f"repos/{repo}/issues/{int(number)}/comments", "--jq", ".[] | @json"],  # noqa: S603, S607
                              capture_output=True, text=True, encoding="utf-8", check=False)
        if done.returncode:
            raise Failed(f"the comments of {pull} could not be read: {done.stderr.strip()[-200:]}")
        return [str(json.loads(line).get("body") or "") for line in done.stdout.splitlines() if line.strip()]

    def outcome(self) -> dict | None:
        at = self.keys / "outcome"
        if not all((at / f).is_file() for f in ("token", "jwks.json", "receipt.json")):
            return None
        issuer = (at / "issuer").read_text(encoding="utf-8").strip() if (at / "issuer").is_file() else None
        return {"jwt": (at / "token").read_text(encoding="utf-8").strip(), "jwks": _json(at / "jwks.json"), "issuer": issuer,
                "audience": _json(at / "receipt.json")["audience"]}

    def preflight(self, ask: dict) -> dict:
        argv = [sys.executable, "-m", "knos", "preflight", "--issue", ask["issue"], "--tree", str(ask["tree"]), "--json", *(["--by", ask["by"]] if ask.get("by") else [])]
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", check=False, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})  # noqa: S603
        try:
            return json.loads(done.stdout)
        except ValueError:
            raise Failed(f"`knos preflight` printed no report: {(done.stderr or done.stdout).strip()[-300:]}") from None

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

    def __init__(self, pay_build: str | None = None):
        """`pay_build`: another build of knos_pay than tests/fixtures/knos_pay_v2_test.so, a path under tests/fixtures
        (the rehearsal starts on the build that is live and upgrades in place)."""
        sys.path.insert(0, str(ROOT / "tests"))
        import _meter
        import _order
        import _settle

        class Both(_meter.Meter, _order.OrderChain):
            pass
        self.fake: dict[str, Any] = {}          # what a test puts where an outside step would have left it
        self.pay_build = pay_build or "knos_pay_v2_test.so"

        self._undo = (relay.ATTESTERS, chain.__dict__.get("V1_BUDGET_IX"), os.environ.get("KNOS_NO_SAS"))
        os.environ["KNOS_NO_SAS"] = "1"                 # no attestation service is asked from a simulator
        chain.V1_BUDGET_IX = True                       # LiteSVM reads a v1 transaction's limit from a compute budget instruction
        self.o, self.m, self.s = _order, _meter, _settle
        first, keep = _order.Chain.__init__, _order.Chain.__init__.__defaults__
        first.__defaults__ = (self.pay_build, keep[1])           # the build of knos_pay the chain starts on
        try:
            c = self.c = Both()
        finally:
            first.__defaults__ = keep
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

    def upgrade(self, build: str = "knos_pay_v2_test.so") -> str:
        """knos_pay's bytes replaced in place, every account left as it is: what an upgrade does. Returns the build's hash."""
        at = ROOT / "tests" / "fixtures" / build
        self.c.svm.add_program_from_file(pay.PAY_ID, str(at))
        self.pay_build = build
        return gate.executable_hash(at.read_bytes()).hex()

    def forge(self, aud: str, file: str = "prove.yml", terms: bytes | None = None, raw: Callable[[bytes], bytes] | None = None, still: bool = False,
              **over) -> Any:
        """What GitHub would sign for a run of the pinned <file>, issued now, signed by the test key. `still`: the
        clock is not moved for it (every token before it took one second)."""
        from _pay2 import github_claims
        c = self.c
        c.warp(0 if still else 1)
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

    def either(self, ixs, payer: Keypair | None = None) -> tuple[str, int | None]:
        return self.ledger.either(list(ixs), payer or self.relayer)

    def outside(self, name: str) -> dict | None:
        if name in self.fake:
            return self.fake[name]
        return self._x402() if name == "x402" else None

    def landed(self, signature: str) -> dict | None:
        if signature not in self.ledger.said:
            return None
        return {"ok": True, "accounts": sorted(str(k) for k, sigs in self.ledger.named.items() if signature in sigs)}

    def comments(self, pull: str) -> list[str]:
        return list(self.fake.get("comments", {}).get(pull, []))

    def preflight(self, ask: dict) -> dict:
        return self.fake["report"]

    def outcome(self) -> dict | None:
        """A token signed by a stand-in for a cluster's key (tests/test_outcome_k8s.py), for the example's accepted evaluation."""
        if "outcome" in self.fake:
            return self.fake["outcome"]
        import outcome_k8s as k8s
        import test_outcome_k8s as cluster
        aud = k8s.evaluation(True).audience()
        return {"jwt": cluster.token(cluster.claims(aud, now=self.c.now())), "jwks": cluster.jwks(), "issuer": k8s.ISSUER, "audience": aud}

    def _x402(self) -> dict:
        """What `node examples/x402_attested/live.mjs run` does over RPC, done here on the simulator: a buyer's wallet
        funds an order for the seller's work, and the order's pinned workflow pays the seller when the work is accepted."""
        o, c = self.o, self.c
        n, seller, wallet = self.issue(), o.user(), Keypair.from_seed(bytes([45]) * 32).pubkey()
        order = pay.order_pda(pay.scope_of(o.REPO, n), self.funder.pubkey(), 0)
        fund = self.send([pay.fund_order_wallet_ix(self.funder.pubkey(), self.funder_token, self.mint, o.REPO, n, AMOUNT, o.WF_REPO, o.WF_SHA, o.TERMS)], self.funder)
        proof = self.forge(pay.order_pay_audience(order, o.HEAD, o.TH, pay.MERGE, 7, [(seller, 10_000, wallet)]), repository_id=o.REPO)
        r = self.submit(proof)
        if not r.get("ok"):
            raise Failed(f"the simulator's x402 order was not paid: {r.get('why')}")
        return {"fund": fund, "paid": r["sigs"][-1], "order": str(order), "seller": str(pay.ata(wallet, self.mint)), "amount": AMOUNT, "at": c.now()}


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
        self.last = sig
        if not ok:
            raise chain.RpcError(f"transaction failed: {r.err()}", {"logs": logs})
        self.said[sig], self.when[sig] = logs, self.c.now()
        for key in tx.message.account_keys:
            self.named.setdefault(key, []).append(sig)
        return sig

    def refused(self, ixs, payer) -> tuple[str, int | None]:
        return self._one(ixs, payer, None, refuse=True)

    def either(self, ixs, payer) -> tuple[str, int | None]:
        try:
            return self._one(ixs, payer, None), None
        except chain.RpcError as why:
            return self.last, code_of(why) or -1

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


def ev_status(book: Book, capability: str) -> str:
    return str(book.ev["exercises"].get(capability, {}).get("status", ""))


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


def _held(w: World, order: Pubkey) -> int:
    """What an order paid less its holdback keeps for its warranty, read from the chain: the relay's answer for a
    token another relayer carried first names what was paid and not what was held back."""
    hb = pay.read_holdback(w.account(pay.hb_pda(order)))
    return sum(amount for _i, _w, amount in hb.payees) if hb else 0


def _fund(book: Book, st: dict, key: str, tok: Tok, what: str) -> tuple[dict, Pubkey]:
    """Relays a fund token; the order is funded with its fee on top. Returns the relay's answer and the order."""
    w, f = book.w, fund_parts(tok)
    source = pay.baltok_pda(f["balance"])
    before = w.tokens(source)
    r = w.submit(tok)
    if not r.get("ok") and (took := w.consumed(tok, f"knos3:funded order={f['order']} ")):
        # the repository's run carried the token first, and its order may be paid already: the funding is the
        # transaction that set the token's marker, and what it funded is what knos_pay logged in it
        sig, line = took
        said = dict(kv.split("=", 1) for kv in line.split()[1:] if "=" in kv)
        _check(int(said.get("amount", -1)) == f["amount"] and said.get("source") == str(f["balance"]),
               f"{what}: the transaction that took the token ({sig}) funded another amount or from another Balance: {line}")
        o = pay.read_order(w.account(f["order"]))
        if o is not None and o.state == "open" and o.fee == int(said["fee"]):
            _check(w.tokens(pay.ov_pda(f["order"])) == o.amount + o.fee, f"{what}: the order does not hold its amount and its fee")
        r = {"ok": True, "already": True, "order": str(f["order"]), "amount": f["amount"], "fee": int(said["fee"]), "sigs": [sig]}
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
    if not st.get("verify") and ev_status(book, "verify_github") != "exercised":
        # the repository's run carried the fund token, so this round sent no verification of its own with the funding:
        # the one the replay above needed is knos_oidc verifying GitHub's signature on that same token at the public id
        at, _key, sigs = w.verified(t1)
        sig = sigs[-1] if sigs else next(iter(w.ledger.history(at, 5)), "")
        _check(bool(_SIG.fullmatch(sig)) and bool(have(oidc.read_token(w.account(at)), "the verified token").verified),
               "knos_oidc holds no verified account of the fund token")
        st["verify"] = sig
        book.tx(st, "knos_oidc verifies GitHub's signature on the fund token", sig, "knos_oidc")
        book.done(st, "verify_github", "knos_oidc", sig, [f"knos_oidc verified GitHub's signature on the fund token into its account {at}",
                                                          "the same token was then refused by knos_pay as a second use"])
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
    most = lambda x: max(rule(x) for _words, rule in FEE_RULES.values())    # noqa: E731  whichever build is live: never this tree's client's fee
    need = pay.MIN_AMOUNT + AMOUNT + most(AMOUNT) + USDC + most(AMOUNT + USDC)
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
        if not r.get("ok") and (took := w.consumed(first, f"knos3:quorum order={order} ")):
            r = {"ok": True, "already": True, "sigs": [took[0]]}     # the repository's run carried this judge first: its marker is that transaction's
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
        o = pay.read_order(w.account(order))
        if not r.get("ok") and o is not None and int(second.c.get("actor_id", 0)) in (o.funder_id, o.owner_id):
            st["refused_neutral"] = {"run": str(second.c.get("run_id")), "actor": int(second.c["actor_id"]), "why": str(r.get("why"))}
            raise Cannot("needs a second GitHub account: a neutral run counts toward a quorum only when someone other than the order's funder "
                         f"started it, and the run the release can start (attest.yml run {second.c.get('run_id')}) was started by the funder "
                         f"(GitHub id {second.c['actor_id']}), the only account there is. Nothing moved and nothing was sent in anyone else's name")
        _check(bool(r.get("ok")), f"the second judge: the relay answered: {r.get('why')}")
        paid, back = sum(p["amount"] for p in r["paid"]), int(r.get("held_back", 0)) or (_held(w, order) if r.get("already") else 0)
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
            raise Skip("knos_oidc with strict JSON is not live at the public id (it is proposed after the push of this release): a NaN claim is accepted until then")
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


# ---- the rounds 0.3.18 adds: what had no round at the public ids -------------------------------------------------------
def fee_tiers_21(amount: int) -> int:
    """knos_pay 2.1's fee on an order (the build of proposal 4): 2.5% of the first 1,000.00, 1% of what lies between
    1,000.00 and 50,000.00, 0.5% of what lies above, each part rounded down; at least 0.40."""
    first = min(amount, 1_000 * USDC)
    second = min(amount, 50_000 * USDC) - first
    return max(first * 250 // 10_000 + second * 100 // 10_000 + (amount - first - second) * 50 // 10_000, 400_000)


def fee_flat(amount: int) -> int:
    """The fee of the build this release proposes: 0.30% of the amount, rounded down; at least 0.05."""
    return max(amount * 30 // 10_000, 50_000)


# The rule of each build, written out here and NOT read from knos.settle.v2.pay: the tree's client follows the tree's
# program, and what a round at a public id asserts is the build that id runs ("new": proposal 4's; "next": a later one).
FEE_RULES: dict[str, tuple[str, Callable[[int], int]]] = {
    "new": ("knos_pay 2.1: 2.5% of the first 1,000.00, 1% up to 50,000.00, 0.5% above, at least 0.40", fee_tiers_21),
    "next": ("0.30% of the amount, at least 0.05", fee_flat)}
ABOVE_THE_FIRST_TIER = 1_500 * USDC


def changed_fixtures(root: Path = ROOT) -> list[str]:
    """The programs whose test build in tests/fixtures is not the one made from the source that is live
    (tests/fixtures/live_builds.json): what this tree changes, in the order the upgrades execute."""
    import hashlib
    out = []
    for name in PROGRAMS:
        held = ((_json(root / "tests" / "fixtures" / "live_builds.json") or {}).get("programs") or {}).get(name)
        at = root / "tests" / "fixtures" / str((held or {}).get("fixture"))
        if held and at.is_file() and hashlib.sha256(at.read_bytes()).hexdigest() != held["sha256"]:
            out.append(name)
    return out


def simulated_programs() -> dict[str, dict]:
    """What the simulator runs, in the words of read_programs: a program whose test build is of source that is not live
    yet is "next", the others "new"."""
    later = changed_fixtures()
    return {n: {"id": oidc.IDS[n], "hash": None, "slot": None, "build": "this tree's" if n in later else NEW[n],
                "proposal": None if n in later else PROPOSALS[n], "is": "next" if n in later else "new"} for n in PROGRAMS}


def round_fees(book: Book, st: dict) -> None:
    """A wallet funds an order above 1,000.00 for one minute of work: the fee the order holds is the one the build at
    the public id charges, read from the order's account and from where the money went; then it all goes back."""
    w = book.w
    wf_repo, wf_sha, repo = w.pin()
    funder, source = w.funder, w.funder_token
    amount = ABOVE_THE_FIRST_TIER
    words, rule = FEE_RULES["next" if book.ev["programs"].get("knos_pay", {}).get("is") == "next" else "new"]
    terms = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "mode": "merge", "v": 2})
    if "issue" not in st:
        most = amount + max(f(amount) for _words, f in FEE_RULES.values())
        if w.tokens(source) < most:
            raise Cannot(f"the funding wallet {funder.pubkey()} holds {money(w.tokens(source))} test USDC, and an order above 1,000.00 with its fee "
                         f"takes {money(most)} for one minute (it all comes back)")
        st["issue"], st["start"] = w.now(), w.tokens(source)
    order = pay.order_pda(pay.scope_of(repo, st["issue"]), funder.pubkey(), 1)        # seq 1: never the address of the expiry round's order
    if "fund" not in st:
        sig = w.send([pay.fund_order_wallet_ix(funder.pubkey(), source, w.mint, repo, st["issue"], amount, wf_repo, wf_sha, terms, work_s=pay.MIN_WORK, seq=1)], funder)
        o = have(pay.read_order(w.account(order)), "the order")
        took = st["start"] - w.tokens(source)
        _check(o.amount == amount and w.tokens(pay.ov_pda(order)) == took == amount + o.fee, "the order does not hold its amount and its fee, or they did not come from the wallet")
        _check(o.fee == rule(amount), f"the build at the public id charged {money(o.fee)} on {money(amount)}; the rule recorded for it ({words}) gives {money(rule(amount))}")
        st["fund"] = {"signature": sig, "order": str(order), "amount": amount, "fee": o.fee, "rule": words, "deadline": o.deadline}
        book.tx(st, f"a wallet funds an order of {money(amount)}: the fee on top is {money(o.fee)}", sig, "knos_pay")
        book.done(st, "fee_tiers", "knos_pay", sig, [f"an order of {money(amount)} holds a fee of {money(o.fee)} on top, read from the order's account on chain",
                                                      f"that is the rule of the build the public id runs ({words})",
                                                      f"the wallet paid {money(took)}: the amount and the fee, nothing else"])
    if "refund" not in st:
        w.wait_until(st["fund"]["deadline"], "the deadline of the order nobody proves")
        sig = w.send([pay.refund_order_ix(w.relayer.pubkey(), order, have(pay.read_order(w.account(order)), "the order"))])
        _check(w.account(order) is None and w.tokens(source) == st["start"], "the expired order did not go back whole, fee included")
        st["refund"] = {"signature": sig}
        book.tx(st, "past its deadline the order goes back to the wallet, fee included", sig, "knos_pay")


def round_holdback(book: Book, st: dict) -> None:
    """An order that holds a fifth back for a day's warranty: its proof pays four fifths, and once the warranty is
    over the holdback is released to the payee."""
    w = book.w
    sim = w if isinstance(w, Simulated) else None
    how = (f"in {w.repository}: comment `/knos fund {AMOUNT // USDC} holdback 20 warranty 1` on a new issue and merge a pull request that closes it; a day after "
           "the payment run this again with `--resume`: it sends the release itself")
    if sim and "issue" not in st:
        st["issue"], st["payee"], st["wallet"] = sim.issue(), sim.o.user(), str(Keypair.from_seed(bytes([46]) * 32).pubkey())
    options = pay.opts(holdback_bps=2000, warranty_days=1)
    wanted = lambda t: fund_parts(t)["holdback"] > 0 and not fund_parts(t)["flags"] & (order_auto.F_AUTO | order_auto.F_QUORUM)  # noqa: E731
    forge = (lambda: sim.forge(pay.order_fund_audience(st["issue"], AMOUNT, pay.MERGE, sim.o.TH, sim.c.bal, options=options), "fund.yml", sim.o.TERMS,
                               event_name="issue_comment", actor_id=sim.o.MAINT, repository_id=sim.o.REPO, repository_owner_id=sim.o.OWNER)) if sim else None
    t = book.token(st, "fund", "fund", wanted, forge, ("fund.yml", how))
    if "fund1" not in st:
        _fund(book, st, "fund1", t, "a comment funds an order that holds a fifth back for one day")
    order = Pubkey.from_string(st["fund1"]["order"])
    forge = (lambda: sim.forge(pay.order_pay_audience(order, sim.o.HEAD, sim.o.TH, pay.MERGE, 7, [(st["payee"], 10_000, Pubkey.from_string(st["wallet"]))]),
                               repository_id=sim.o.REPO)) if sim else None
    proof = book.token(st, "proof", "pay", lambda x: x.aud.startswith(f"knos3:pay:{order}:"), forge, ("prove.yml", how))
    _i, _b, named = pay.payees_of(proof.aud)[0]
    wallet = have(pay.order_destination(pay.read_bind(w.account(pay.bind_pda(_i))), named), "the payee's wallet (an address in the token, or a bound wallet)")
    dest = pay.ata(wallet, w.mint)
    if "paid" not in st:
        had = w.tokens(dest)
        r = w.submit(proof)
        _check(bool(r.get("ok")), f"the proof: the relay answered: {r.get('why')}")
        paid, back = sum(p["amount"] for p in r["paid"]), int(r.get("held_back", 0)) or (_held(w, order) if r.get("already") else 0)
        _check(paid + back == st["fund1"]["amount"] and back == st["fund1"]["amount"] * 2000 // 10_000, "the proof did not pay the order less one fifth")
        if not r.get("already"):
            _check(w.tokens(dest) - had == paid, "the payee was not paid four fifths")
        hb = have(pay.read_holdback(w.account(pay.hb_pda(order))), "the record of what is held back")
        st["paid"] = {"signature": r["sigs"][-1], "paid": paid, "held_back": back, "until": hb.until}
        book.tx(st, "the proof pays the order less its holdback; the warranty starts", r["sigs"][-1], "knos_pay")
    if "release" not in st:
        w.wait_until(st["paid"]["until"], "the end of the warranty, after which the holdback is released to the payee")
        o, hb = pay.read_order(w.account(order)), pay.read_holdback(w.account(pay.hb_pda(order)))
        if o is None or hb is None:         # another relayer's sweep released it first: its transaction is the order's newest
            sig = next(iter(w.ledger.history(order, 5)), "")
            _check(bool(_SIG.fullmatch(sig)) and w.account(order) is None, "the order is gone and no transaction of its release is found")
            said = "another relayer's sweep sent the release; the order's account is closed"
        else:
            me, had = w.relayer.pubkey(), w.tokens(dest)
            got = relay._read(w.ledger, [pay.ata(me, o.mint, o.token_program), pay.ata(pay.FEE_OWNER, o.mint, o.token_program)])
            sig = w.send([*relay._tip_accounts(me, o, got)[0], pay.release_ix(me, order, o, hb)])
            _check(w.tokens(dest) - had == st["paid"]["held_back"] and w.account(order) is None, "the holdback did not reach the payee, or the order is not closed")
            said = f"{money(st['paid']['held_back'])} reached the payee's account and the order's account is closed"
        st["release"] = {"signature": sig}
        book.tx(st, "the warranty is over: the holdback is released to the payee", sig, "knos_pay")
        book.done(st, "holdback_release", "knos_pay", sig, [f"the proof paid {money(st['paid']['paid'])} and the order kept {money(st['paid']['held_back'])} "
                                                            f"until {day(st['paid']['until'])}", said])


def round_issuer(book: Book, st: dict) -> None:
    """An outcome that is not code, signed by a Kubernetes cluster's own issuer: the token is checked offline, then
    verified by knos_oidc under the cluster's key, which this wallet registered as a private key."""
    w = book.w
    import outcome_k8s as k8s
    how = ("`gh workflow run outcome-k8s.yml`; when the run is green, `gh run download <run id> -n outcome-k8s -D <keys>/outcome`; then this again "
           "(`--resume`) within six hours of the run. It sends what `python scripts/outcome_k8s.py chain --send` sends and keeps each transaction")
    if "verified" in st:
        return
    got = w.outcome()
    if got is None:
        raise Need("outcome-k8s.yml", how)
    issuer, now = got.get("issuer") or k8s.ISSUER, w.now()
    try:
        seen = k8s.verify_token(got["jwt"], got["jwks"], issuer, now)
        k8s.spend_checks(seen["claims"], got["audience"], k8s.SUBJECT, now)
    except k8s.Refused as why:
        raise Need("outcome-k8s.yml", f"the token of <keys>/outcome is refused before any fee ({why}); a new run signs a new one. {how}") from None
    me = w.relayer.pubkey()
    held = oidc.read_key(w.account(oidc.key_pda(issuer, seen["n"], registrant=me)))
    groups, account, key = k8s.chain_groups(me, got["jwt"], seen["n"], issuer, registered=held is not None and held.state == 1)
    before = oidc.read_token(w.account(account))
    sigs: list[str] = []
    if before is None or not before.verified:
        for what, ixs in groups:
            sigs.append(w.send(ixs))
            if not what.startswith(("token bytes", "step")):
                book.tx(st, what, sigs[-1], "knos_oidc")
    sig = sigs[-1] if sigs else next(iter(w.ledger.history(account, 5)), "")
    t = have(oidc.read_token(w.account(account)), "the token's account")
    _check(bool(t.verified) and oidc.token_issuer(w.account(account)) == (oidc.issuer_hash(issuer), me),
           "the token's account is not VERIFIED under this issuer and this wallet")
    st["verified"] = {"signature": sig, "token": str(account), "key": str(key), "issuer": issuer, "transactions": sigs}
    book.tx(st, f"the cluster's token is written and verified ({len(sigs)} transactions; this is the last)", sig, "knos_oidc")
    book.done(st, "outcome_not_code", "knos_oidc", sig,
              [f"knos_oidc verified a token of the issuer {issuer}, a Kubernetes cluster's own, under a private key this wallet registered",
               f"the token's account {account} names that issuer's hash and the registrant {me}",
               "the same token passed the verifier's rule offline first; the meter does not count it on chain"])


def _on_chain(w: World, sig: str | None, programs: tuple[str, ...], also: tuple[str, ...] = ()) -> None:
    """A transaction someone else sent: it is on the cluster, it succeeded, and it names these programs at their
    pinned ids (and these addresses)."""
    _check(bool(_SIG.fullmatch(str(sig or ""))), f"`{sig}` is not a transaction's signature")
    got = w.landed(str(sig))
    _check(got is not None, f"the cluster has no transaction {sig}")
    _check(bool(have(got)["ok"]), f"the transaction {sig} failed on chain")
    for p in programs:
        _check(oidc.IDS[p] in have(got)["accounts"], f"the transaction {sig} does not name {p} at its pinned id {oidc.IDS[p]}")
    for a in also:
        _check(str(a) in have(got)["accounts"], f"the transaction {sig} does not name {a}")


def _note(w: World, name: str, keys: tuple[str, ...], workflow: str, how: str) -> dict:
    """What the outside step of round `name` left, with every key it must have; Need (with what to do) when it is not there."""
    got = w.outside(name)
    if not got:
        raise Need(workflow, how)
    lacks = [k for k in keys if not got.get(k)]
    _check(not lacks, f"the note for {name} lacks {', '.join(lacks)}: {how}")
    return got


def round_x402(book: Book, st: dict) -> None:
    """The `knos-order` scheme end to end: a buyer's wallet funds an order over RPC, is served, and the seller is paid
    when the order's pinned workflow accepts the work."""
    w = book.w
    if "paid" in st:
        return
    how = ("cp examples/x402_attested/offer.devnet.json offer.json (fill repoId, issue, wfSha, seller, delivery); `node examples/x402_attested/live.mjs run "
           "--rpc <rpc> --key <keys>/funder.json --offer offer.json`; merge the seller's pull request; when `node examples/x402_attested/live.mjs status --rpc "
           "<rpc> --order <order>` says paid: `python scripts/exercise_public.py note x402 --keys <keys> fund=<the funding signature> paid=<the payment's> "
           "order=<the order>`, then this again")
    got = _note(w, "x402", ("fund", "paid", "order"), "live.mjs", how)
    _check(got["fund"] != got["paid"], "the funding and the payment are one signature: give both")
    _on_chain(w, got["fund"], ("knos_pay",), (got["order"],))
    _on_chain(w, got["paid"], ("knos_pay",), (got["order"],))
    _check(w.account(Pubkey.from_string(got["order"])) is None, "the order is still open: it is funded and nobody is paid yet")
    said = ["the order the 402 answer offered was funded by the buyer's wallet at the public knos_pay", "a later transaction of the same order closed it"]
    if got.get("seller") and got.get("amount"):
        _check(w.tokens(Pubkey.from_string(got["seller"])) >= int(got["amount"]), "the seller's account does not hold the order's amount")
        said.append(f"the seller's account holds the {money(int(got['amount']))} the order paid")
    st["fund"], st["paid"] = {"signature": got["fund"], "order": got["order"]}, {"signature": got["paid"]}
    book.tx(st, "the buyer's wallet funds the order the 402 answer offered", got["fund"], "knos_pay")
    book.tx(st, "the work is accepted: the order pays the seller", got["paid"], "knos_pay")
    book.done(st, "x402_knos_order", "knos_pay", got["paid"], said)


def round_passkey(book: Book, st: dict) -> None:
    """A passkey funds an order from the site's Buy page: a person does it in a browser, and the transaction the page
    shows is held to the chain."""
    w = book.w
    if "fund" in st:
        return
    how = (f"in a browser with a passkey, open {SITE}#buy and press, in this order: `Create a passkey wallet`; send the address it shows "
           f"{money(AMOUNT + USDC)} test USDC and press `Check the balance`; `Sign the order with the passkey`; `Copy the comment`, then `Open the issue` and "
           "post the comment there. The relay carries it. Press `Read the order from devnet`: the page shows the funding transaction. Then `python "
           "scripts/exercise_public.py note passkey --keys <keys> fund=<that transaction>`, and this again")
    got = _note(w, "passkey", ("fund",), "the site's Buy page", how)
    _on_chain(w, got["fund"], ("knos_passkey", "knos_pay"))
    st["fund"] = {"signature": got["fund"]}
    book.tx(st, "a passkey's signature funds an order: the relay carried the comment", got["fund"], "knos_passkey")
    said = ["the transaction the Buy page showed succeeded and names knos_passkey and knos_pay at their public ids"]
    if got.get("how"):          # how the passkey and the page were had, as the note says it (a virtual authenticator is said so)
        said.append(str(got["how"]))
    for cap in ("passkey_funder", "passkey_fund_relay", "buyer_page"):
        book.done(st, cap, "knos_passkey", got["fund"], said)


def round_appeal(book: Book, st: dict) -> None:
    """A supplier contests a refusal in the playground: the order is funded at the public id, the pull request is
    refused, the author appeals, and the neutral judge answers."""
    w = book.w
    if "answer" in st:
        return
    how = (f"in {PLAYGROUND} (docs/PLAYGROUND.md): fund a test task, open a pull request for it that its terms refuse, wait for the refusal, and comment "
           "`/knos appeal <reason>` as the pull request's author. When the neutral judge has answered: `python scripts/exercise_public.py note appeal --keys "
           f"<keys> pull={PLAYGROUND}#<number> fund=<the order's funding transaction> answer=upheld` (or `answer=overturned paid=<the payment>`), then this again")
    got = _note(w, "appeal", ("pull", "fund", "answer"), "attest.yml", how)
    _check(got["answer"] in ("upheld", "overturned"), f"the appeal's answer is `{got['answer']}`: upheld or overturned")
    _on_chain(w, got["fund"], ("knos_pay",))
    said = w.comments(got["pull"])
    at = next((i for i, body in enumerate(said) if body.lstrip().lower().startswith("/knos appeal ")), None)
    _check(at is not None, f"{got['pull']} has no `/knos appeal <reason>` comment")
    if len(said) <= have(at) + 1:
        raise Need("attest.yml", f"nothing has answered the appeal on {got['pull']} yet: the neutral judge's run has not ended. Run this again after it")
    st["fund"] = {"signature": got["fund"]}
    book.tx(st, "the order whose refusal is appealed is funded at the public id", got["fund"], "knos_pay")
    checked = [f"{got['pull']}: the author's `/knos appeal` comment is there, and {len(said) - have(at) - 1} comment(s) answer it",
               "the order under appeal was funded at the public knos_pay; the money stayed where the terms put it until the answer"]
    if got["answer"] == "overturned":
        _check(bool(got.get("paid")), "an overturned refusal is paid: give paid=<the payment's signature>")
        _on_chain(w, got["paid"], ("knos_pay",))
        book.tx(st, "the neutral judge overturned the refusal: the order pays", got["paid"], "knos_pay")
        book.done(st, "supplier_appeal", "knos_pay", got["paid"], [*checked, "the neutral judge overturned the refusal and the order paid"])
    else:
        book.ev["exercises"]["supplier_appeal"] = {"status": "ran: the neutral judge upheld the refusal", "round": st["round"], "program": "knos_pay", "asserted": checked,
                                                   "note": "an upheld appeal moves no money: no transaction of its own, so the capability's stage does not move"}
    st["answer"] = got["answer"]


def round_preflight(book: Book, st: dict) -> None:
    """`knos preflight` on a change the playground's order refused before: the memory engine recalls that refusal
    under the same terms."""
    w = book.w
    if "recalled" in st:
        return
    how = (f"after a refusal in {PLAYGROUND} by a workflow of this release (the appeal round's pull request is one): check out that pull request's branch, "
           "then `python scripts/exercise_public.py note preflight --keys <keys> issue=<owner/name#the funded issue> tree=<the checkout> by=<the author's "
           "login>`, and this again")
    ask = _note(w, "preflight", ("issue", "tree"), "knos preflight", how)
    report = w.preflight(ask)
    memory = report.get("memory") or {}
    _check(bool(memory.get("on")), f"the memory engine was off, so nothing could be recalled: {memory.get('said')}")
    warned = list(memory.get("warnings") or [])
    _check(bool(warned), "the preflight recalled no earlier refusal under these terms: only a workflow of this release writes refusals into memory, and "
                         "the refusal must be under the same terms hash")
    st["recalled"] = [{"code": x.get("code"), "path": x.get("path"), "count": x.get("count"), "said": x.get("said")} for x in warned]
    book.say(f"  recalled  {warned[0].get('said')}")
    book.ev["exercises"]["supplier_preflight"] = {
        "status": "ran: a remembered refusal was recalled", "round": st["round"], "asserted": [f"terms {str(report.get('terms_hash'))[:12]}: {x.get('said')}" for x in warned],
        "note": "a preflight sends nothing: there is no transaction, so the capability's stage does not move"}


def round_gitlab(book: Book, st: dict) -> None:
    """A GitLab pipeline's token verified and a merge request's author paid: only where Knos has a project on gitlab.com."""
    project = (book.w.outside("gitlab") or {}).get("project")
    if not project:
        raise Cannot("no project: Knos has no project on gitlab.com, so no pipeline there signs a token for an order")
    raise Need("a pipeline on gitlab.com", f"in {project}: add examples/gitlab/.gitlab-ci.yml, fund an issue and merge a merge request; its job posts the token, "
                                           "and this script has no reader for GitLab's notes yet: relay it with `knos-relay` and record the payment by hand")


# name -> (the round, the programs whose upgraded build it needs, the capabilities it can exercise)
ROUNDS: dict[str, tuple[Callable[[Book, dict], None], tuple[str, ...], tuple[str, ...]]] = {
    "expiry": (round_expiry, ("knos_pay",), ("fund_from_wallet", "top_up", "refund")),
    "order": (round_order, ("knos_oidc", "knos_pay"), ("work_orders", "order_pay", "single_use_tokens", "verify_github")),
    "quorum": (round_quorum, ("knos_oidc", "knos_pay"), ("order_quorum", "neutral_attest", "order_challenge", "warranty_revert")),
    "auto": (round_auto, ("knos_oidc", "knos_pay"), ("order_auto_accept", "tests_mode")),
    "meter": (round_meter, ("knos_oidc", "knos_meter"), ("meter_batch", "meter_seller_claim")),
    "strict": (round_strict, ("knos_oidc",), ("oidc_strict_json",)),
    "fees": (round_fees, ("knos_pay",), ("fee_tiers",)),
    "holdback": (round_holdback, ("knos_oidc", "knos_pay"), ("holdback_release",)),
    "issuer": (round_issuer, ("knos_oidc",), ("outcome_not_code",)),
    "x402": (round_x402, ("knos_pay",), ("x402_knos_order",)),
    "passkey": (round_passkey, ("knos_pay", "knos_passkey"), ("passkey_funder", "passkey_fund_relay", "buyer_page")),
    "appeal": (round_appeal, ("knos_pay",), ("supplier_appeal",)),
    "preflight": (round_preflight, (), ("supplier_preflight",)),
    "gitlab": (round_gitlab, ("knos_oidc", "knos_pay"), ("verify_gitlab", "gitlab_pay")),
}
NOT_ON_CHAIN = {"fuzz_rsa_diff_target", "kani_fee_conservation", "rust_handler_tests"}      # about a program's source, with nothing to send
# what has no round here, and why: said by `run`, never guessed at
NO_ROUND = {
    "verify_any_issuer": "cannot: no issuer other than GitHub and GitLab has a key admitted on GitHub's signature at the public id, and Knos runs no such "
                         "issuer; a Kubernetes cluster's token is verified under a private key instead (the round `issuer`, capability `outcome_not_code`)",
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


def run(w: World, ev: dict, only: str | None = None, say: Callable[[str], None] = print, root: Path = ROOT) -> dict:
    """Runs every round that still has something to do. Returns the evidence, changed in place. `root`: the tree whose
    docs/capabilities.json says what is below `exercised` (the tests give the manifest of before the public round)."""
    book = Book(ev, w, say)
    plan = exercisable(root)
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
            st.pop("needs_time", None)
        except Need as need:
            why = str(need)
            say(f"  NEEDS A RUN of {need.workflow}: {need.how}")
        except Wait as wait:
            why = str(wait)
            st["needs_time"] = wait.until
            say(f"  {why}; `--resume` after it finishes this round")
        except Cannot as no:
            why = f"cannot: {no}"
            say(f"  {why}")
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
            ev["exercises"].setdefault(cap, {"status": where[6:] if where.startswith(("none: needs run", "none: cannot")) else "no round: " + where[6:]})
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


# ---- propose -----------------------------------------------------------------------------------------------------------
from provenance import RELEASE_CHANGES  # noqa: E402  the ONE proposal set of this release, in the order the upgrades execute: ("knos_oidc", "knos_pay")

NEXT_VERSION = {"knos_oidc": "2.2", "knos_pay": "2.2", "knos_meter": "1.2", "knos_passkey": "1.2"}


def propose(url: str, keys: Path, so_dir: Path, say: Callable[[str], None] = print, account: Callable | None = None,
            call: Callable[..., int] | None = None, root: Path = ROOT, changes: tuple[str, ...] = RELEASE_CHANGES) -> int:
    """Proposes this release's upgrades as one set. The plan is read, never assumed: every program whose verified build
    in `so_dir` is not the one its public id runs. It must be exactly `changes`; anything else is refused with nothing
    sent. `call(argv, env)` runs deploy_v2.sh (the tests pass their own)."""
    import upgrade_feed as feed
    account = account or mc._rpc(url)
    rows = read_programs(account, root)
    behind = [n for n, r in rows.items() if r["is"] not in ("new", "next")]
    if behind:
        say(f"refused: {', '.join(behind)} does not run its upgraded build: proposals 3 to 6 have not all executed. Nothing was proposed.")
        return 3 if all(rows[n]["is"] == "old" for n in behind) else 1
    say("proposals 3 to 6 executed: " + ", ".join(f"{n} runs {r['build']}" for n, r in rows.items()))
    built, size = {}, {}
    for n in PROGRAMS:
        so = so_dir / f"{n}.so"
        if not so.is_file():
            say(f"refused: {so} is missing: the verified builds of program.yml's run go there. Nothing was proposed.")
            return 1
        built[n], size[n] = gate.executable_hash(so.read_bytes()).hex(), so.stat().st_size
    plan = [n for n in PROGRAMS if built[n] != rows[n]["hash"]]
    want = ", ".join(changes)
    if plan != list(changes):
        other, lacks = [n for n in plan if n not in changes], [n for n in changes if n not in plan]
        say("refused: " + ("every program runs the build of " + str(so_dir) + " already: there is nothing to propose. " if not plan else "")
            + (f"the build of {', '.join(other)} in {so_dir} is not the one live at the public id, and this release changes {want} and no other. " if other else "")
            + (f"the build of {', '.join(lacks)} in {so_dir} is the one already live, and this release proposes {want} as one set: put the verified build "
               f"of this tree there. " if lacks and plan else "")
            + f"The plan would be [{', '.join(plan)}]; it must be [{want}]. Nothing was proposed.")
        return 1
    records = {}
    for n in plan:
        records[n] = feed.gate_record(account, rows[n]["id"], built[n])
        if records[n] is None:
            say(f"refused: the upgrade gate holds no record of the build {built[n]} of {n}: it is not a verified build of program.yml. Nothing was proposed.")
            return 1
    for n in plan:      # the loader refuses an Upgrade to a build larger than the program's data account
        got = account(str(mc.programdata_address(rows[n]["id"])))
        room = len(got[1]) - mc.PROGRAMDATA_HEADER if got else 0
        say(f"{n}: this build is {size[n]:,} bytes; its data account has room for {room:,} bytes: "
            + ("it fits" if size[n] <= room else f"{size[n] - room:,} bytes short, so deploy_v2.sh extends the account first (no code changes; the fee payer pays the rent)"))
    seen = _json(root / "docs" / "provenance.json") or {}
    for n in plan:
        seen.setdefault("next", {})[n] = {"version": NEXT_VERSION[n], "build_hash": built[n], "source_commit": records[n].sha, "gate_run": records[n].run_id}
    _write(root / "docs" / "provenance.json", seen)
    say("the plan: propose [" + ", ".join(plan) + "] as one set (" + "; ".join(f"{n} {built[n]}, built from {records[n].sha} in run {records[n].run_id}" for n in plan)
        + f"); {', '.join(n for n in PROGRAMS if n not in plan)} run the builds of {so_dir} already")
    env = {**os.environ, "KNOS_KEYS": str(keys), "KNOS_RPC": url, "KNOS_SO_DIR": str(so_dir), "KNOS_CHANGES": " ".join(plan)}
    argv = ["bash", (root / "scripts" / "deploy_v2.sh").as_posix(), "--propose"]      # bash takes / on every OS
    code = call(argv, env) if call else subprocess.run(argv, env=env, check=False).returncode  # noqa: S603
    if code:
        say(f"scripts/deploy_v2.sh --propose stopped with exit {code}: read its last lines; it can be run again")
        return code
    made = {q.get("program"): q for q in (_json(keys / "upgrade-schedule.json") or {}).get("proposals", [])}      # what deploy_v2.py's `schedule` wrote
    for n in plan:
        q = made.get(n)
        if q is None:
            say(f"{keys / 'upgrade-schedule.json'} names no proposal for {n}: read what deploy_v2.sh printed above")
            code = 1
            continue
        say(f"proposal {q['index']} for {n} (build {q.get('hash')}, buffer {q.get('buffer')}): can be executed from {day(int(q['executable_from']))}")
    if not code:
        both = " and ".join("proposal " + str(made[n]["index"]) for n in plan)
        say(f"next: bash scripts/schedule_upgrade.sh arranges ONE run that executes {both}, each only while its buffer holds the build above; then "
            "`knos status` shows them pending")
    return code


def propose_oidc(url: str, keys: Path, so_dir: Path, say: Callable[[str], None] = print, account: Callable | None = None,
                 call: Callable[..., int] | None = None, root: Path = ROOT) -> int:
    """The name of 0.3.16's command, kept: it says what changed and does what `propose` does."""
    say(f"`propose-oidc` is `propose` now: this release proposes {' and '.join(RELEASE_CHANGES)} as ONE set, never knos_oidc alone. Running `propose`:")
    return propose(url, keys, so_dir, say, account, call, root)


# ---- rehearse --rc: knos_pay's new build on a staging id, before it is proposed -----------------------------------------
Q2 = pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(2))
RC_TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "test"}], "mode": "merge", "v": 2})
RC_HOW = ("in the staging repository, whose workflows read the staging ids (KNOS_PROGRAM_IDS = <keys>/rc/program_ids.json): merge a pull request that closes "
          "the issue the order names so that prove.yml posts its token, and start attest.yml by hand where a second judge is asked for; then `rehearse --rc "
          "--resume`")


def _rc_work(w: World) -> int:
    """How long an order of the rehearsal that needs a workflow run stays open: an hour on devnet (it goes back at
    `close`), two weeks in the simulator, where time costs nothing."""
    return 14 * 86_400 if isinstance(w, Simulated) else 3600


def _rc_order(w: World, st: dict, seq: int) -> tuple[int, Pubkey]:
    """The issue number and the address of this step's order: a wallet's order of the round's repository."""
    if "issue" not in st:
        st["issue"] = w.issue() if isinstance(w, Simulated) else w.now()
    return st["issue"], pay.order_pda(pay.scope_of(w.pin()[2], st["issue"]), w.funder.pubkey(), seq)


def _rc_fund(w: World, st: dict, seq: int, amount: int, options: bytes | None = None, work_s: int = 14 * 86_400) -> tuple[str, Pubkey, pay.Order]:
    wf_repo, wf_sha, repo = w.pin()
    n, order = _rc_order(w, st, seq)
    before = w.tokens(w.funder_token)
    sig = w.send([pay.fund_order_wallet_ix(w.funder.pubkey(), w.funder_token, w.mint, repo, n, amount, wf_repo, wf_sha, RC_TERMS, work_s=work_s, seq=seq,
                                           options=options)], w.funder)
    o = have(pay.read_order(w.account(order)), "the order")
    _check(o.amount == amount and w.tokens(pay.ov_pda(order)) == before - w.tokens(w.funder_token) == amount + o.fee,
           "the order does not hold its amount and its fee, or they did not come from the wallet")
    return sig, order, o


def _rc_judge(book: Book, st: dict, key: str, order: Pubkey, pick: Callable[[Tok], bool], claims: dict, still: bool = False) -> Tok:
    """One judge's token for the order's work: forged in the simulator, found among the staging repository's comments on devnet."""
    w = book.w
    sim = w if isinstance(w, Simulated) else None
    if sim and "payee" not in st:
        st["payee"], st["wallet"] = sim.o.user(), str(Keypair.from_seed(bytes([50 + len(book.ev["rounds"])]) * 32).pubkey())
    forge = (lambda: sim.forge(pay.order_pay_audience(order, sim.o.HEAD, pay.terms_hash(RC_TERMS), pay.MERGE, 7, [(st["payee"], 10_000, Pubkey.from_string(st["wallet"]))]),
                               still=still, **claims)) if sim else None
    return book.token(st, key, "pay", lambda x: x.aud.startswith(f"knos3:pay:{order}:") and pick(x), forge, ("prove.yml and attest.yml", RC_HOW))


def _rc_dest(w: World, tok: Tok) -> tuple[list, Pubkey]:
    payees = pay.payees_of(tok.aud)
    wallets = [(i, pay.order_destination(pay.read_bind(w.account(pay.bind_pda(i))), a)) for i, _b, a in payees]
    return wallets, pay.ata(have(wallets[0][1], "the payee's wallet"), w.mint)


def _rc_alone(book: Book, st: dict, order: Pubkey, tok: Tok, what: str, wrong: str) -> None:
    """Shows one more token to PayOrder as the instruction itself, so that the answer is a transaction: whatever the
    program answers, no money may move and the order stays open and unpaid."""
    w = book.w
    wallets, dest = _rc_dest(w, tok)
    o = have(pay.read_order(w.account(order)), "the order")
    account, key, _ = w.verified(tok)
    had, held = w.tokens(dest), w.tokens(pay.ov_pda(order))
    sig, code = w.either([order_auto.with_quorum(pay.pay_order_ix(w.relayer.pubkey(), account, key, order, o, wallets, used=w.account(account)), order, o)])
    after = pay.read_order(w.account(order))
    _check(w.tokens(dest) == had and w.tokens(pay.ov_pda(order)) == held and after is not None and after.state == "open" and after.paid == 0, wrong)
    means = "accepted, and not counted as a second judge" if code is None else pay.ERRORS.get(code, "the program refused it")
    st["answer"] = {"signature": sig, "error": code, "means": means}
    if code is None:
        book.tx(st, f"{what}: {means}; no money moved", sig, "knos_pay")
    else:
        book.tx(st, what, sig, "knos_pay", code, means)


def rc_fund_old(book: Book, st: dict) -> None:
    """On the build that is live: a wallet funds an order, which the new build will have to pay as it finds it."""
    w = book.w
    if "fund" in st:
        return
    sig, order, o = _rc_fund(w, st, 0, AMOUNT, work_s=_rc_work(w))
    _check(o.fee == fee_tiers_21(AMOUNT), f"the staging id does not run the live build yet: it charged {money(o.fee)} on {money(AMOUNT)}, and knos_pay 2.1 charges "
                                           f"{money(fee_tiers_21(AMOUNT))}")
    st["fund"] = {"signature": sig, "order": str(order), "amount": o.amount, "fee": o.fee, "data": have(w.account(order)).hex()}
    book.tx(st, f"under the live build, a wallet funds an order of {money(o.amount)} with {money(o.fee)} on top", sig, "knos_pay")


def rc_pay_old(book: Book, st: dict) -> None:
    """After the upgrade in place: the order funded under the old build reads as it was written, and its proof pays it."""
    w = book.w
    if "paid" in st:
        return
    before = have(book.ev["rounds"].get("old_layout_fund", {}).get("fund"), "the order funded before the upgrade")
    order = Pubkey.from_string(before["order"])
    st.setdefault("issue", book.ev["rounds"]["old_layout_fund"]["issue"])
    o = have(pay.read_order(w.account(order)), "the order funded before the upgrade")
    _check(have(w.account(order)).hex() == before["data"] and (o.amount, o.fee, o.state) == (before["amount"], before["fee"], "open"),
           "the upgrade changed the order's account, or the new client reads another amount or fee from it")
    tok = _rc_judge(book, st, "proof", order, lambda x: int(x.c["repository_id"]) == w.pin()[2], {"repository_id": w.pin()[2]})
    _wallets, dest = _rc_dest(w, tok)
    had = w.tokens(dest)
    r = w.submit(tok)
    _check(bool(r.get("ok")), f"the new build did not pay the order funded under the old one: {r.get('why')}")
    _check(w.tokens(dest) - had == before["amount"] and w.account(order) is None, "the payee was not paid the order's amount, or the order is not closed")
    st["paid"] = {"signature": r["sigs"][-1], "amount": before["amount"], "fee_kept": before["fee"]}
    book.tx(st, f"the new build pays the order funded before the upgrade: {money(before['amount'])}, its fee as funded ({money(before['fee'])})", r["sigs"][-1], "knos_pay")


def rc_fees(book: Book, st: dict) -> None:
    """The new fee rule on chain: 0.30 on an order of 100.00, and the floor of 0.05 on one of 5.00."""
    w = book.w
    for seq, amount in ((3, 100 * USDC), (4, AMOUNT)):
        key = f"fee{amount // USDC}"
        if key in st:
            continue
        sig, order, o = _rc_fund(w, st, seq, amount, work_s=pay.MIN_WORK)
        st[key] = {"signature": sig, "order": str(order), "fee": o.fee, "deadline": o.deadline}
        book.tx(st, f"an order of {money(amount)} is funded with a fee of {money(o.fee)} on top", sig, "knos_pay")
        _check(o.fee == fee_flat(amount), f"this build charged {money(o.fee)} on {money(amount)}; the new rule (0.30%, at least 0.05) gives {money(fee_flat(amount))}")


def rc_one_owner(book: Book, st: dict) -> None:
    """A quorum of two, and ONE account starts both runs (its own repository's, and a neutral one in another repository
    it owns): that is one judge, and nothing is paid."""
    w = book.w
    sim = w if isinstance(w, Simulated) else None
    if "answer" in st:
        return
    _n, order = _rc_order(w, st, 5)
    if "fund" not in st:
        sig, order, o = _rc_fund(w, st, 5, AMOUNT, Q2, _rc_work(w))
        st["fund"] = {"signature": sig, "order": str(order)}
        book.tx(st, "a wallet funds an order that needs two judges", sig, "knos_pay")
    one = sim.o.OWNER if sim else None
    first = _rc_judge(book, st, "own", order, lambda x: int(x.c["repository_id"]) == w.pin()[2], {"repository_id": w.pin()[2], "actor_id": one})
    if "one" not in st:
        r = w.submit(first)
        _check(bool(r.get("ok")) and not r.get("paid"), f"the first judge was not recorded as one of two: {r.get('why') or r.get('paid')}")
        st["one"] = {"signature": r["sigs"][-1], "actor": int(first.c["actor_id"])}
        book.tx(st, "the run in the order's repository is recorded: one of two", r["sigs"][-1], "knos_pay")
    same = _rc_judge(book, st, "same", order, lambda x: int(x.c["repository_id"]) != w.pin()[2] and int(x.c["actor_id"]) == st["one"]["actor"],
                     sim.c.neutral(one) if sim else {})
    _rc_alone(book, st, order, same, "the same account's neutral run, shown as the second judge",
              "ONE account's two runs paid a quorum of two: this build does not tell judges apart by who started the run")


def rc_two_owners(book: Book, st: dict) -> None:
    """A quorum of two with two owners: the order's own run, and a neutral run another account started in a repository
    of its own. That pays."""
    w = book.w
    sim = w if isinstance(w, Simulated) else None
    if "paid" in st:
        return
    _n, order = _rc_order(w, st, 6)
    if "fund" not in st:
        sig, order, _o = _rc_fund(w, st, 6, AMOUNT, Q2, _rc_work(w))
        st["fund"] = {"signature": sig, "order": str(order)}
        book.tx(st, "a wallet funds an order that needs two judges", sig, "knos_pay")
    first = _rc_judge(book, st, "own", order, lambda x: int(x.c["repository_id"]) == w.pin()[2], {"repository_id": w.pin()[2], "actor_id": sim.o.OWNER if sim else None})
    if "one" not in st:
        r = w.submit(first)
        _check(bool(r.get("ok")) and not r.get("paid"), f"the first judge was not recorded as one of two: {r.get('why') or r.get('paid')}")
        st["one"] = {"signature": r["sigs"][-1], "actor": int(first.c["actor_id"]), "owner": int(first.c["repository_owner_id"])}
        book.tx(st, "the run in the order's repository is recorded: one of two", r["sigs"][-1], "knos_pay")
    other = lambda x: (int(x.c["repository_id"]) != w.pin()[2] and int(x.c["repository_owner_id"]) != st["one"]["owner"]  # noqa: E731
                       and int(x.c["actor_id"]) != st["one"]["actor"])
    if not sim and "other" not in st.get("tokens", {}) and w.find("pay", lambda x: x.aud.startswith(f"knos3:pay:{order}:") and other(x), None, book.taken()) is None:
        raise Cannot("needs a second repository owner: every repository the release run can start a workflow in belongs to the founder, and two runs "
                     "of one owner are one judge. Nothing was sent in a second owner's name")
    second = _rc_judge(book, st, "other", order, other, sim.c.neutral(sim.o.user()) if sim else {})
    _wallets, dest = _rc_dest(w, second)
    had = w.tokens(dest)
    r = w.submit(second)
    _check(bool(r.get("ok")), f"two owners' runs did not pay a quorum of two: {r.get('why')}")
    _check(w.tokens(dest) - had == AMOUNT and w.account(order) is None, "the second owner's run did not pay the order")
    st["paid"] = {"signature": r["sigs"][-1], "actor": int(second.c["actor_id"]), "owner": int(second.c["repository_owner_id"])}
    book.tx(st, "another account's neutral run in its own repository is the second judge: the order pays", r["sigs"][-1], "knos_pay")


def rc_same_second(book: Book, st: dict) -> None:
    """An order paid by its two judges, and its address funded again in the same second of the chain's clock: the first
    judge's marker of the order BEFORE counts for nothing, so one judge's new token alone moves no money."""
    w = book.w
    sim = w if isinstance(w, Simulated) else None
    if "answer" in st:
        return
    if sim is None:
        raise Cannot("four transactions do not land in one second of devnet's clock at will. The simulator runs this step on the same build "
                     "(`rehearse --rc --simulate`), and so does the handler test finding_a_marker_of_the_order_before_does_not_count_for_one_funded_again_in_the_same_second")
    _n, order = _rc_order(w, st, 7)
    judge = sim.o.user()
    a = _rc_judge(book, st, "own", order, lambda x: True, {"repository_id": sim.o.REPO})         # all three tokens first: none moves the clock later
    b = _rc_judge(book, st, "other", order, lambda x: True, sim.c.neutral(judge))
    again = _rc_judge(book, st, "again", order, lambda x: True, sim.c.neutral(judge))
    sig, order, o = _rc_fund(w, st, 7, AMOUNT, Q2)
    book.tx(st, "a wallet funds an order that needs two judges", sig, "knos_pay")
    wallets, dest = _rc_dest(w, a)
    for tok, what in ((a, "the first judge is recorded"), (b, "the second judge pays the order")):
        r = w.submit(tok)
        _check(bool(r.get("ok")), f"{what}: the relay answered: {r.get('why')}")
        book.tx(st, what, r["sigs"][-1], "knos_pay")
    _check(w.account(order) is None, "the two judges did not pay the first order")
    sig, order, o2 = _rc_fund(w, st, 7, AMOUNT, Q2)
    _check(o2.not_before == o.not_before, "the chain's clock moved between the two fundings: this is not the same second")
    st["second"] = {"signature": sig, "order": str(order), "not_before": o2.not_before}
    book.tx(st, "the same address is funded again in the same second", sig, "knos_pay")
    _rc_alone(book, st, order, again, "one judge's new token, alone, against the order funded again",
              "ONE judge's token paid the order funded again: the marker of the order before was counted for it")


def rc_close(book: Book, st: dict) -> None:
    """Every order still open goes back to the wallet at its deadline, fee included: nothing of the rehearsal stays."""
    w = book.w
    back = st.setdefault("refunds", {})
    for name, s in book.ev["rounds"].items():
        for key, row in s.items():
            if not isinstance(row, dict) or "order" not in row or row["order"] in back:
                continue
            order = Pubkey.from_string(row["order"])
            o = pay.read_order(w.account(order))
            if o is None or o.state != "open":
                continue
            w.wait_until(o.deadline, f"the deadline of the order of `{name}`")
            before = w.tokens(w.funder_token)
            sig = w.send([pay.refund_order_ix(w.relayer.pubkey(), order, have(pay.read_order(w.account(order)), "the order"))])
            _check(w.tokens(w.funder_token) - before == o.amount - o.paid + o.fee and w.account(order) is None, f"the order of `{name}` did not go back whole")
            back[row["order"]] = sig
            book.tx(st, f"the open order of `{name}` goes back to the wallet with its fee", sig, "knos_pay")


# name -> (the step, when it runs: before or after the staging id is upgraded in place)
RC_STEPS: dict[str, tuple[Callable[[Book, dict], None], str]] = {
    "old_layout_fund": (rc_fund_old, "before"), "old_layout_pay": (rc_pay_old, "after"), "fees": (rc_fees, "after"), "one_owner": (rc_one_owner, "after"),
    "two_owners": (rc_two_owners, "after"), "same_second": (rc_same_second, "after"), "close": (rc_close, "after")}


def rehearse_phase(w: World, ev: dict, phase: str, say: Callable[[str], None] = print) -> None:
    """The steps of one phase that are not done yet. Each step's answer is kept in ev["rounds"][step]["result"]."""
    book = Book(ev, w, say)
    for name, (fn, when) in RC_STEPS.items():
        if when != phase:
            continue
        st = ev["rounds"].setdefault(name, {"round": name})
        if st.get("result") == "ok" and name != "close":
            say(f"[{name}] done before: nothing is sent again")
            continue
        say(f"[{name}] {' '.join((fn.__doc__ or '').split())}")
        try:
            fn(book, st)
            st["result"] = "ok"
        except Need as need:
            st["result"] = str(need)
            say(f"  NEEDS A RUN of {need.workflow}: {need.how}")
        except Wait as wait:
            st["result"] = str(wait)
            say(f"  {wait}; `rehearse --rc --resume` after it")
        except Cannot as no:
            st["result"] = f"cannot: {no}"
            say(f"  cannot: {no}")
        except Failed as bad:
            st["result"] = f"failed: {bad}"
            say(f"  FAILED: {bad}")
        except Exception as bad:  # noqa: BLE001 - one step's trouble is written down; the others still run
            st["result"] = f"failed: {type(bad).__name__}: {str(bad)[:300]}"
            say(f"  FAILED: {st['result']}")
    ev["finished"] = w.now()


def rehearse_summary(ev: dict, say: Callable[[str], None] = print) -> int:
    """One line per step, and the exit code: 0 unless a step failed (`cannot` and `needs run` are said, not failures)."""
    for name in RC_STEPS:
        say(f"  {name}: {ev['rounds'].get(name, {}).get('result', 'not run')}")
    results = [str(ev["rounds"].get(name, {}).get("result", "not run")) for name in RC_STEPS]
    bad, open_ = [r for r in results if r.startswith("failed")], [r for r in results if r.startswith(("needs", "not run"))]
    say("the rehearsal FAILED: the build is not proposed until every step above is ok or cannot" if bad else
        "the rehearsal is not finished: " + str(len(open_)) + " step(s) wait; `rehearse --rc --resume`" if open_ else
        "the rehearsal passed: every step is ok, or cannot be done from here and says why")
    return 1 if bad else 0


def rehearse_simulated(say: Callable[[str], None] = print) -> tuple[dict, int]:
    """The whole rehearsal on the simulator: the chain starts on the test build of the source that is live (kept in
    tests/fixtures/live), and knos_pay is replaced in place by the tree's test build."""
    kept = ((_json(LIVE_BUILDS) or {}).get("programs") or {}).get("knos_pay", {}).get("kept")
    old = kept if kept and (ROOT / "tests" / "fixtures" / kept).is_file() else None
    w = Simulated(pay_build=old)
    try:
        ev = {"v": 1, "mode": w.mode, "kind": "rehearsal", "cluster": "simulator", "started": w.now(), "rounds": {}, "exercises": {},
              "old_build": gate.executable_hash((ROOT / "tests" / "fixtures" / w.pay_build).read_bytes()).hex()}
        say(f"staging (simulated): knos_pay runs the live source's test build {ev['old_build'][:16]}... ({w.pay_build})")
        rehearse_phase(w, ev, "before", say)
        ev["new_build"] = w.upgrade()
        say(f"upgraded in place: knos_pay runs this tree's test build {ev['new_build'][:16]}..."
            + (" (the SAME build: this tree's knos_pay is the one that is live)" if ev["new_build"] == ev["old_build"] else ""))
        rehearse_phase(w, ev, "after", say)
    finally:
        w.close()
    return ev, rehearse_summary(ev, say)


def rehearse_public(url: str, keys: Path, live_dir: Path, so_dir: Path, resume: bool, say: Callable[[str], None] = print, call: Callable[..., int] | None = None) -> int:
    """The rehearsal on devnet as one command: the live builds to fresh staging ids, an order funded there, the staging
    id upgraded in place to the builds of `so_dir`, the steps, then the staging programs closed. `call(argv, env)` runs
    one command (the tests pass their own). The steps themselves run in a process of their own, told where the staging
    programs are by KNOS_PROGRAM_IDS."""
    run = call or (lambda argv, env: subprocess.run(argv, env=env, check=False).returncode)  # noqa: S603
    base = {**os.environ, "KNOS_KEYS": str(keys), "KNOS_RPC": url}
    deploy = ["bash", (ROOT / "scripts" / "deploy_v2.sh").as_posix()]
    ids = keys / "rc" / "program_ids.json"
    me = [sys.executable, str(Path(__file__).resolve()), "rehearse", "--rc", "--rpc", url, "--keys", str(keys)]
    kept = (_json(keys / REHEARSAL) or {}) if resume else {}
    plan = [("deploy the LIVE builds to fresh staging ids", [*deploy, "--rc"], {**base, "KNOS_RC_SO_DIR": str(live_dir)}, "deployed"),
            ("before the upgrade", [*me, "--phase", "before"], {**base, "KNOS_PROGRAM_IDS": str(ids)}, "before"),
            ("upgrade the staging ids in place to this release's builds", [*deploy, "--rc"], {**base, "KNOS_RC_SO_DIR": str(so_dir)}, "upgraded")]
    for what, argv, env, mark in plan:
        if mark in kept.get("phases", []):
            say(f"{what}: done before")
            continue
        say(f"== {what}")
        code = run(argv, env)
        if code:
            say(f"stopped at `{what}` with exit {code}: read its last lines. `rehearse --rc --resume` goes on from here; `bash scripts/deploy_v2.sh --rc-close` closes staging")
            return code
        kept = _json(keys / REHEARSAL) or kept
        kept.setdefault("phases", []).append(mark)
        kept.setdefault("rounds", {})
        _write(keys / REHEARSAL, kept)
    say("== after the upgrade")
    code = run([*me, "--phase", "after"], {**base, "KNOS_PROGRAM_IDS": str(ids)})
    ev = _json(keys / REHEARSAL) or {"rounds": {}}
    waits = [n for n in RC_STEPS if str(ev["rounds"].get(n, {}).get("result", "not run")).startswith(("needs", "not run"))]
    if waits:
        say(f"staging stays open for {', '.join(waits)}: `rehearse --rc --resume` after those runs. To give up: bash scripts/deploy_v2.sh --rc-close")
        return code
    say("== close the staging programs")
    closed = run([*deploy, "--rc-close"], base)
    return code or closed


# ---- the command ------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("command", choices=("status", "run", "record", "propose", "propose-oidc", "rehearse", "note", "list"))
    ap.add_argument("words", nargs="*", help="note: the round's name, then key=value for each thing its outside step printed")
    ap.add_argument("--json", action="store_true", help="status: one JSON object (`exit` is the exit code)")
    ap.add_argument("--rc", action="store_true", help="rehearse: on staging ids (the only kind there is)")
    ap.add_argument("--phase", choices=("before", "after"), help="rehearse: one phase alone, on the ids of KNOS_PROGRAM_IDS (what `rehearse --rc` calls)")
    ap.add_argument("--live-so-dir", type=Path, default=Path(os.environ["KNOS_LIVE_SO_DIR"]) if os.environ.get("KNOS_LIVE_SO_DIR") else None,
                    help="rehearse: the verified builds that are live (program.yml's run on the v0.3.14 tag)")
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
    a = ap.parse_intermixed_args(argv)
    if a.command == "list":
        for cap, how in exercisable().items():
            say(f"{cap}: {how}")
        return 0
    if a.command == "status":
        if not a.rpc:
            ap.error("status needs --rpc")
        return status(a.rpc, say, as_json=a.json)
    where = a.evidence or (a.keys / EVIDENCE if a.keys else None)
    if a.command in ("propose", "propose-oidc"):
        if not (a.rpc and a.keys and a.so_dir):
            ap.error(f"{a.command} needs --rpc, --keys and --so-dir (or KNOS_SO_DIR)")
        return (propose if a.command == "propose" else propose_oidc)(a.rpc, a.keys, a.so_dir, say)
    if a.command == "note":
        if not (a.keys and a.words and all("=" in x for x in a.words[1:]) and a.words[0] in ROUNDS):
            ap.error("note takes --keys, a round's name and key=value pairs: note x402 --keys DIR fund=SIGNATURE paid=SIGNATURE order=ADDRESS")
        held = _json(a.keys / OUTSIDE) or {}
        held.setdefault(a.words[0], {}).update(dict(x.split("=", 1) for x in a.words[1:]))
        _write(a.keys / OUTSIDE, held)
        say(f"wrote {a.keys / OUTSIDE}: {a.words[0]} {json.dumps(held[a.words[0]], sort_keys=True)}; `run --resume --only {a.words[0]}` holds it to the chain")
        return 0
    if a.command == "rehearse":
        if a.simulate:
            ev, code = rehearse_simulated(say)
            if where:
                _write(where, ev)
                say(f"wrote {where}")
            return code
        if not (a.rpc and a.keys):
            ap.error("rehearse --rc needs --rpc and --keys (and --live-so-dir and --so-dir), or --simulate")
        if a.phase:         # one phase, in the process `rehearse --rc` started with the staging ids
            if not os.environ.get("KNOS_PROGRAM_IDS"):
                ap.error("--phase runs on staging ids only: KNOS_PROGRAM_IDS is not set (run `rehearse --rc`, which sets it)")
            w = Public(a.rpc, a.keys, say, a.since)
            w.repository = w.cfg.get("staging_repository", "drexthealpha/knos-rc")
            ev = _json(a.keys / REHEARSAL) or {}
            ev.update({"v": 1, "mode": "staging", "kind": "rehearsal", "cluster": "devnet", "ids": dict(oidc.IDS)})
            ev.setdefault("rounds", {})
            ev.setdefault("exercises", {})
            rehearse_phase(w, ev, a.phase, say)
            _write(a.keys / REHEARSAL, ev)
            return rehearse_summary(ev, say) if a.phase == "after" else int(any(str(s.get("result", "")).startswith("failed") for s in ev["rounds"].values()))
        if not (a.live_so_dir and a.so_dir):
            ap.error("rehearse --rc needs --live-so-dir (the verified builds that are live) and --so-dir (this release's verified builds)")
        return rehearse_public(a.rpc, a.keys, a.live_so_dir, a.so_dir, a.resume, say)
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
        programs = simulated_programs()
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
