"""What people tell Knos in a comment: one line that starts with `/knos`.

    /knos fund <amount> [checks: a, b] [paths: glob, ...] [days N] [reserve N]     (alias: /knos bounty)
                        and, for a work order: [warranty N] [holdback N] [arbiter @login] [neutral off] [auto] [quorum 2|3]
                        [judge: owner/repo]
    /knos offer @vendor rate <amount> budget <amount> [checks: a, b] [paths: glob, ...] [days N]
    /knos raise <amount>    /knos cancel    /knos split @a 60 @b 40
    /knos take          /knos release       /knos address <address>      /knos mine
    /knos pay @login    /knos reject [reason]   /knos tip <amount>       /knos settle
    /knos status        /knos help

`parse` reads a comment (or a new issue's description) and gives the command as a typed value, an Error that carries
the reply to post, or None when no line of it starts with `/knos`. `reply` writes the answer for every outcome:
understood, an unknown command (it lists the commands), a malformed one (it shows the exact form to type), one from
someone who may not use it (it says who may, and what this person can do instead), and one in the wrong place.
Every `/knos` comment gets a reply, and no reply ever starts with `/knos`.

Reading is generous about spacing and case and strict about everything that moves money: an amount is digits with at
most 6 decimals, and an address is 32 bytes in canonical base58. Whether the commenter may give the command is not
decided here (knos.who decides from what GitHub authenticates; the chain decides who may spend a balance).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DAYS, MAX_DAYS = 14, 90                             # until an unpaid bounty goes back; knos-pay's MAX_WORK
RESERVE, MAX_RESERVE = 7, 90                        # days a `/knos take` lasts
MIN_UNITS, MAX_UNITS = 1_000_000, 100_000_000_000   # knos-pay's MIN_AMOUNT and MAX_AMOUNT, in millionths
MAX_BUDGET = 1_000_000_000_000                      # a standing offer's budget as written; the escrow's own cap is said at funding
MONEY = "test USDC"                                 # what devnet's money is called, everywhere


@dataclass(frozen=True)
class Fund:
    units: int                                  # millionths of the token (USDC has 6 decimals)
    checks: tuple[str, ...] | None = None       # None: none named, the repository decides; (): `checks: none`
    paths: tuple[str, ...] = ()
    days: int = DAYS
    reserve: int = RESERVE
    warranty: int | None = None                 # a work order's: days a share of each payment waits; None: the repository's policy decides
    holdback: int | None = None                 # that share, in percent
    arbiter: str | None = None                  # the login of whoever rules on a dispute
    neutral: bool | None = None                 # False: only the funder's repository may sign the payment (`neutral off`)
    auto: bool = False                          # `auto`: the first pull request that passes the black-box suite is paid, without a merge
    quorum: int | None = None                   # `quorum 2` or `quorum 3`: that many distinct judges must pass the same pull request
    judge: str | None = None                    # `judge: owner/repo`: the third reader of a quorum, a repository neither side owns
    name = "fund"


@dataclass(frozen=True)
class Offer:
    """A standing offer to one vendor: `rate` for each accepted change of theirs, out of `budget`."""
    vendor: str
    rate: int
    budget: int
    checks: tuple[str, ...] | None = None
    paths: tuple[str, ...] = ()
    days: int = DAYS
    reserve = 0                                 # an offer is one vendor's: there is nothing to reserve
    name = "offer"

    @property
    def units(self) -> int:
        """What goes into escrow: the whole budget."""
        return self.budget


@dataclass(frozen=True)
class Raise:
    units: int
    name = "raise"


@dataclass(frozen=True)
class Cancel:
    name = "cancel"


@dataclass(frozen=True)
class Take:
    name = "take"


@dataclass(frozen=True)
class Release:
    name = "release"


@dataclass(frozen=True)
class Address:
    address: str
    name = "address"


@dataclass(frozen=True)
class Mine:
    name = "mine"


@dataclass(frozen=True)
class Pay:
    login: str
    name = "pay"


@dataclass(frozen=True)
class Split:
    shares: tuple[tuple[str, int], ...]         # (login, percent), one to four, adding up to 100
    name = "split"


@dataclass(frozen=True)
class Reject:
    reason: str = ""
    name = "reject"


@dataclass(frozen=True)
class Tip:
    units: int
    name = "tip"


@dataclass(frozen=True)
class PasskeyFund:
    """`/knos passkey-fund <base64url>`: a funding a passkey signed on the site's Buy page. Not typed by hand, so it is
    not in FORMS: `intent` is what knos.settle.v2.passkey_fund.read_intent reads, and a relay sends it."""
    intent: str
    name = "passkey-fund"


@dataclass(frozen=True)
class Settle:
    name = "settle"


@dataclass(frozen=True)
class Status:
    name = "status"


@dataclass(frozen=True)
class Help:
    name = "help"


@dataclass(frozen=True)
class Error:
    """A `/knos` line that is not a command as written. `reply` is what to post back."""
    kind: str               # unknown | malformed | misplaced
    reply: str
    command: str = ""       # the command it tried to be, when that much was understood


FORMS = {   # the exact form to type, in the order `/knos help` lists them
    "fund": "/knos fund <amount> [checks: a, b] [paths: glob, ...] [days N] [reserve N]",
    "offer": "/knos offer @vendor rate <amount> budget <amount> [checks: a, b] [paths: glob, ...] [days N]",
    "raise": "/knos raise <amount>",
    "cancel": "/knos cancel",
    "take": "/knos take",
    "release": "/knos release",
    "address": "/knos address <your Solana address>",
    "mine": "/knos mine",
    "pay": "/knos pay @login",
    "split": "/knos split @login <percent> [@login <percent> ...]",
    "reject": "/knos reject [reason]",
    "tip": "/knos tip <amount>",
    "settle": "/knos settle",
    "status": "/knos status",
    "help": "/knos help",
}
ALIASES = {"bounty": "fund"}
_ABOUT = {
    "fund": "a maintainer, on an issue: put a bounty on it (a work order also takes `warranty N`, `holdback N`, `arbiter @login`, `neutral off`, "
            "`auto`, `quorum 2`, `quorum 3 judge: owner/repo`)",
    "offer": "a maintainer, on an issue: a standing offer that pays one vendor for each accepted change",
    "raise": "on a funded issue: how its work order is topped up",
    "cancel": "a maintainer, on a funded issue: end its work order with 7 days' notice",
    "take": "on a funded issue: reserve it for yourself",
    "release": "on an issue you hold: give it back",
    "address": "on your pull request: where its payment goes",
    "mine": "on a pull request an agent opened for you: it is yours",
    "pay": "a maintainer, on an agent's pull request: who it pays",
    "split": "a maintainer, before merging: the people a work order pays, and the share of each",
    "reject": "a maintainer, before merging: this pull request does not take the bounty",
    "tip": "a maintainer, on a merged pull request: pay its author now",
    "settle": "on a merged pull request: try its payment again",
    "status": "what is in escrow here",
    "help": "this list",
}
_ON_PULL = {"fund": False, "offer": False, "raise": False, "cancel": False, "split": True, "take": False, "release": False, "address": True, "mine": True, "pay": True, "reject": True,
            "tip": True, "settle": True}     # where a command belongs; status and help go anywhere


# ---- reading ---------------------------------------------------------------------------------------------------------

def _line(body: str) -> str | None:
    """What follows `/knos` on the first line that starts with it. Not a line inside a code fence, a quote, or
    indented as code (those show what someone else typed), and not one inside an HTML comment (nobody sees it)."""
    from .closing import cut
    fenced = False
    for raw in cut((body or "")[:200_000]).splitlines()[:2000]:
        line = raw.replace("\u00a0", " ").rstrip()      # a no-break space is how some keyboards type a space
        text = line.lstrip(" ")
        if text.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or len(line) - len(text) > 3:
            continue
        m = re.match(r"/knos(?:[ \t]+(.*))?$", text, re.I | re.S)
        if m:
            return (m.group(1) or "").replace("\t", " ").strip()
    return None


def amount(units: int) -> str:
    """Millionths as people write them: 20, 12.5."""
    whole, part = divmod(int(units), 1_000_000)
    return f"{whole}.{part:06d}".rstrip("0") if part else str(whole)


def _units(text: str, most: int = MAX_UNITS) -> int | str:
    m = re.fullmatch(r"([0-9]{1,9})(?:\.([0-9]{1,6}))?", text)
    if not m:
        return "the amount is digits with at most 6 decimals, like 20 or 12.5"
    units = int(m.group(1)) * 1_000_000 + int((m.group(2) or "0").ljust(6, "0"))
    if not MIN_UNITS <= units <= most:
        return f"the amount must be from {amount(MIN_UNITS)} to {amount(most)}"
    return units


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def address_ok(text: str) -> bool:
    """A Solana address: base58 that decodes to exactly 32 bytes, written the one way those bytes are written."""
    if not isinstance(text, str) or not 32 <= len(text) <= 44 or any(ch not in _B58 for ch in text):
        return False
    n = 0
    for ch in text:
        n = n * 58 + _B58.index(ch)
    zeros = len(text) - len(text.lstrip("1"))
    return n > 0 and zeros + (n.bit_length() + 7) // 8 == 32     # all zeros is nobody's wallet


def _show(text: str, most: int = 40) -> str:
    """Someone's text, safe to say back: one line, no markup, no mention, short."""
    return re.sub(r"[^A-Za-z0-9 _.,:;/#()*+=?!'\"-]", "", str(text))[:most].strip()


