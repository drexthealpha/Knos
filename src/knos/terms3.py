"""Knos Terms 3: acceptance as a versioned contract (docs/TERMS.md, "Knos Terms 3").

A terms 3 document is one JSON object that answers ten questions, each in a required field that holds the facts
and one plain line (`says`) written from those facts by this module, so a line cannot say one thing while the facts
say another:

    deliverable   what one deliverable is, and how a retry is told from a new one
    evidence      whose signature counts: which issuers, which workflows
    checks        the tests or checks that decide, and where their authoritative copy lives
    window        how long accepted work can be reopened (the warranty), and what is held meanwhile
    changes       which paths may change, which are protected, what a contributor may add without authority
    dispute       who may appeal, to which evaluator, by when, and where the money stays meanwhile
    evaluators    who may judge: each an issuer and a repository and workflow; for a quorum, that their owners differ
    price         the amount and the currency
    deadline      how long the order is open, and what happens to a token presented late
    policy        who may publish a new version, and how a version is cited

    validate(doc)      the document with every `says` line written; raises Missing (which field) or Refused (why)
    digest(doc)        its version: the sha256 of its canonical bytes
    order_terms(doc)   the 600-byte terms an order is funded on (knos.terms), which carry `contract`: this digest
    check_order(...)   what an order's options say that the document does not: [] when the order is the document's
    diff(a, b)         what changed between two versions, one plain sentence a difference, each tagged with its field

The older formats are not touched: a file published as Knos Terms 1 keeps its bytes and its hash, and an order
funded on it stays valid. Money on devnet is test USDC.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import terms

STANDARD = "Knos Terms 3"
V = 3
GITHUB = "https://token.actions.githubusercontent.com"
GITLAB = "https://gitlab.com"
ISSUERS = {GITHUB: "GitHub Actions", GITLAB: "GitLab CI"}
MONEY = "test USDC"
NOT_BUILT = "not built: needs a signing system of record"
ANYONE = "*"            # an evaluator's repository or owner: any, as long as it is neither party's
MAX_AMOUNT = 100_000 * 10**6
MAX_DAYS = 365

# the ten questions, in the order a buyer reads them: (field, the question, what the field must name)
FIELDS = (
    ("deliverable", "What is one deliverable?", "how one deliverable is told from another and from a retry"),
    ("evidence", "Whose signature counts?", "which issuers and workflows count as evidence"),
    ("checks", "What decides?", "the checks that decide and where their authoritative copy lives"),
    ("window", "How long can it be reopened?", "the reopening and warranty window"),
    ("changes", "What may change?", "the paths allowed and what a contributor may add without authority"),
    ("dispute", "Who may appeal, and to whom?", "who may appeal, to which evaluator, by when, and where money stays meanwhile"),
    ("evaluators", "Who may judge?", "the authorised evaluators, and for a quorum that their owners differ"),
    ("price", "What does it pay?", "the price and the currency"),
    ("deadline", "When does it end?", "the deadline and what happens to a token presented late"),
    ("policy", "Who may change these terms?", "who may publish a new version and how a version is cited"),
)
NAMES = tuple(f for f, _q, _w in FIELDS)
QUESTION = {f: q for f, q, _w in FIELDS}
_TOP = frozenset(("standard", "v", "name", "version", *NAMES))
_MORE = frozenset(("built", "needs"))

KINDS = {       # what one deliverable is, and what a retry of it is
    "pull-request": "One deliverable is the accepted pull request for one issue. A new commit, or another pull request for the "
                    "same issue, is a retry: the same deliverable, judged again and counted once.",
    "batch": "One deliverable is one batch file, named by its sha256. The same bytes sent again are a duplicate and counted once; "
             "changed bytes are a new attempt at the same batch number.",
    "resolution": "One deliverable is one ticket resolved. A ticket reopened inside the window is the same deliverable, not a new one.",
}
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,39}(?:/[a-z0-9][a-z0-9._-]{0,39})?", re.I)
_LOGIN = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:/[A-Za-z0-9._-]{1,60})?")
_HEX = re.compile(r"[0-9a-f]{64}")
_AMOUNT = re.compile(r"(0|[1-9][0-9]{0,5})\.[0-9]{2}")


class Refused(ValueError):
    """Not a terms 3 document. The message says which field and why, for the person who wrote it."""


class Missing(Refused):
    """A required field is absent. `fields`: every one that is, in the order of the ten questions."""

    def __init__(self, fields: list[str]):
        self.fields = list(fields)
        what = {f: w for f, _q, w in FIELDS}
        super().__init__("This terms 3 file is missing " + "; ".join(f"`{f}` ({what.get(f, 'a required field')})" for f in fields) + ".")


def _text(value, what: str, most: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > most or any(not " " <= ch <= "~" for ch in value):
        raise Refused(f"{what} is a line of plain ASCII text, at most {most} characters")
    return value.strip()


def _int(value, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Refused(f"{what} is a whole number from {low} to {high}")
    return value


def _keys(value, field: str, need: tuple, may: tuple = ()) -> dict:
    if not isinstance(value, dict):
        raise Refused(f"`{field}` is an object")
    lacking = [k for k in need if k not in value]
    extra = sorted(set(value) - set(need) - set(may) - {"says"})
    if lacking or extra:
        raise Refused(f"`{field}` names exactly: {', '.join(need)}" + (f" (and may name {', '.join(may)})" if may else "")
                      + (f". Missing: {', '.join(lacking)}" if lacking else "") + (f". Not known: {', '.join(extra)}" if extra else ""))
    return value


def _globs(value, what: str) -> list[str]:
    if not isinstance(value, list):
        raise Refused(f"{what} is a list of globs")
    try:
        return sorted({terms.valid_glob(g) for g in value})
    except terms.Refused as why:
        raise Refused(f"{what}: {why}") from None


def _issuer(value, what: str) -> str:
    if value not in ISSUERS:
        raise Refused(f"{what} is one of the issuers Knos reads: {', '.join(ISSUERS)}")
    return value


def _list(names: list[str], none: str = "none") -> str:
    return ", ".join(f"`{n}`" for n in names) if names else none


def _days(n: int) -> str:
    return f"{n} day{'' if n == 1 else 's'}"


def units(amount: str) -> int:
    """`50.00` as millionths of the token."""
    whole, cents = amount.split(".")
    return int(whole) * 10**6 + int(cents) * 10**4


# ---- each field: its facts checked and put in order, then its line ---------------------------------------------------

def _deliverable(d, _doc) -> dict:
    d = _keys(d, "deliverable", ("kind", "one_per"))
    if d["kind"] not in KINDS:
        raise Refused(f"`deliverable.kind` is one of: {', '.join(KINDS)}")
    return {"kind": d["kind"], "one_per": _text(d["one_per"], "`deliverable.one_per`", 40)}


def _evidence(d, doc) -> dict:
    d = _keys(d, "evidence", ("sources",))
    if not isinstance(d["sources"], list) or (not d["sources"] and doc.get("built", True)):
        raise Refused("`evidence.sources` lists at least one {issuer, workflow}: with none, nothing a third party signed counts")
    out = set()
    for s in d["sources"]:
        s = _keys(s, "evidence.sources[]", ("issuer", "workflow"))
        out.add((_issuer(s["issuer"], "`evidence.sources[].issuer`"), _text(s["workflow"], "`evidence.sources[].workflow`")))
    return {"sources": [{"issuer": i, "workflow": w} for i, w in sorted(out)]}


def _checks(d, _doc) -> dict:
    d = _keys(d, "checks", ("mode", "deciding", "accept", "authority"), ("image",))
    if d["mode"] not in ("merge", "tests"):
        raise Refused("`checks.mode` is merge (a maintainer's merge decides) or tests (the acceptance suite decides)")
    if not isinstance(d["accept"], str) or not re.fullmatch(r"[0-9a-f]{64}" if d["mode"] == "tests" else "", d["accept"]):
        raise Refused("`checks.accept` is the acceptance suite's sha256 in tests mode, and empty in merge mode")
    if not isinstance(d["deciding"], list):
        raise Refused("`checks.deciding` is a list of {name, app}")
    got = set()
    for c in d["deciding"]:
        c = _keys(c, "checks.deciding[]", ("name", "app"))
        got.add((_text(c["name"], "a check's name", 100), _int(c["app"], terms.ANY, 2**31 - 1, "a check's app")))
    out = {"mode": d["mode"], "deciding": [{"name": n, "app": a} for n, a in sorted(got)], "accept": d["accept"],
           "authority": _text(d["authority"], "`checks.authority`")}
    if "image" in d:
        try:
            out["image"] = terms.valid_image(d["image"])
        except terms.Refused as why:
            raise Refused(f"`checks.image`: {why}") from None
    return out


def _window(d, _doc) -> dict:
    d = _keys(d, "window", ("warranty_days", "holdback_percent"))
    days, held = _int(d["warranty_days"], 0, 365, "`window.warranty_days`"), _int(d["holdback_percent"], 0, 50, "`window.holdback_percent`")
    if bool(days) != bool(held):
        raise Refused("`window`: a warranty needs a holdback and a holdback a warranty. With nothing held, nothing can come back.")
    return {"warranty_days": days, "holdback_percent": held}


def _changes(d, _doc) -> dict:
    d = _keys(d, "changes", ("paths", "protected", "may_add"))
    out = {"paths": _globs(d["paths"], "`changes.paths`"), "protected": _globs(d["protected"], "`changes.protected`"),
           "may_add": _globs(d["may_add"], "`changes.may_add`")}
    clash = [g for g in out["may_add"] if g in out["protected"]]
    if clash:
        raise Refused(f"`changes`: {_list(clash)} is both protected and open to any contributor. It is one or the other.")
    return out


def _dispute(d, doc) -> dict:
    d = _keys(d, "dispute", ("who", "evaluator", "within_days", "money", "no_answer"), ("arbiter",))
    if d["who"] != "supplier":
        raise Refused("`dispute.who` is supplier: the pull request's author is who `/knos appeal` hears")
    if d["money"] != "order":
        raise Refused("`dispute.money` is order: an appeal moves nothing, and the money stays in the order until its deadline")
    if d["no_answer"] != "refund-at-deadline":
        raise Refused("`dispute.no_answer` is refund-at-deadline: with no verdict by the deadline the program returns the money to its funder")
    out = {"who": "supplier", "evaluator": _text(d["evaluator"], "`dispute.evaluator`", 40),
           "within_days": _int(d["within_days"], 1, MAX_DAYS, "`dispute.within_days`"), "money": "order", "no_answer": "refund-at-deadline"}
    arbiter = d.get("arbiter", "")
    if arbiter:
        if not isinstance(arbiter, str) or not _LOGIN.fullmatch(arbiter):
            raise Refused("`dispute.arbiter` is a GitHub login")
        out["arbiter"] = arbiter.lstrip("@")
    mode = (doc.get("checks") or {}).get("mode") if isinstance(doc.get("checks"), dict) else None
    if out["evaluator"] == "arbiter":
        if mode == "tests":
            raise Refused("`dispute.evaluator`: an order decided by an acceptance suite is appealed to an evaluator who runs it again, not to an arbiter")
    else:
        names = [e.get("name") for e in (doc.get("evaluators") or {}).get("list", []) if isinstance(e, dict)] if isinstance(doc.get("evaluators"), dict) else []
        if out["evaluator"] not in names:
            raise Refused(f"`dispute.evaluator` names one of `evaluators.list` ({', '.join(str(n) for n in names) or 'none listed'}), or `arbiter`")
        if mode == "merge":
            raise Refused("`dispute.evaluator`: an order paid on a merge has no suite to run again, so its appeal goes to `arbiter`")
        if "arbiter" in out:
            raise Refused("`dispute.arbiter` goes with `dispute.evaluator: arbiter`")
    return out


def _evaluators(d, doc) -> dict:
    d = _keys(d, "evaluators", ("quorum", "list"), ("related",))
    quorum = _int(d["quorum"], 1, 3, "`evaluators.quorum`")
    if not isinstance(d["list"], list) or (not d["list"] and doc.get("built", True)):
        raise Refused("`evaluators.list` names at least one evaluator")
    rows, seen = [], set()
    for e in d["list"]:
        e = _keys(e, "evaluators.list[]", ("name", "issuer", "repository", "workflow", "owner"))
        name = _text(e["name"], "an evaluator's name", 40)
        if name in seen or name == "arbiter":
            raise Refused(f"`evaluators.list`: the name `{name}` is taken")
        seen.add(name)
        repo, owner = _text(e["repository"], "an evaluator's repository", 100), _text(e["owner"], "an evaluator's owner", 40)
        if repo != ANYONE and (not _NAME.fullmatch(repo) or "/" not in repo or repo.split("/")[0].lower() != owner.lower()):
            raise Refused(f"evaluator `{name}`: its repository is owner/name and its owner is that owner, or both are `*` (anyone's but the parties')")
        if (repo == ANYONE) != (owner == ANYONE):
            raise Refused(f"evaluator `{name}`: repository and owner are both `*`, or neither")
        rows.append({"name": name, "issuer": _issuer(e["issuer"], f"evaluator `{name}`'s issuer"), "repository": repo,
                     "workflow": _text(e["workflow"], f"evaluator `{name}`'s workflow"), "owner": owner})
    owners = [r["owner"].lower() for r in rows]
    if quorum > 1 and (len(rows) < quorum or len(set(owners)) < quorum):
        raise Refused(f"`evaluators`: a quorum of {quorum} needs {quorum} evaluators whose owners differ; these have "
                      f"{len(set(owners))} owner{'' if len(set(owners)) == 1 else 's'} ({', '.join(sorted(set(owners))) or 'none'}). "
                      "Two judges with one owner are one judge.")
    out = {"quorum": quorum, "list": sorted(rows, key=lambda r: r["name"])}
    if "related" in d:      # optional (0.3.19): accounts the parties declare to be one party. Terms without it are the terms they were
        out["related"] = _related(d["related"])
    return out


def _related(value) -> list[list[int]]:
    """`evaluators.related` in its one written form: groups of account ids (the forge's numeric ids) that are one party,
    merged where they overlap, in rising order (knos.receipt.related). An empty list is not written: leave the key out."""
    from . import receipt
    try:
        groups = receipt.related(value)
    except ValueError:
        groups = []
    if not groups:
        raise Refused("`evaluators.related` lists the accounts declared to be one party, by their numeric ids: [[7001, 8002], ...]. "
                      "With none to declare, leave the key out.")
    return groups


def declared(doc: dict) -> list[list[int]]:
    """The control relationships a terms 3 document declares (`evaluators.related`), for knos.receipt.build5 and
    assurance_of; [] for terms that declare none. Two evaluators the terms declare related never count as two."""
    return [list(g) for g in validate(doc, strict=False)["evaluators"].get("related", [])]


def _price(d, _doc) -> dict:
    d = _keys(d, "price", ("amount", "currency"))
    if not isinstance(d["amount"], str) or not _AMOUNT.fullmatch(d["amount"]) or not 0 < units(d["amount"]) <= MAX_AMOUNT:
        raise Refused("`price.amount` is written like 50.00, above zero and at most 100000.00")
    if d["currency"] != MONEY:
        raise Refused(f"`price.currency` is {MONEY}: the only money an order holds today, on Solana devnet")
    return {"amount": d["amount"], "currency": MONEY}


def _deadline(d, _doc) -> dict:
    d = _keys(d, "deadline", ("days", "late"))
    if d["late"] != "refused":
        raise Refused("`deadline.late` is refused: the program refuses a token presented after the deadline, and nothing here can say otherwise")
    return {"days": _int(d["days"], 1, MAX_DAYS, "`deadline.days`"), "late": "refused"}


def _policy(d, _doc) -> dict:
    d = _keys(d, "policy", ("may_change", "how"))
    if not isinstance(d["may_change"], list) or not d["may_change"]:
        raise Refused("`policy.may_change` lists who may publish a new version: at least one login or team")
    who = set()
    for login in d["may_change"]:
        if not isinstance(login, str) or not _LOGIN.fullmatch(login):
            raise Refused("`policy.may_change` holds GitHub logins or teams, like @octocat or @acme/platform")
        who.add("@" + login.lstrip("@"))
    if d["how"] != "new-version":
        raise Refused("`policy.how` is new-version: a version never changes, and a change is the next version with its own hash")
    return {"may_change": sorted(who), "how": "new-version"}


_READ = {"deliverable": _deliverable, "evidence": _evidence, "checks": _checks, "window": _window, "changes": _changes,
         "dispute": _dispute, "evaluators": _evaluators, "price": _price, "deadline": _deadline, "policy": _policy}


def _check(c: dict) -> str:
    return f"`{c['name']}`" + {terms.STATUS: " (a commit status)", terms.ANY: " (any source)"}.get(c["app"], f" (GitHub App {c['app']})")


_UNBUILT = {      # a template that cannot be funded: what four of its fields say instead
    "checks": "Nothing can decide yet: no third party signs that this work was done. The authoritative copy: {authority}.",
    "window": "Nothing can be paid, so nothing can be reopened.",
    "dispute": "No appeal can be heard yet: there is no evaluator to hear it.",
    "price": "Would pay {amount} {currency} for each accepted deliverable. Nothing can be funded on these terms yet.",
}


def say(field: str, d: dict, is_built: bool = True) -> str:
    """The plain line of one field, written from its facts. `validate` holds every `says` to this."""
    if not is_built and field in _UNBUILT:
        return _UNBUILT[field].format(**{k: v for k, v in d.items() if isinstance(v, str)})
    if field == "deliverable":
        return f"{KINDS[d['kind']]} There is one for each {d['one_per']}."
    if field == "evidence":
        if not d["sources"]:
            return "No evidence source exists for this kind of work yet: nothing a third party signs says it was done."
        return "Evidence counts only when signed by " + "; or by ".join(f"{ISSUERS[s['issuer']]} for a run of {s['workflow']}" for s in d["sources"]) + "."
    if field == "checks":
        by = "A maintainer's merge decides" if d["mode"] == "merge" else f"The acceptance suite decides (its files hash to {d['accept'][:12]})"
        after = (f", after {' and '.join(_check(c) for c in d['deciding'])} pass{'es' if len(d['deciding']) == 1 else ''} at the last commit"
                 if d["deciding"] else ", and no named check has to pass")
        image = f" The suite runs in the image {d['image']}." if d.get("image") else ""
        return f"{by}{after}.{image} The authoritative copy: {d['authority']}."
    if field == "window":
        if not d["warranty_days"]:
            return "Payment is final when it is made: nothing is held back, and accepted work cannot be reopened."
        return (f"{d['holdback_percent']}% of the payment waits {_days(d['warranty_days'])} in the order and goes back to the funder if the "
                "change is reverted in that time. What was already paid stays paid.")
    if field == "changes":
        only = f"Only files matching {_list(d['paths'])} may change." if d["paths"] else "Any file may change."
        guard = f" No change may touch {_list(d['protected'])}." if d["protected"] else " No path is protected."
        add = (f" Without asking, a contributor may add files matching {_list(d['may_add'])}." if d["may_add"]
               else " A contributor may add nothing outside that without the buyer's say.")
        return only + guard + add
    if field == "dispute":
        head = f"The supplier may appeal a rejection within {_days(d['within_days'])} of it, with `/knos appeal <reason>`. "
        if d["evaluator"] == "arbiter":
            who = (f"@{d['arbiter']}, the arbiter, rules, and that ruling ends the appeal. " if d.get("arbiter") else
                   "No arbiter is named, so a rejection stands unless both sides agree on one. ")
            who = "There is no suite to run again. " + who
        else:
            who = f"The evaluator `{d['evaluator']}` runs the work again itself, and its verdict ends the appeal. "
        return (head + who + "Meanwhile the money stays in the order. With no verdict by the deadline, the money goes back to its funder.")
    if field == "evaluators":
        if not d["list"]:
            return "No evaluator can be named yet: nobody signs for this kind of work."
        rows = "; ".join(f"`{e['name']}` ({ISSUERS[e['issuer']]}, workflow {e['workflow']}, in "
                         + ("any repository that neither party owns" if e["repository"] == ANYONE else f"{e['repository']}, owned by {e['owner']}") + ")"
                         for e in d["list"])
        need = "One of them is enough." if d["quorum"] == 1 else f"{d['quorum']} of them must accept the same work, and their owners differ."
        one = ("" if not d.get("related") else " Declared to be one party, so never two evaluators: "
               + "; ".join("accounts " + ", ".join(str(i) for i in g[:-1]) + f" and {g[-1]}" for g in d["related"]) + ".")
        return f"These may judge: {rows}. {need}{one}"
    if field == "price":
        return f"Pays {d['amount']} {d['currency']}, once, for an accepted deliverable. The funder pays the fee on top."
    if field == "deadline":
        return (f"The order is open for {_days(d['days'])} from funding, or less if the funder cancels, which takes 7 days' notice. "
                "A token presented after that is refused, and the money goes back to its funder.")
    if field == "policy":
        return (f"{', '.join(d['may_change'])} may publish a new version. A version never changes: a change is the next version, with its own "
                "hash, and an order keeps the version it was funded on.")
    raise KeyError(field)


def validate(doc, strict: bool = True) -> dict:
    """The document with every field checked, every list in order and every `says` line written. Raises Missing with
    the absent fields, or Refused with the one that is wrong. `strict`: a `says` line the file carries must be the one
    this module writes from the facts (False: lines are written, whatever the file said)."""
    if not isinstance(doc, dict):
        raise Refused("A terms 3 file is one JSON object.")
    if doc.get("standard") != STANDARD or doc.get("v") != V or type(doc.get("v")) is not int:
        raise Refused(f'A terms 3 file says "standard": "{STANDARD}" and "v": {V}. This one does not, so it is read as another format.')
    lacking = [f for f in NAMES if f not in doc]
    if lacking:
        raise Missing(lacking)
    extra = sorted(set(doc) - _TOP - _MORE)
    if extra:
        raise Refused(f"A terms 3 file has no field named {', '.join(extra)}.")
    name = doc.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise Refused("`name` is the template's name, or the repository as owner/name")
    out: dict = {"standard": STANDARD, "v": V, "name": name, "version": _int(doc.get("version"), 1, 10**6, "`version`")}
    if doc.get("built", True) is not True:
        if doc.get("built") is not False or doc.get("needs") != NOT_BUILT.split(": ")[1][6:]:
            raise Refused('A template that cannot be funded says "built": false and "needs": "a signing system of record".')
        out["built"], out["needs"] = False, doc["needs"]
    elif "needs" in doc:
        raise Refused("`needs` goes with `built: false`")
    for field in NAMES:
        facts = _READ[field](doc[field], doc)
        line = say(field, facts, "built" not in out)
        had = doc[field].get("says")
        if strict and had is not None and had != line:
            raise Refused(f"`{field}.says` does not say what the field holds. It must read: {line}")
        if strict and had is None:
            raise Missing([f"{field}.says"])
        out[field] = {**facts, "says": line}
    return out


def canonical(doc: dict) -> bytes:
    """The bytes that are hashed: sorted keys, `,` and `:` with no space, ASCII. Lists were put in order by `validate`."""
    return json.dumps(validate(doc), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(doc: dict) -> str:
    """The version of a terms 3 document: the sha256 of its canonical bytes, in hex."""
    return hashlib.sha256(canonical(doc)).hexdigest()


def dumps(doc: dict) -> str:
    """The file a buyer commits: the validated document, in the order of the ten questions."""
    got = validate(doc)
    return json.dumps({k: got[k] for k in ("standard", "v", "name", "version", *(k for k in ("built", "needs") if k in got), *NAMES)},
                      indent=2, ensure_ascii=True) + "\n"


def is_terms3(data) -> bool:
    return isinstance(data, dict) and (data.get("standard") == STANDARD or data.get("v") == V)


def built(doc: dict) -> bool:
    return doc.get("built", True) is True


def cite(doc: dict) -> str:
    """The sentence a contract carries."""
    got = validate(doc)
    return f"Acceptance is governed by {STANDARD}, {got['name']} version {got['version']}, sha256 {digest(got)}"


def questions(doc: dict) -> list[dict]:
    """The document as the ten questions it answers: [{"field", "question", "answer"}]."""
    got = validate(doc)
    return [{"field": f, "question": QUESTION[f], "answer": got[f]["says"]} for f in NAMES]


# ---- the order a document funds --------------------------------------------------------------------------------------

def order_terms(doc: dict) -> dict:
    """The terms an order is funded on (knos.terms, at most 600 bytes): the deciding checks, the paths, the protected
    paths, and `contract`, this document's sha256, so the order's own hash names this version and no other."""
    got = validate(doc)
    if not built(got):
        raise Refused(f"`{got['name']}` cannot fund an order: {NOT_BUILT}.")
    c, ch = got["checks"], got["changes"]
    try:
        return terms.parse(terms.canonical({"accept": c["accept"], "checks": [{"app": x["app"], "name": x["name"]} for x in c["deciding"]],
                                            "deny": sorted({*terms.DENY, *ch["protected"]}), "mode": c["mode"], "paths": ch["paths"],
                                            "reserve": 7, "v": 1, "contract": digest(got), **({"image": c["image"]} if "image" in c else {})}))
    except terms.Refused as why:
        raise Refused(f"These terms do not fit an order: {why}") from None


def options(doc: dict) -> dict:
    """What the document fixes of an order beside its terms: the options the funding token signs."""
    got = validate(doc)
    return {"units": units(got["price"]["amount"]), "days": got["deadline"]["days"], "holdback": got["window"]["holdback_percent"],
            "warranty": got["window"]["warranty_days"], "quorum": got["evaluators"]["quorum"],
            "arbiter": got["dispute"].get("arbiter", ""), "judges": [e["repository"] for e in got["evaluators"]["list"]]}


def comment(doc: dict) -> str:
    """The `/knos fund` comment that funds this document's order."""
    got, o = validate(doc), options(doc)
    names = ", ".join(c["name"] for c in got["checks"]["deciding"]) or "none"
    line = f"/knos fund {got['price']['amount'].removesuffix('.00')} checks: {names}"
    if got["changes"]["paths"]:
        line += " paths: " + ", ".join(got["changes"]["paths"])
    if o["holdback"]:
        line += f" holdback {o['holdback']} warranty {o['warranty']}"
    if o["quorum"] > 1:
        line += f" quorum {o['quorum']}"
    if o["arbiter"]:
        line += f" arbiter @{o['arbiter']}"
    return f"{line} days {o['days']}"


def check_order(doc: dict, *, units_: int, days: int, holdback: int = 0, warranty: int = 0, quorum: int = 1, order_terms_: dict | None = None,
                arbiter: str = "") -> list[str]:
    """What an order says that the document it cites does not, one plain sentence each; [] when the order is the
    document's. The caller refuses to fund on any sentence."""
    o, out = options(doc), []
    for what, have, want, unit in (("amount", units_, o["units"], "millionths"), ("deadline", days, o["days"], "days"),
                                   ("holdback", holdback or 0, o["holdback"], "percent"), ("warranty", warranty or 0, o["warranty"], "days"),
                                   ("quorum", quorum or 1, o["quorum"], "judges")):
        if have != want:
            out.append(f"The order's {what} is {have} {unit}; the terms say {want}.")
    if (arbiter or "").lstrip("@").lower() != o["arbiter"].lower():
        out.append(f"The order's arbiter is {arbiter or 'not named'}; the terms name {('@' + o['arbiter']) if o['arbiter'] else 'none'}.")
    if order_terms_ is not None and terms.canonical(order_terms_) != terms.canonical(order_terms(doc)):
        out.append("The order's checks, paths or contract hash are not the ones this version of the terms gives.")
    return out


def evaluator_allowed(doc: dict, issuer: str, repository: str, workflow: str, parties: tuple[str, ...] = ()) -> str | None:
    """The name of the evaluator a signed token is from, or None when the terms authorise nobody with that identity.
    `workflow`: the token's job_workflow_ref without its `@ref`. `parties`: the owners who may not be a `*` evaluator."""
    got, owner = validate(doc), repository.split("/")[0].lower()
    for e in got["evaluators"]["list"]:
        if e["issuer"] != issuer or e["workflow"] != workflow.split("@")[0]:
            continue
        if e["repository"].lower() == repository.lower() or (e["repository"] == ANYONE and owner not in {p.lower() for p in parties}):
            return e["name"]
    return None


def appeal_open(doc: dict, rejected_at: float, now: float) -> bool:
    """Whether an appeal of a rejection made at `rejected_at` is still inside the terms' window at `now`."""
    return now - rejected_at <= validate(doc)["dispute"]["within_days"] * 86400


# ---- two versions, compared ------------------------------------------------------------------------------------------

def _set(was: list, now: list, field: str, more: str, less: str, out: list) -> None:
    out += [(field, f"{more} `{g}`.") for g in now if g not in was]
    out += [(field, f"{less} `{g}`.") for g in was if g not in now]


def diff(a: dict, b: dict) -> list[tuple[str, str]]:
    """What changed from version `a` to version `b`: (field, one plain sentence) for each difference, in the order of
    the ten questions. Compared by meaning: the order of a list or of the keys changes nothing. [] when both are one
    version."""
    a, b = validate(a), validate(b)
    out: list[tuple[str, str]] = []
    if a["deliverable"] != b["deliverable"]:
        out.append(("deliverable", f"What counts as one deliverable changed: it was one {a['deliverable']['kind']} for each "
                                   f"{a['deliverable']['one_per']}; it is now one {b['deliverable']['kind']} for each {b['deliverable']['one_per']}."))
    src = lambda d: [f"{ISSUERS[s['issuer']]} / {s['workflow']}" for s in d["evidence"]["sources"]]  # noqa: E731
    _set(src(a), src(b), "evidence", "A new evidence source now counts:", "An evidence source no longer counts:", out)
    ca, cb = a["checks"], b["checks"]
    by = {"merge": "a maintainer's merge", "tests": "the acceptance suite passing"}
    if ca["mode"] != cb["mode"]:
        out.append(("checks", f"What decides changed: it was {by[ca['mode']]}; it is now {by[cb['mode']]}."))
    elif ca["accept"] != cb["accept"]:
        out.append(("checks", f"The acceptance suite changed (hash {ca['accept'][:12]} before, {cb['accept'][:12]} now). Work one accepts is not thereby accepted by the other."))
    was, now = [_check(c) for c in ca["deciding"]], [_check(c) for c in cb["deciding"]]
    out += [("checks", f"A check must now pass that did not have to: {n}.") for n in now if n not in was]
    out += [("checks", f"A check no longer has to pass: {n}.") for n in was if n not in now]
    if ca.get("image") != cb.get("image"):
        out.append(("checks", f"Where the suite runs changed: {ca.get('image') or 'no pinned image'} before, {cb.get('image') or 'no pinned image'} now."))
    if ca["authority"] != cb["authority"]:
        out.append(("checks", f"The authoritative copy of the checks moved: {ca['authority']} before, {cb['authority']} now."))
    wa, wb = a["window"], b["window"]
    if wa != wb:
        w = lambda x: f"{x['holdback_percent']}% held for {_days(x['warranty_days'])}" if x["warranty_days"] else "nothing held, no reopening"  # noqa: E731
        out.append(("window", f"The reopening window changed: {w(wa)} before; {w(wb)} now."))
    ha, hb = a["changes"], b["changes"]
    if bool(ha["paths"]) != bool(hb["paths"]):
        listed = _list(ha["paths"] or hb["paths"])
        out.append(("changes", f"Before, any file could change; now only files matching {listed}." if hb["paths"] else
                    f"Before, only files matching {listed} could change; now any file can."))
    else:
        _set(ha["paths"], hb["paths"], "changes", "The work may now also change files matching", "The work may no longer change files matching", out)
    _set(ha["protected"], hb["protected"], "changes", "A path is now protected:", "A path is no longer protected:", out)
    _set(ha["may_add"], hb["may_add"], "changes", "A contributor may now add, without asking, files matching",
         "A contributor may no longer add, without asking, files matching", out)
    da, db = a["dispute"], b["dispute"]
    if da["within_days"] != db["within_days"]:
        out.append(("dispute", f"The time to appeal changed: {_days(da['within_days'])} before, {_days(db['within_days'])} now."))
    if (da["evaluator"], da.get("arbiter", "")) != (db["evaluator"], db.get("arbiter", "")):
        who = lambda d: (f"the arbiter @{d['arbiter']}" if d.get("arbiter") else "an arbiter, none named") if d["evaluator"] == "arbiter" else f"the evaluator `{d['evaluator']}`"  # noqa: E731
        out.append(("dispute", f"Who hears an appeal changed: {who(da)} before, {who(db)} now."))
    ea, eb = a["evaluators"], b["evaluators"]
    ev = lambda d: [f"{e['name']} ({ISSUERS[e['issuer']]}, {e['workflow']}, {e['repository']})" for e in d["list"]]  # noqa: E731
    _set(ev(ea), ev(eb), "evaluators", "An evaluator may now judge:", "An evaluator may no longer judge:", out)
    if ea["quorum"] != eb["quorum"]:
        out.append(("evaluators", f"How many evaluators must agree changed: {ea['quorum']} before, {eb['quorum']} now."))
    if ea.get("related", []) != eb.get("related", []):
        out.append(("evaluators", f"The accounts declared to be one party changed: {ea.get('related') or 'none'} before, {eb.get('related') or 'none'} now."))
    if a["price"] != b["price"]:
        out.append(("price", f"The price changed: {a['price']['amount']} {a['price']['currency']} before, {b['price']['amount']} {b['price']['currency']} now."))
    if a["deadline"]["days"] != b["deadline"]["days"]:
        out.append(("deadline", f"The deadline changed: {_days(a['deadline']['days'])} from funding before, {_days(b['deadline']['days'])} now."))
    _set(a["policy"]["may_change"], b["policy"]["may_change"], "policy", "May now publish a new version:", "May no longer publish a new version:", out)
    return out


def diff_text(a: dict, b: dict, name_a: str = "the first", name_b: str = "the second") -> str:
    """What `knos terms diff` prints for two terms 3 files."""
    va, vb = digest(a), digest(b)
    if va == vb:
        return f"Nothing changed: both are version {va} of the terms.\n"
    lines = diff(a, b)
    body = "".join(f"  - [{f}] {x}\n" for f, x in lines) or "  - Only the name or the version number differ.\n"
    return (f"{STANDARD}, version {va[:12]} ({name_a}) to version {vb[:12]} ({name_b}):\n\n{body}"
            f"\n{len(lines)} difference{'' if len(lines) == 1 else 's'}. An order keeps the version it was funded on: its hash is in the "
            "order's terms. The later version applies only to orders funded on it.\n")


# ---- templates: the common jobs, each with safe defaults -------------------------------------------------------------

WORKFLOWS = "/".join(("drexthealpha", "knos-workflows", ".github", "workflows", ""))     # (joined here: tests/test_workflows2.py lets no file of the package, compiled or not, spell the published path whole)
PROVE, ATTEST = WORKFLOWS + "prove.yml", WORKFLOWS + "attest.yml"
SAMPLE_REPO = "acme/widgets"
ACTIONS = 15368                 # the GitHub App id of GitHub Actions
DATASET_ACCEPT = "8445799b6b70bde0dcf4a73465d9a34b0e180a9c88daa305acf4926c5d62acc5"     # examples/outcomes/data-labelling's suite


def _own(repo: str) -> dict:
    return {"name": "own", "issuer": GITHUB, "repository": repo, "workflow": PROVE, "owner": repo.split("/")[0]}


NEUTRAL = {"name": "neutral", "issuer": GITHUB, "repository": ANYONE, "workflow": ATTEST, "owner": ANYONE}


def base(repo: str = SAMPLE_REPO, name: str = "bug-fix") -> dict:
    """The safe defaults every template starts from, for `repo`: paid on a merge after named checks, nothing held, the
    order's own repository judges, an appeal goes to an arbiter (none named), 14 days, and only the owner changes it."""
    return {
        "standard": STANDARD, "v": V, "name": name, "version": 1,
        "deliverable": {"kind": "pull-request", "one_per": "issue"},
        "evidence": {"sources": [{"issuer": GITHUB, "workflow": PROVE}, {"issuer": GITHUB, "workflow": ATTEST}]},
        "checks": {"mode": "merge", "deciding": [{"name": "lint", "app": ACTIONS}, {"name": "unit", "app": ACTIONS}], "accept": "",
                   "authority": f"the workflow files of {repo} at the commit the order was funded on"},
        "window": {"warranty_days": 0, "holdback_percent": 0},
        "changes": {"paths": ["src/**", "tests/**"], "protected": list(terms.DENY), "may_add": []},
        "dispute": {"who": "supplier", "evaluator": "arbiter", "within_days": 7, "money": "order", "no_answer": "refund-at-deadline"},
        "evaluators": {"quorum": 1, "list": [_own(repo)]},
        "price": {"amount": "50.00", "currency": MONEY},
        "deadline": {"days": 14, "late": "refused"},
        "policy": {"may_change": ["@" + repo.split("/")[0]], "how": "new-version"},
    }


def _made(name: str, **fields) -> dict:
    doc = base(name=name)
    for key, value in fields.items():
        doc[key] = {**doc[key], **value} if isinstance(doc.get(key), dict) else value
    return validate(doc, strict=False)


TEMPLATES = {
    # a bug fix: two checks, only src/ and tests/, paid on the merge
    "bug-fix": lambda: _made("bug-fix"),
    # a migration: touches anything, so a fifth waits 30 days and comes back on a revert
    "migration": lambda: _made("migration", checks={"deciding": [{"name": "unit", "app": ACTIONS}]}, changes={"paths": []},
                               window={"warranty_days": 30, "holdback_percent": 20}, price={"amount": "100.00"}, deadline={"days": 30}),
    # a dataset batch: scored by a suite on items never shown, appealed to a neutral run of the same suite
    "dataset-batch": lambda: _made("dataset-batch", deliverable={"kind": "batch", "one_per": "batch number"},
                                   checks={"mode": "tests", "deciding": [], "accept": DATASET_ACCEPT,
                                           "authority": f".knos/acceptance/ of {SAMPLE_REPO} at the commit the order was funded on; its hash is in these terms"},
                                   changes={"paths": ["batches/**"]}, dispute={"evaluator": "neutral"},
                                   evaluators={"list": [_own(SAMPLE_REPO), NEUTRAL]}, price={"amount": "40.00"}),
    # a support resolution: no third party signs that a ticket was resolved, so this cannot fund anything
    "support-resolution": lambda: _made("support-resolution", built=False, needs="a signing system of record",
                                        deliverable={"kind": "resolution", "one_per": "ticket"}, evidence={"sources": []},
                                        checks={"deciding": [], "authority": "none yet: the help desk's own record, which the seller keeps"},
                                        changes={"paths": [], "protected": []}, evaluators={"list": []},
                                        window={"warranty_days": 0, "holdback_percent": 0}, price={"amount": "1.00"}),
}


def template(name: str) -> dict:
    if name not in TEMPLATES:
        raise KeyError(f"there is no terms 3 template named {name}: the templates are {', '.join(TEMPLATES)}")
    return TEMPLATES[name]()
