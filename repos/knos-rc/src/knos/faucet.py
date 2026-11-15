"""The test USDC faucet: `/knos faucet <Solana address | passkey>` on the playground's faucet issue.

A stranger who wants to fund a task in a repository of their own holds no test USDC. This gives them a small fixed
amount of it, on Solana devnet. Test USDC has no monetary value, and every reply says so.

    python -m knos.faucet --event "$GITHUB_EVENT_PATH"      # what the worker runs for one comment
    knos faucet request <address>                            # the line to post, and where
    knos faucet status                                       # what the journal on this machine holds

THE RULES, all of them (docs/reference/FAUCET.md says the same):

    where       only on an issue labelled LABEL in knos.playground.REPO, while its owner is the playground's owner
    how much    AMOUNT (20 test USDC), one fixed amount
    how often   once per forge account per PERIOD (7 days), and once per receiving address per PERIOD
    daily cap   DAY_CAP (200 test USDC) in one UTC day, for everyone together. Circle's devnet faucet, the one source
                of this money, gives 20 USDC every 2 hours per address (https://faucet.circle.com/): 240 a day at most
    who         the anti-drain rule, from the one public call GET /users/{login}: a person's account (type User),
                opened at least MIN_AGE_DAYS (30) days ago, with at least MIN_PUBLIC (1) public repository or gist
    from what   the faucet key holds test USDC and nothing else: no SOL. It signs the transfer; the relay's key pays
                the transaction fee and the receiving account's rent. `DevnetChain` refuses to start when the faucet
                key is the fee payer, the fee owner or the guardian

TWO RUNS AT ONCE SEND ONCE. The worker runs one faucet job at a time (its concurrency group). Should two overlap all
the same, the pre-posted signature is the lock: each run posts its pending reply, then reads the issue again, and a run
that finds an EARLIER reply of the faucet's own for the same account or address sends nothing (`grant`, `held`).

JOURNALED: A RETRY NEVER SENDS TWICE. A grant is a row in the Sibyl store (knos.proof.history, category CATEGORY):

    pending     written BEFORE anything is signed. Then the transfer is signed, and its signature and the last block
                height it can land in are written to the row and to the faucet's own reply on the issue BEFORE it is
                sent. A row counts against every limit from this moment
    sent        the cluster confirmed that signature
    void        the transfer failed on chain and moved nothing; it counts against no limit

A run that finds a pending row (the same comment again, or a new comment by the same account) sends nothing new while
the journaled signature can still land: it asks the cluster about that signature. Landed: sent. Not landed and the
block height is past `last_valid`: that transfer can never land, so one new transfer is signed, journaled the same
way and sent. A runner keeps no disk between runs, so the journal travels in the faucet issue: every reply ends with
one hidden line (`MARK`), and `restore` reads the rows back from the replies the workflow's own account wrote.

NOTHING THE REQUESTER WROTE REACHES A REPLY except their address, which is base58 that decodes to 32 bytes.
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from . import playground

AMOUNT = 20_000_000                 # millionths of test USDC one grant gives
PERIOD = 7 * 86_400                 # one grant per forge account, and per receiving address, in this long
DAY_CAP = 200_000_000               # every grant of one UTC day together
MIN_AGE_DAYS = 30                   # the forge account is at least this old
MIN_PUBLIC = 1                      # and has this many public repositories or gists
LABEL = "faucet"                    # the label of the one issue the faucet answers on
CATEGORY = "faucet"                 # the journal's category in the Sibyl store
BOT = "github-actions[bot]"         # whose replies carry the journal
NOTE = "Test USDC has no monetary value."
MARK = "<!-- knos-faucet 1 "        # then one JSON object and " -->": the row, in the faucet's own reply
FORM = "/knos faucet <your Solana address | passkey>"
DOC = "https://github.com/drexthealpha/Knos/blob/main/docs/reference/FAUCET.md"
WHERE = f"https://github.com/{playground.REPO}/issues?q=is%3Aissue+is%3Aopen+label%3A{LABEL}"

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_LINE = re.compile(r"^[ \t]*/knos[ \t]+faucet(?:[ \t]+(\S+))?[ \t]*$", re.I | re.M)
_LOGIN = re.compile(r"[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}")
_ROW = re.compile(re.escape(MARK) + r"(\{[^\n]{2,600}\}) -->")
_COUNTED = ("pending", "sent")


def address_ok(text: object) -> bool:
    """A Solana address: base58 that decodes to exactly 32 bytes (the rule of knos.commands.address_ok)."""
    if not isinstance(text, str) or not 32 <= len(text) <= 44 or any(ch not in _B58 for ch in text):
        return False
    n = 0
    for ch in text:
        n = n * 58 + _B58.index(ch)
    return n > 0 and len(text) - len(text.lstrip("1")) + (n.bit_length() + 7) // 8 == 32


def read(body: object) -> str | None:
    """The argument of the first `/knos faucet` line in a comment: an address, "passkey", "" when the line names
    neither, None when the comment has no such line."""
    hit = _LINE.search(str(body or "")[:20_000])
    if hit is None:
        return None
    word = hit.group(1) or ""
    return "passkey" if word.lower() == "passkey" else word if address_ok(word) else ""


def units(n: int) -> str:
    return f"{n // 1_000_000}.{n % 1_000_000 // 10_000:02d}"


def _stamp(at: float) -> str:
    return datetime.datetime.fromtimestamp(at, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _day(at: float) -> str:
    return datetime.datetime.fromtimestamp(at, datetime.timezone.utc).strftime("%Y-%m-%d")


def _unix(stamp: object) -> float | None:
    try:
        return datetime.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


# ---- the anti-drain rule ---------------------------------------------------------------------------------------------
def account_rule(user: object, now: float) -> str:
    """Why this forge account gets nothing ("" when it may ask). `user` is GET /users/{login}, one unauthenticated call."""
    if not isinstance(user, dict) or not user.get("id"):
        return "GitHub did not say who this account is. Comment again."
    if user.get("type") != "User":
        return "The faucet gives to a person's account, not to a bot or an organisation."
    made = _unix(user.get("created_at"))
    if made is None:
        return "GitHub did not say when this account was opened. Comment again."
    if now - made < MIN_AGE_DAYS * 86_400:
        return f"The faucet gives to accounts at least {MIN_AGE_DAYS} days old. This one may ask from {_stamp(made + MIN_AGE_DAYS * 86_400)}."
    if int(user.get("public_repos") or 0) + int(user.get("public_gists") or 0) < MIN_PUBLIC:
        return "The faucet gives to accounts with at least one public repository or gist. Make one, then comment again."
    return ""


# ---- the journal -----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Ask:
    """One request: who (the forge's own account id, never the login alone), where to, and the comment it came in."""
    request: str            # "github:<comment id>": the same comment is the same request
    account: int
    to: str
    forge: str = "github"


def _name(request: str) -> str:
    return "faucet-" + re.sub(r"[^A-Za-z0-9]+", "-", request)[:80]


def rows(store) -> list[dict]:
    """Every journal row, oldest first."""
    found = [r for r in store.all(CATEGORY) if r.get("kind") == "faucet" and r.get("request")]
    return sorted(found, key=lambda r: (int(r.get("at") or 0), str(r["request"])))


def _write(store, row: dict) -> dict:
    store.put(CATEGORY, _name(row["request"]), row)
    return row


def marker(row: dict) -> str:
    """The hidden line a reply ends with: the row, in a form `restore` reads back. Only numbers, a state word, an
    address and a signature: nothing free."""
    keep = {k: row[k] for k in ("request", "forge", "account", "to", "units", "state", "sig", "last_valid", "at") if k in row}
    return MARK + json.dumps(keep, sort_keys=True, separators=(",", ":")) + " -->"


def _sound(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    return (isinstance(row.get("request"), str) and 0 < len(row["request"]) <= 80 and isinstance(row.get("account"), int)
            and address_ok(row.get("to")) and row.get("units") == AMOUNT and row.get("state") in ("pending", "sent", "void")
            and isinstance(row.get("at"), int) and isinstance(row.get("sig", ""), str) and isinstance(row.get("last_valid", 0), int))


def restore(store, comments, bot: str = BOT) -> int:
    """Load the rows the faucet's own replies carry into the store; how many were new or newer. `comments` is the
    issue's comments, oldest first: the last word about a request wins, and a comment by anyone but `bot` is not read.
    What the store already says is never taken back: sent stays sent."""
    have = {r["request"]: r for r in rows(store)}
    rank = {"pending": 0, "void": 1, "sent": 2}
    n = 0
    for c in comments or []:
        user = c.get("user") if isinstance(c, dict) else None
        if not isinstance(user, dict) or user.get("login") != bot:
            continue
        for found in _ROW.findall(str(c.get("body") or "")):
            try:
                row = json.loads(found)
            except ValueError:
                continue
            if not _sound(row):
                continue
            old = have.get(row["request"])
            if old is None or rank[row["state"]] > rank[old["state"]] or (row["state"] == old["state"] == "pending" and row.get("sig") and row.get("sig") != old.get("sig")):
                have[row["request"]] = _write(store, {"kind": "faucet", "forge": "github", **row})
                n += 1
    return n


def refuses(store, ask: Ask, user: object, now: float, holds: int | None = None) -> str:
    """Why a NEW grant is not made ("" when it may be). The journal only: nothing is signed or sent here."""
    if not address_ok(ask.to):
        return f"That is not a Solana address. Write `{FORM}`."
    why = account_rule(user, now)
    if why:
        return why
    if isinstance(user, dict) and int(user.get("id") or 0) != ask.account:
        return "GitHub named another account for this login. Comment again."
    counted = [r for r in rows(store) if r.get("state") in _COUNTED]
    for r in counted:
        if now - int(r["at"]) < PERIOD and (r.get("to") == ask.to or (r.get("forge") == ask.forge and r.get("account") == ask.account)):
            whose = "This account" if r.get("account") == ask.account else "This address"
            return f"{whose} had test USDC from the faucet on {_stamp(int(r['at']))}. One grant per {PERIOD // 86_400} days: ask again after {_stamp(int(r['at']) + PERIOD)}."
    if sum(int(r["units"]) for r in counted if _day(int(r["at"])) == _day(now)) + AMOUNT > DAY_CAP:
        return f"The faucet gave its {units(DAY_CAP)} test USDC for today (UTC). Ask again tomorrow."
    if holds is not None and holds < AMOUNT:
        return "The faucet is empty until it is filled again. Ask again tomorrow."
    return ""


# ---- sending ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Signed:
    sig: str                # the transfer's signature, known before it is sent
    last_valid: int         # the last block height it can land in
    raw: object             # what `submit` takes


class Chain(Protocol):
    def holds(self) -> int: ...                                 # test USDC the faucet key holds, in millionths
    def sign(self, to: str, amount: int) -> Signed: ...         # signs, sends nothing
    def submit(self, signed: Signed) -> None: ...
    def status(self, sig: str) -> str: ...                      # "landed", "failed" or "unknown"
    def height(self) -> int: ...
    def bound(self, account: int) -> str | None: ...            # the address this account bound with /knos address


@dataclass(frozen=True)
class Outcome:
    state: str              # "sent", "pending", "refused"
    reply: str
    row: dict | None = None


def _words(row: dict) -> str:
    to, amount = row["to"], units(int(row["units"]))
    if row["state"] == "sent":
        return (f"Knos: {amount} test USDC sent to `{to}`. {NOTE}\n\nTransaction: https://explorer.solana.com/tx/{row['sig']}?cluster=devnet\n\n"
                f"Next: install the workflow in your own repository, then comment `/knos fund 5` on an issue there ({DOC}).\n\n{marker(row)}")
    return (f"Knos: {amount} test USDC is on its way to `{to}`. {NOTE} Nothing more is needed; if this reply does not change within "
            f"ten minutes, comment `/knos faucet {to}` again and the same transfer is checked, never sent twice.\n\n{marker(row)}")


def no(why: str) -> Outcome:
    return Outcome("refused", f"Knos: nothing was sent. {why} {NOTE}")


def grant(store, chain: Chain, ask: Ask, user: object, now: float, noted: Callable[[dict], None] | None = None,
          waits: int = 0, sleep: Callable[[float], None] | None = None, held: Callable[[dict], bool] | None = None) -> Outcome:
    """One request, start to end. `noted(row)` is called after the row holds a signature and BEFORE that transfer is
    sent: the worker posts the pending reply there, so the journal is outside this machine first. `waits`: how many
    times to ask for the signature after sending, `sleep(2.0)` between (none in tests).

    THE LOCK. `held(row)` is asked after `noted` and before the transfer leaves: True when another run holds this
    account or this address already (`answer` reads the issue again: an earlier reply of the faucet's own carries a
    signature for it). Then this run sends nothing and takes its row back. Two runs that overlap both post their
    signature first and both look again, so the later reply always sees the earlier one: one of them sends. When the
    question cannot be answered, nothing is sent either."""
    mine = [r for r in rows(store) if r.get("state") == "pending" and (r["request"] == ask.request or (r.get("forge") == ask.forge and r.get("account") == ask.account))]
    done = next((r for r in rows(store) if r["request"] == ask.request and r.get("state") == "sent"), None)
    if done is not None:
        return Outcome("sent", _words(done), done)
    if mine:
        row = dict(mine[-1])                # the grant in flight: its address, not this comment's
        if row.get("sig"):
            said = chain.status(row["sig"])
            if said == "landed":
                row = _write(store, {**row, "state": "sent"})
                return Outcome("sent", _words(row), row)
            if said == "failed":
                _write(store, {**row, "state": "void"})
                return no("The transfer failed on devnet and moved nothing. Comment again.")
            if chain.height() <= int(row.get("last_valid") or 0):
                return Outcome("pending", _words(row), row)        # it can still land: nothing new is signed
    else:
        try:
            holds = chain.holds()
        except Exception:  # noqa: BLE001 - not knowing is not "it holds enough"
            return no("Devnet did not say what the faucet holds. Comment again in a minute.")
        why = refuses(store, ask, user, now, holds)
        if why:
            return no(why)
        row = _write(store, {"kind": "faucet", "request": ask.request, "forge": ask.forge, "account": ask.account, "to": ask.to,
                             "units": AMOUNT, "state": "pending", "at": int(now)})
    try:
        signed = chain.sign(row["to"], int(row["units"]))
    except Exception:  # noqa: BLE001 - nothing was signed, so nothing can land: the row is taken back
        _write(store, {**row, "state": "void"})
        return no("Devnet did not answer, so no transfer was made. Comment again in a minute.")
    row = _write(store, {**row, "sig": signed.sig, "last_valid": int(signed.last_valid)})
    if noted is not None:
        noted(row)
    if held is not None:
        try:
            taken = bool(held(row))
        except Exception:  # noqa: BLE001 - not knowing whether another run sends is not "none does"
            _write(store, {**row, "state": "void"})
            return no("GitHub did not answer, so the faucet could not see whether this request is being sent already. Comment again in a minute.")
        if taken:
            _write(store, {**row, "state": "void"})
            return no("Another request for this account or this address is being sent already: its reply is above. One grant per "
                      f"{PERIOD // 86_400} days.")
    try:
        chain.submit(signed)
    except Exception:  # noqa: BLE001 - it may or may not have left: the signature in the journal is how the next run finds out
        return Outcome("pending", _words(row), row)
    for i in range(waits + 1):
        said = chain.status(signed.sig)
        if said == "landed":
            row = _write(store, {**row, "state": "sent"})
            return Outcome("sent", _words(row), row)
        if said == "failed":
            _write(store, {**row, "state": "void"})
            return no("The transfer failed on devnet and moved nothing. Comment again.")
        if i < waits and sleep is not None:
            sleep(2.0)
    return Outcome("pending", _words(row), row)


# ---- one comment on the faucet issue ---------------------------------------------------------------------------------
def is_faucet_issue(event: dict, devnet: bool = True) -> bool:
    """Whether this event is a new comment on the playground's faucet issue (the name, the owner's id and the label)."""
    repo, issue = event.get("repository") or {}, event.get("issue") or {}
    owner = (repo.get("owner") or {}).get("id")
    return (event.get("action") == "created" and isinstance(event.get("comment"), dict) and "pull_request" not in issue
            and playground.is_playground(str(repo.get("full_name") or ""), owner, devnet)
            and any(isinstance(lb, dict) and lb.get("name") == LABEL for lb in issue.get("labels") or []))


def answer(event: dict, github, store, chain: Chain, now: float, post: Callable[[str], Any], edit: Callable[[Any, str], None],
           waits: int = 0, sleep: Callable[[float], None] | None = None, bot: str = BOT) -> Outcome | None:
    """Answer one comment: None when it is not for the faucet. `github(path)` reads GitHub; `post(text)` writes a reply
    and returns what `edit(that, text)` takes. The journal is restored from the issue first, the pending reply is
    posted before the transfer leaves, and the same reply is edited to say how it ended."""
    if not is_faucet_issue(event):
        return None
    comment, issue = event["comment"], event["issue"]
    who = comment.get("user") or {}
    word = read(comment.get("body"))
    login = str(who.get("login") or "")
    if word is None or who.get("login") == bot or not _LOGIN.fullmatch(login):
        return None
    repo = event["repository"]["full_name"]
    since = datetime.datetime.fromtimestamp(now - PERIOD - 86_400, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    def comments() -> list:
        page, seen = 1, []
        while page <= 20:
            got = github(f"repos/{repo}/issues/{int(issue['number'])}/comments?since={since}&per_page=100&page={page}")
            if not isinstance(got, list):
                raise ValueError("not a list")
            seen += got
            if len(got) < 100:
                break
            page += 1
        return seen
    try:
        restore(store, comments(), bot)
        user = github(f"users/{login}")
    except Exception:  # noqa: BLE001 - without the journal nothing is sent
        out: Outcome = no("GitHub did not answer, so the faucet could not read its own journal. Comment again in a minute.")
        post(out.reply)
        return out
    account = int(who.get("id") or 0)
    if word == "":
        out = no(f"Write `{FORM}`: the address is 32 to 44 letters and digits, as your wallet shows it.")
    else:
        to: str | None = word
        if word == "passkey":
            try:
                to = chain.bound(account)
            except Exception:  # noqa: BLE001
                to = None
        if not to:
            out = no("This account has bound no address or passkey yet. Write the address itself: the Buy page shows your passkey wallet's.")
        else:
            posted: list = []
            request = f"github:{int(comment['id'])}"

            def held(row: dict) -> bool:
                """Whether an EARLIER reply of the faucet's own carries a grant in flight, or made, for this account or
                address under another request: the issue is read again, now that this run's own signature is posted."""
                mine = posted[0] if posted else None
                for c in comments():
                    who_, cid = c.get("user") if isinstance(c, dict) else None, c.get("id") if isinstance(c, dict) else None
                    if not isinstance(who_, dict) or who_.get("login") != bot or cid == mine or (isinstance(mine, int) and isinstance(cid, int) and cid > mine):
                        continue
                    for found in _ROW.findall(str(c.get("body") or "")):
                        try:
                            other = json.loads(found)
                        except ValueError:
                            continue
                        if (_sound(other) and other["request"] != request and other["state"] in _COUNTED and now - int(other["at"]) < PERIOD
                                and (other["to"] == row["to"] or other["account"] == account)):
                            return True
                return False
            out = grant(store, chain, Ask(request, account, to), user, now,
                        noted=lambda row: posted.append(post(_words(row))), waits=waits, sleep=sleep, held=held)
            if posted:
                edit(posted[0], out.reply)
                return out
    post(out.reply)
    return out


# ---- devnet ----------------------------------------------------------------------------------------------------------
class DevnetChain:
    """The Chain on a cluster. The faucet key (KNOS_FAUCET_KEY) signs as the owner of its test USDC and pays nothing;
    `payer` (the relay's key) pays the fee and the receiving account's rent."""

    def __init__(self, ledger, faucet, payer, mint=None):
        from .settle.v2 import pay
        self.pay, self.ledger, self.faucet, self.payer = pay, ledger, faucet, payer
        self.mint = mint or pay.USDC_DEVNET
        if faucet.pubkey() in (payer.pubkey(), pay.FEE_OWNER, pay.GUARDIAN):
            raise ValueError("the faucet key must be a key of its own: not the fee payer, the fee owner or the guardian")
        self.source = pay.ata(faucet.pubkey(), self.mint)

    def ixs(self, to: str, amount: int) -> list:
        """Create the receiver's token account if it has none, then TransferChecked (6 decimals) from the faucet's."""
        from solders.instruction import AccountMeta, Instruction
        from solders.pubkey import Pubkey
        owner = Pubkey.from_string(to)
        dest = self.pay.ata(owner, self.mint)
        move = Instruction(self.pay.TOKEN, b"\x0c" + int(amount).to_bytes(8, "little") + b"\x06",
                           [AccountMeta(self.source, False, True), AccountMeta(self.mint, False, False), AccountMeta(dest, False, True),
                            AccountMeta(self.faucet.pubkey(), True, False)])
        return [self.pay.create_ata_ix(self.payer.pubkey(), owner, self.mint), move]

    def _call(self, method: str, params: list):
        from . import chain
        return chain.call(self.ledger.url, method, params)

    def holds(self) -> int:
        got = self.ledger.infos([self.source])[0]
        return int.from_bytes(got[1][64:72], "little") if got and len(got[1]) >= 72 else 0

    def sign(self, to: str, amount: int) -> Signed:
        from solders.hash import Hash

        from . import chain
        latest = self._call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]
        tx = chain.sign(self.ixs(to, amount), self.payer, [self.faucet], Hash.from_string(latest["blockhash"]))
        return Signed(str(tx.signatures[0]), int(latest["lastValidBlockHeight"]), tx)

    def submit(self, signed: Signed) -> None:
        self.ledger._submit(signed.raw)

    def status(self, sig: str) -> str:
        try:
            got = self._call("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])["value"][0]
        except Exception:  # noqa: BLE001
            return "unknown"
        if not got:
            return "unknown"
        if got.get("err"):
            return "failed"
        return "landed" if got.get("confirmationStatus") in ("confirmed", "finalized") else "unknown"

    def height(self) -> int:
        return int(self._call("getBlockHeight", [{"commitment": "confirmed"}]))

    def bound(self, account: int) -> str | None:
        got = self.ledger.infos([self.pay.bind_pda(account)])[0]
        bind = self.pay.read_bind(got[1]) if got else None
        return str(bind.wallet) if bind else None


def _faucet_key():
    import os

    from . import chain
    text = os.environ.get("KNOS_FAUCET_KEY") or ""
    if not text:
        raise SystemExit("KNOS_FAUCET_KEY is not set: the faucet's own key, which holds test USDC and nothing else.")
    return chain._keypair(text)


def _store(root):
    from .proof import history
    return history.SibylStore.local(root, "knos-faucet")


def main(argv: list[str] | None = None) -> int:
    """`python -m knos.faucet --event FILE [--home DIR]`: answer the comment in a GitHub event. The relay's GitHub token writes the reply."""
    import argparse
    import time
    from pathlib import Path

    p = argparse.ArgumentParser(prog="knos.faucet")
    p.add_argument("--event", required=True)
    p.add_argument("--home", default="")
    a = p.parse_args(argv)
    event = json.loads(Path(a.event).read_text(encoding="utf-8"))
    if not is_faucet_issue(event) or read(event["comment"].get("body")) is None:
        print("not a faucet request: nothing done")
        return 0
    from . import chain, paths
    from .proof import ghrelay
    forge = ghrelay.Hub()               # reads and writes as GH_TOKEN, as the relay does
    repo, number = event["repository"]["full_name"], int(event["issue"]["number"])
    where = f"repos/{repo}/issues/{number}/comments"
    out = answer(event, forge.get, _store(Path(a.home) if a.home else paths.home() / "faucet"),
                 DevnetChain(chain.ledger(), _faucet_key(), chain.key()), time.time(),
                 post=lambda text: forge.send(where, {"body": text})["id"],
                 edit=lambda cid, text: forge.send(f"repos/{repo}/issues/comments/{int(cid)}", {"body": text}, "PATCH"),
                 waits=30, sleep=time.sleep)
    print(out.state if out else "not a faucet request: nothing done")
    return 0


def register(app: Any, help_lines: list | None = None) -> None:
    """`knos faucet request | status`, on the main app. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")

    if help_lines is not None:
        help_lines.append(("faucet", "For money", "Test USDC for a first task of your own: the line to post, and what the faucet gave."))
    sub = typer.Typer(help=f"Test USDC from the faucet, on devnet. {NOTE}", no_args_is_help=True)
    app.add_typer(sub, name="faucet", rich_help_panel="For money")

    @sub.command("request")
    def request_(to: str = typer.Argument(..., help="your Solana address, or the word passkey for the address your account bound")) -> None:
        """Print the comment that asks for test USDC, and where to post it. Sends nothing."""
        if to.lower() != "passkey" and not address_ok(to):
            typer.echo("That is not a Solana address (32 bytes in base58, as your wallet shows it).", err=True)
            raise typer.Exit(2)
        typer.echo(f"/knos faucet {'passkey' if to.lower() == 'passkey' else to}")
        typer.echo(f"Post that line as a comment on the faucet issue: {WHERE}")
        typer.echo(f"It gives {units(AMOUNT)} test USDC, once per account per {PERIOD // 86_400} days. {NOTE}")

    @sub.command("status")
    def status_(home: str = typer.Option("", "--home", help="the faucet journal's folder (default: KNOS_HOME/faucet)")) -> None:
        """What the journal on this machine holds: one line per grant, then today's total against the daily cap."""
        import time
        from pathlib import Path

        from . import paths
        found = rows(_store(Path(home) if home else paths.home() / "faucet"))
        for r in found:
            typer.echo(f"{_stamp(int(r['at']))}  {r['state']:<8} {units(int(r['units']))} test USDC  account {r['account']}  to {r['to']}")
        today = sum(int(r["units"]) for r in found if r.get("state") in _COUNTED and _day(int(r["at"])) == _day(time.time()))
        typer.echo(f"Today (UTC): {units(today)} of {units(DAY_CAP)} test USDC. {NOTE}")


if __name__ == "__main__":
    raise SystemExit(main())