_LOGIN = r"[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}"
_OPTION = re.compile(r"(checks|paths)\s*:|(days|reserve|warranty|holdback|quorum)\s*:?\s*([0-9]{1,4})(?!\S)|(review)\s+[0-9]+(?!\S)"
                     r"|(arbiter)\s*:?\s*@?(" + _LOGIN + r")(?!\S)|(neutral)\s*:?\s*(on|off)(?!\S)"
                     r"|(rate|budget)\s*:?\s*([0-9.]{1,16})(?!\S)|(auto)(?!\S)"
                     r"|(judge)\s*:?\s*(?:https://github\.com/)?(" + _LOGIN + r"/[A-Za-z0-9._-]{1,100})(?!\S)", re.I)
_RANGE = {"days": (1, MAX_DAYS), "reserve": (0, MAX_RESERVE), "warranty": (0, 90), "holdback": (0, 50), "quorum": (2, 3)}     # knos-pay's limits
_FUND_TAKES = ("checks", "paths", "days", "reserve", "warranty", "holdback", "arbiter", "neutral", "auto", "quorum", "judge")
_OFFER_TAKES = ("checks", "paths", "days", "rate", "budget")


def _list(text: str, i: int) -> tuple[list[str] | str, int]:
    """The comma-separated names from text[i:] up to the next option. A comma inside brackets belongs to the name
    (`test (ubuntu, 3.12)`); a name in double quotes or backticks is taken whole."""
    items, cur, depth, quote = [], [], 0, ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
            else:
                cur.append(ch)
        elif ch in '"`' and not "".join(cur).strip():
            quote = ch
        elif ch == "," and not depth:
            items.append("".join(cur))
            cur = []
        elif ch == " " and not depth and _OPTION.match(text, i + len(text[i:]) - len(text[i:].lstrip(" "))):
            break
        else:
            depth += (ch in "([{") - (ch in ")]}" and depth > 0)
            cur.append(ch)
        i += 1
    if quote or depth:
        return "a name's quote or bracket is not closed", i
    items.append("".join(cur))
    return list(dict.fromkeys(x.strip() for x in items if x.strip())), i


def _options(text: str, takes: tuple[str, ...] = _FUND_TAKES) -> dict | str:
    out: dict = {}
    i = 0
    while i < len(text):
        if text[i] == " ":
            i += 1
            continue
        m = _OPTION.match(text, i)
        if not m:
            word = text[i:].split()[0]
            if word.lower().rstrip(":") in _RANGE:
                return f"`{word.lower().rstrip(':')}` needs a whole number after it, like `days 30`"
            if word.lower().rstrip(":") in ("arbiter", "neutral", "rate", "budget", "judge"):
                return {"judge": "`judge` needs a repository after it, like `judge: owner/repo`", "arbiter": "`arbiter` needs a GitHub login after it, like `arbiter @octocat`", "neutral": "`neutral` is `neutral off` or `neutral on`",
                        "rate": "`rate` needs an amount after it, like `rate 12`", "budget": "`budget` needs an amount after it, like `budget 100`"}[word.lower().rstrip(":")]
            return f"`{_show(word)}` is not something this command takes"
        if m.group(4):
            return "there is no `review` any more (once a payment is made it is final)"
        key = (m.group(1) or m.group(2) or m.group(5) or m.group(7) or m.group(9) or m.group(11) or m.group(12)).lower()
        if key not in takes:
            return f"`{key}` is not something this command takes"
        if key in out:
            return f"`{key}` is written twice"
        if m.group(2):
            low, high = _RANGE[key]
            if not low <= int(m.group(3)) <= high:
                return f"`{key}` must be from {low} to {high}"
            out[key], i = int(m.group(3)), m.end()
            continue
        if m.group(11):         # a bare word: `auto`
            out[key], i = True, m.end()
            continue
        if m.group(12):         # `judge: owner/repo`: GitHub is asked for it at funding (knos.flow)
            out[key], i = m.group(13), m.end()
            continue
        if m.group(5) or m.group(7):
            out[key], i = (m.group(6) if m.group(5) else m.group(8).lower() == "on"), m.end()
            continue
        if m.group(9):
            units = _units(m.group(10), MAX_UNITS if key == "rate" else MAX_BUDGET)     # what one order may hold is the chain's to say
            if isinstance(units, str):
                return f"`{key}`: {units}"
            out[key], i = units, m.end()
            continue
        items, i = _list(text, m.end())
        if isinstance(items, str):
            return items
        if not items:
            return f"`{key}:` needs at least one name after it" + (", or `checks: none`" if key == "checks" else "")
        if key == "checks":
            if any(len(x) > 200 for x in items):
                return "a check's name is at most 200 characters"
            out[key] = () if [x.lower() for x in items] == ["none"] else tuple(items)
        else:
            from .terms import Refused, valid_glob
            try:
                out[key] = tuple(dict.fromkeys(valid_glob(re.sub(r"^(?:\./|/)+", "", g)) for g in items))
            except Refused:
                return "a path is a glob from the repository's root, like `src/**` or `docs/*.md`"
    return out


def _bad(name: str, why: str) -> Error:
    return Error("malformed", reply("malformed", name, why=why), name)


def _fund(rest: str):
    first, _, more = rest.partition(" ")
    units = _units(first) if first else "the amount is missing"
    if isinstance(units, str):
        return _bad("fund", units)
    options = _options(more)
    return _bad("fund", options) if isinstance(options, str) else Fund(units, **options)


def _offer(rest: str):
    first, _, more = rest.partition(" ")
    m = re.fullmatch("@(" + _LOGIN + ")", first)      # the @ is required: `rate` and `budget` are logins too
    if not m:
        return _bad("offer", "name the vendor's GitHub account first, like `/knos offer @acme-agents rate 12 budget 100`")
    options = _options(more, _OFFER_TAKES)
    if isinstance(options, str):
        return _bad("offer", options)
    if "rate" not in options or "budget" not in options:
        return _bad("offer", "an offer says what one accepted change is paid (`rate 12`) and the most it pays in all (`budget 100`)")
    if options["rate"] > options["budget"]:
        return _bad("offer", "the budget is under the rate: it could not pay for one change")
    return Offer(m.group(1), **options)


def _raise(rest: str):
    units = _units(rest) if rest else "the amount is missing"
    return _bad("raise", units) if isinstance(units, str) else Raise(units)


def _split(rest: str):
    pairs = re.findall(r"@?(" + _LOGIN + r")\s+([0-9]{1,3})%?(?:\s*,)?(?=\s|$)", rest)
    if not pairs or re.sub(r"@?" + _LOGIN + r"\s+[0-9]{1,3}%?(?:\s*,)?(?=\s|$)", "", rest).strip():
        return _bad("split", "name each person and their share in percent, like `/knos split @ana 60 @ben 40`")
    shares = tuple((login, int(pct)) for login, pct in pairs)
    if len(shares) > 4 or len({login.lower() for login, _ in shares}) != len(shares):
        return _bad("split", "a work order pays one to four people, each named once")
    if any(pct < 1 for _, pct in shares) or sum(pct for _, pct in shares) != 100:
        return _bad("split", f"the shares must add up to 100, and these add up to {sum(pct for _, pct in shares)}")
    return Split(shares)


def _tip(rest: str):
    units = _units(rest) if rest else "the amount is missing"
    return _bad("tip", units) if isinstance(units, str) else Tip(units)


def _address(rest: str):
    if not address_ok(rest):
        return _bad("address", "that is not a Solana address (32 bytes in base58, as your wallet shows it)")
    return Address(rest)


def _pay(rest: str):
    m = re.fullmatch("@?(" + _LOGIN + ")", rest)
    return Pay(m.group(1)) if m and len(m.group(1)) <= 39 else _bad("pay", "name one GitHub account")


_PASSKEY_FUND = re.compile(r"passkey-fund(?: +(\S*))?", re.I)     # its one argument is longer than any typed command's line


def _passkey_fund(line: str, on_pull: bool | None):
    """The line after `/knos`, when its word is passkey-fund: the intent whole, or what to do instead."""
    text = (_PASSKEY_FUND.fullmatch(line) or [None, None])[1] or ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{300,6000}", text):
        return Error("malformed", "Knos: that passkey funding line is not whole (it was cut, or text was added to it), so nothing was funded. "
                     "Sign again on the Buy page and paste the line exactly as it is shown, alone in a comment.", "passkey-fund")
    return Error("misplaced", reply("misplaced", "passkey-fund"), "passkey-fund") if on_pull else PasskeyFund(text)


def _bare(kind):
    return lambda rest: kind() if not rest else _bad(kind.name, "nothing goes after it")


_READ = {"fund": _fund, "offer": _offer, "raise": _raise, "cancel": _bare(Cancel), "split": _split, "take": _bare(Take), "release": _bare(Release), "address": _address, "mine": _bare(Mine),
         "pay": _pay, "reject": lambda rest: Reject(rest[:200].strip()), "tip": _tip, "settle": _bare(Settle),
         "status": _bare(Status), "help": lambda rest: Help()}


def parse(body: str, on_pull: bool | None = None):
    """The command in a comment or an issue's description: a Fund, Take, Release, Address, Mine, Pay, Reject, Tip,
    Settle, Status or Help; an Error whose `reply` says what to type instead; or None when no line starts with
    `/knos`. The command word is read in any case, and a bare `/knos` is `/knos help`.

    `on_pull` says where the comment is (True: on a pull request; False: on an issue). Given it, a command in the
    wrong place (an issue's command on a pull request, or the other way round) is an Error of kind misplaced."""
    line = _line(body)
    if line is None:
        return None
    if _PASSKEY_FUND.match(line) and line[12:13] in ("", " "):
        return _passkey_fund(line, on_pull)
    if len(line) > 1000:
        return Error("malformed", reply("malformed", why="that line is too long to be a command"))
    word, _, rest = line.partition(" ")
    if not word:
        return Help()
    name = ALIASES.get(word.lower(), word.lower())
    if name not in _READ:
        return Error("unknown", reply("unknown", word=word))
    command = _READ[name](rest.strip())
    if on_pull is not None and not isinstance(command, Error) and _ON_PULL.get(name, on_pull) != bool(on_pull):
        return Error("misplaced", reply("misplaced", name), name)
    return command


# ---- answering -------------------------------------------------------------------------------------------------------

def _name(command) -> str:
    return command if isinstance(command, str) else getattr(command, "name", "") or ""


def _commands() -> str:
    return "\n".join(f"- `{form}`: {_ABOUT[name]}" for name, form in FORMS.items())


_WHO = {
    "fund": "the repository's owner and the people they let spend its balance",
    "offer": "the repository's owner and the people they let spend its balance",
    "cancel": "people with write access to this repository",
    "split": "people with write access to this repository",
    "tip": "the repository's owner and the people they let spend its balance",
    "pay": "people with write access to this repository",
    "reject": "people with write access to this repository",
    "mine": "a person named in this pull request's assignees, when a bot account opened it",
    "address": "the person this pull request pays",
    "release": "the person who holds the issue",
    "take": "people, not bot accounts",
}
_INSTEAD = {
    "fund": "You can ask them to fund it: they comment `/knos fund 20` on the issue.",
    "offer": "You can ask them: they comment `/knos offer @you rate 12 budget 100` on the issue.",
    "cancel": "The order runs until its deadline; `/knos status` shows it.",
    "split": "You can ask a maintainer to name the shares before the merge.",
    "tip": "You can ask them: they comment `/knos tip 5` on the merged pull request.",
    "pay": "If an agent opened this pull request for you and you are one of its assignees, comment `/knos mine`.",
    "reject": "You can say in a review why it should not be merged; a maintainer decides.",
    "mine": "A maintainer can name you instead: they comment `/knos pay @you` on the pull request.",
    "address": "If another pull request pays you, comment `/knos address <your Solana address>` on that one.",
    "release": "Nothing changed. A maintainer can change the issue's assignee.",
    "take": "The person who runs the agent can take the issue from their own account.",
}


def _understood(command, facts: dict) -> str:
    name, money = _name(command), facts.get("money", MONEY)
    paid = facts.get("paid") or {}
    if name == "fund":
        from . import terms as terms_
        told = [*terms_.describe(facts["terms"], facts.get("source", "")), *(facts.get("notes") or [])] if facts.get("terms") else []
        about = " ".join(told) + " " if told else ""
        where = f" for issue #{facts['issue']}" if facts.get("issue") else ""
        return (f"Knos: {amount(command.units)} {money}{where}. {about}If it is not paid within {command.days} days, the "
                "money goes back to where it came from. Next: the bounty is opened on Solana, and Knos confirms here.")
    if name == "tip":
        to = f" to @{facts['login']}" if facts.get("login") else ""
        return (f"Knos: a tip of {amount(command.units)} {money}{to} for this merged pull request. Next: it is paid on "
                "Solana, and Knos confirms here.")
    if name == "address":
        who = f"@{facts['login']}'s" if facts.get("login") else "The"
        return (f"Knos: noted. {who} payment for this pull request goes to {command.address}, unless a wallet is bound "
                "to that GitHub account (a bound wallet comes first). Do not edit that comment: an edited comment does "
                "not count. To change the address, post a new one.")
    if name in ("mine", "pay"):
        if paid.get("id"):
            return f"Knos: noted. This pull request pays @{paid.get('login')}: {paid.get('why')}."
        return f"Knos: nobody is paid for this pull request yet: {paid.get('why', 'nothing names a person')}. {paid.get('fix', '')}".strip()
    if name == "reject":
        by = f" by @{facts['login']}" if facts.get("login") else ""
        why = f": {_show(command.reason, 200)}" if _show(command.reason, 200) else ""
        return (f"Knos: noted. This pull request does not take the bounty (rejected{by}{why}). It can still be merged. "
                "To undo, delete that comment.")
    if name == "settle":
        return "Knos: trying this pull request's payment again. The result follows here."
    if name == "help":
        return "Knos acts on the first line of a comment that starts with `/knos`:\n" + _commands()
    return "Knos: " + str(facts.get("text") or f"understood `/knos {name}`.")     # take, release, status: the caller's words


def reply(kind: str, command=None, **facts) -> str:
    """The comment Knos answers a `/knos` line with.

        understood    `command` is the parsed value. Facts: fund: issue, and terms, source, notes (knos.terms.build);
                      tip: login; address: login; mine and pay: paid (knos.who.payee after the comment); reject: login;
                      take, release and status: text (knos.who.take and release give theirs ready); money
        unknown       word: what was typed where a command goes
        malformed     why: what is wrong, in a few words. Shows the exact form to type
        not_allowed   who and instead replace the usual "who may" and "what you can do instead"
        misplaced     an issue's command on a pull request, or the other way round (`parse` with `on_pull`)

    `command` may be the parsed value, its class, or its name."""
    name = _name(command)
    if kind == "understood":
        return _understood(command, facts)
    if kind == "unknown":
        said = _show(facts.get("word", ""), 20)
        return (f"Knos: `{said}` is not a command." if said else "Knos: that is not a command.") + " These are:\n" + _commands()
    if kind == "malformed":
        why = f": {facts['why']}" if facts.get("why") else ""
        form = f" Type it like this: `{FORMS[name]}`" + (", for example `/knos fund 20`." if name == "fund" else ".") \
            if name in FORMS else " `/knos help` lists the commands."
        return f"Knos: that was not understood{why}.{form}"
    if kind == "not_allowed":
        who = facts.get("who") or _WHO.get(name, "someone else")
        return f"Knos: `/knos {name}` is for {who}. {facts.get('instead') or _INSTEAD.get(name, '')}".strip()
    if kind == "misplaced":
        here, there = ("an issue", "the pull request") if _ON_PULL.get(name) else ("a pull request", "the issue")
        return f"Knos: `/knos {name}` belongs on {there}, not on {here}. Comment it there."
    raise ValueError(f"no such outcome: {kind}")
