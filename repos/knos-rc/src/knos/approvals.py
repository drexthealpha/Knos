"""Who may approve what, and whether they did: an approval policy, approvals as events, and the chain a request needs.

    knos approve record --repo acme/widgets --comment 2291 --offer .knos/procurement/offers/bug-fix-octocat.yaml
    knos approve check  --approver mei-acme --requester ravi-acme --amount 1200 [--on 2026-10-06] [--as finance]
    knos approve status --offer .knos/procurement/offers/bug-fix-octocat.yaml

The policy is one file in the buyer's repository, `.knos/procurement/policy.yaml` (docs/reference/CONTROLS.md has the schema):
four roles (requester, approver, finance, auditor), the forge accounts that hold each and between which dates, and
thresholds that say how many approvers an amount needs and from where finance signs too.

An approval is a person's assent, and it is taken the way a funding is: a comment by the named account on the forge,

    /knos approve offer:bug-fix-octocat            (or: /knos approve offer:bug-fix-octocat as finance)

which `knos approve record` reads back through the forge's API. Who wrote it and when are the forge's answer, never
the caller's word. The event it appends to `.knos/procurement/approvals.jsonl` carries the comment's address and the
sha256 of its text, so anyone can read the same comment again. That is all the signature there is: Knos adds no key
of its own, and whoever controls the forge account controls the approval.

Authority is code, judged for the day the comment was written (`check`): the account must hold the role on that day,
may not approve its own request above the policy's `self_approval_limit`, and may not pass its own `limit`. A refusal
is one plain sentence. `chain` re-judges every event of a request against the policy, so a log somebody edited by
hand gains nothing: an approval without authority is not counted, and the answer says why.

The policy judged is the file as given. To judge an old approval by the policy of its day, give that day's file:
`git show <commit>:.knos/procurement/policy.yaml`. The event records the sha256 of the policy it was judged by.

web/procure.js is the same code for the console; tests/data/procure_cases.json holds both to one answer.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import controls
from .controls import _LOGIN, _head, _is, day_of, money, units_of

ROLES = ("requester", "approver", "finance", "auditor")
SIGNING = ("approver", "finance")           # the roles whose assent a threshold counts
POLICY_FIELDS = ("version", "kind", "currency", "self_approval_limit", "roles", "thresholds")
HOLDER_FIELDS = ("account", "from", "until", "limit")
TIER_FIELDS = ("up_to", "approvers", "finance")
LOG = "approvals.jsonl"
TYPE, VERSION = "knos.approval", 1
_SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:./#-]{0,119}")
_COMMENT = re.compile(r"^/knos approve +(\S+)(?: +as +(approver|finance))? *$", re.M)


def _same(a, b) -> bool:
    return str(a).lower() == str(b).lower()


def holders(policy: dict, role: str) -> list[dict]:
    return [h for h in (policy.get("roles") or {}).get(role) or [] if isinstance(h, dict)]


def policy_problems(doc) -> list[str]:
    """What is wrong with an approval policy, in sentences ([]: nothing)."""
    out = _head(doc, "approval-policy", "an approval policy", POLICY_FIELDS)
    if not isinstance(doc, dict):
        return out
    if units_of(doc.get("self_approval_limit", 0)) is None:
        out.append("`self_approval_limit` is an amount; 0 means nobody approves their own request.")
    roles = doc.get("roles")
    if not isinstance(roles, dict) or not roles:
        return out + ["`roles` names who holds each role: requester, approver, finance, auditor."]
    for role, rows in roles.items():
        if role not in ROLES:
            out.append(f"`{role}` is not a role: the roles are requester, approver, finance and auditor.")
            continue
        if not isinstance(rows, list) or not all(isinstance(h, dict) for h in rows):
            out.append(f"Role `{role}` is a list of holders, each with an `account`.")
            continue
        for n, h in enumerate(rows, 1):
            me = f"Role `{role}`, @{h['account']}" if _is(_LOGIN, h.get("account")) else f"Role `{role}`, holder {n}"
            out += [f"{me}: `{k}` is not a field of a holder." for k in h if k not in HOLDER_FIELDS]
            if not _is(_LOGIN, h.get("account")):
                out.append(f"{me}: `account` is a forge account, like octocat.")
            days = {k: day_of(h[k]) for k in ("from", "until") if k in h}
            out += [f"{me}: `{k}` is a date like 2026-10-01." for k, d in days.items() if d is None]
            if None not in days.values() and len(days) == 2 and days["from"] > days["until"]:      # type: ignore[operator]
                out.append(f"{me}: `from` is after `until`.")
            if "limit" in h and (role not in SIGNING or not units_of(h["limit"])):
                out.append(f"{me}: `limit` is an amount above zero, for an approver or finance only.")
    tiers = doc.get("thresholds")
    if not isinstance(tiers, list) or not tiers or not all(isinstance(t, dict) for t in tiers):
        return out + ["`thresholds` lists at least one step, each with `approvers` and, but for the last, `up_to`."]
    last = 0
    for n, t in enumerate(tiers, 1):
        out += [f"Threshold {n}: `{k}` is not a field of a threshold." for k in t if k not in TIER_FIELDS]
        top = units_of(t.get("up_to")) if "up_to" in t else None
        if n < len(tiers) and (not top or top <= last):
            out.append(f"Threshold {n}: `up_to` is an amount above the step before it.")
        if n == len(tiers) and "up_to" in t:
            out.append("The last threshold has no `up_to`: it covers every amount above.")
        last = top or last
        for role, least in (("approvers", 1), ("finance", 0)):
            need = t.get(role, 0)
            if isinstance(need, bool) or not isinstance(need, int) or not least <= need <= 5:
                out.append(f"Threshold {n}: `{role}` is a whole number from {least} to 5.")
            elif need > len({str(h.get("account")).lower() for h in holders(doc, "approver" if role == "approvers" else role)}):
                out.append(f"Threshold {n} asks for {need} of `{role}`, and the policy names fewer.")
    return out


def tier_of(policy: dict, amount: int) -> dict:
    """What a sound policy asks for `amount` (millionths): {approver, finance, up_to} (up_to None: the last step)."""
    for t in policy["thresholds"]:
        top = units_of(t["up_to"]) if "up_to" in t else None
        if top is None or amount <= top:
            return {"approver": int(t.get("approvers", 0)), "finance": int(t.get("finance", 0)), "up_to": top}
    return {"approver": 0, "finance": 0, "up_to": None}      # not reached: a sound policy's last step has no up_to


def _term(h: dict) -> str:
    return f"from {h['from']} to {h['until']}" if "from" in h and "until" in h else f"from {h['from']}" if "from" in h else f"until {h['until']}" if "until" in h else "with no end date"


def authority_words(role: str, h: dict) -> str:
    """A holder's authority in a few words: "approver from 2026-01-01 to 2026-12-31, up to 25,000.00"."""
    return f"{role} {_term(h)}" + (f", up to {money(units_of(h['limit']) or 0)}" if "limit" in h else "")


def held_on(policy: dict, account: str, role: str, on: str) -> tuple[dict | None, str]:
    """(the holder's entry in force on the day `on`, "") or (None, why not: one sentence)."""
    mine, day = [h for h in holders(policy, role) if _same(h.get("account"), account)], day_of(on) or 0
    if not mine:
        return None, f"Refused: @{account} does not hold the {role} role in this policy."
    for h in mine:
        if (day_of(h.get("from")) or -10 ** 9) <= day <= (day_of(h.get("until")) or 10 ** 9):
            return h, ""
    ended = [h for h in mine if "until" in h and (day_of(h["until"]) or 0) < day]
    if ended:
        return None, f"Refused: @{account}'s {role} role ended {max(h['until'] for h in ended)}, before this approval of {on}."
    return None, f"Refused: @{account}'s {role} role starts {min(h['from'] for h in mine)}, after this approval of {on}."


def check(policy: dict, *, approver: str, requester: str, amount: int, on: str, role: str = "approver") -> dict:
    """Did `approver` have the authority to approve `amount` (millionths) of `requester`'s request on the day `on`,
    in `role` (approver or finance)? {ok, role, authority, sentence}: `authority` is the entry's own words, and a
    refusal's sentence says which rule refused."""
    def no(sentence: str) -> dict:
        return {"ok": False, "role": role, "authority": "", "sentence": sentence}
    if role not in SIGNING:
        return no(f"Refused: the {role} role approves nothing; an approver or finance does.")
    h, why = held_on(policy, approver, role, on)
    if h is None:
        return no(why)
    own = units_of(policy.get("self_approval_limit", 0)) or 0
    if _same(approver, requester) and amount > own:
        return no(f"Refused: @{approver} asked for this, and nobody approves their own request" + (f" above {money(own)}." if own else "."))
    if "limit" in h and amount > (units_of(h["limit"]) or 0):
        return no(f"Refused: {money(amount)} is over @{approver}'s own limit of {money(units_of(h['limit']) or 0)}.")
    words = authority_words(role, h)
    return {"ok": True, "role": role, "authority": words, "sentence": f"Fine: @{approver} is {words}."}


def chain(policy: dict, *, subject: str, requester: str, amount: int, events: list[dict], on: str) -> dict:
    """Where one request stands: {subject, amount, need, counted, refused, waiting, met, sentence}. `events`: the
    approvals log; those of another subject are skipped, each of this one is judged again for its own day (`check`),
    an account counts once, and in one role only. `waiting` names, per role still short, who could sign on the day
    `on`. `need` is the policy's threshold for the amount."""
    tier = tier_of(policy, amount)
    counted: list[dict] = []
    refused: list[dict] = []
    got = {"approver": 0, "finance": 0}
    if held_on(policy, requester, "requester", on)[0] is None:
        refused.append({"approver": requester, "role": "requester", "sentence": f"Refused: @{requester} does not hold the requester role on {on}."})
    for e in events:
        if e.get("subject") != subject:
            continue
        who, role, at = str(e.get("approver", "")), str(e.get("role", "approver")), str(e.get("at", ""))[:10]
        said = check(policy, approver=who, requester=requester, amount=amount, on=at, role=role)
        if said["ok"] and any(_same(c["approver"], who) for c in counted):
            said = {**said, "ok": False, "sentence": f"Refused: @{who} already approved this, and one person counts once."}
        if said["ok"] and units_of(e.get("amount", "")) not in (None, amount):
            said = {**said, "ok": False, "sentence": f"Refused: @{who} approved {money(units_of(e['amount']) or 0)}, and the request is now {money(amount)}."}
        if said["ok"]:
            counted.append({"approver": who, "role": role, "at": str(e.get("at", "")), "authority": said["authority"], "source": (e.get("source") or {}).get("url", "")})
            got[role] += 1
        else:
            refused.append({"approver": who, "role": role, "sentence": said["sentence"]})
    waiting = []
    for role in SIGNING:
        short = tier[role] - got[role]
        if short > 0:
            who_can = sorted({str(h["account"]) for h in holders(policy, role)
                              if not any(_same(c["approver"], h["account"]) for c in counted)
                              and check(policy, approver=str(h["account"]), requester=requester, amount=amount, on=on, role=role)["ok"]}, key=str.lower)
            waiting.append({"role": role, "count": short, "who": who_can})
    met = not waiting and not any(r["role"] == "requester" for r in refused)
    names = {"approver": lambda n: f"{n} approver{'s' if n != 1 else ''}", "finance": lambda n: "finance"}
    need = " and ".join(names[r](tier[r]) for r in SIGNING if tier[r])
    if met:
        sentence = f"Approved: {need} signed, as {money(amount)} needs."
    elif not waiting:
        sentence = refused[0]["sentence"]
    else:
        sentence = "Waits for " + " and ".join(names[w["role"]](w["count"]) for w in waiting) + f": {money(amount)} needs {need}."
    return {"subject": subject, "amount": amount, "need": {r: tier[r] for r in SIGNING}, "counted": counted, "refused": refused, "waiting": waiting,
            "met": met, "sentence": sentence}


# ---- the event, and the comment it is taken from ------------------------------------------------------------------------
def sha256_hex(text: str | bytes) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode("utf-8")).hexdigest()


def read_comment(body: str) -> tuple[str, str | None] | None:
    """(subject, role asked for or None) of the first `/knos approve ...` line of a comment, or None when it has none."""
    m = _COMMENT.search(str(body).replace("\r\n", "\n"))
    return (m.group(1), m.group(2)) if m and _SUBJECT.fullmatch(m.group(1)) else None


def comment_line(subject: str, role: str = "approver") -> str:
    """The line an approver posts on the forge."""
    return f"/knos approve {subject}" + (" as finance" if role == "finance" else "")


def event(*, subject: str, amount: int, requester: str, approver: str, approver_id: int, role: str, at: str, authority: str, source: dict, policy_sha256: str) -> dict:
    """One approval as the log holds it. `id` is the sha256 of who approved what where: the same comment gives the same id."""
    ident = "apr_" + sha256_hex("\x00".join(["knos.approval.v1", subject, approver.lower(), role, str(source.get("url", ""))]))[:24]
    return {"type": TYPE, "version": VERSION, "id": ident, "subject": subject, "amount": controls.commands.amount(amount), "requested_by": requester,
            "approver": approver, "approver_id": approver_id, "role": role, "at": at, "authority": authority, "source": source, "policy_sha256": policy_sha256}


def from_comment(policy: dict, comment: dict, *, subject: str, requester: str, amount: int, policy_text: str = "") -> tuple[dict | None, str]:
    """(the event, its authority sentence) for a comment as the forge's API returns it, or (None, why it is refused).
    The account and the time are the forge's: `user.login`, `user.id`, `created_at`."""
    asked = read_comment(comment.get("body") or "")
    if asked is None:
        return None, "Refused: that comment has no `/knos approve` line."
    if asked[0] != subject:
        return None, f"Refused: that comment approves `{asked[0]}`, not `{subject}`."
    user, at = comment.get("user") or {}, str(comment.get("created_at") or "")
    who = str(user.get("login") or "")
    if not who or day_of(at[:10]) is None:
        return None, "Refused: the forge did not say who wrote that comment, or when."
    if comment.get("created_at") != comment.get("updated_at", comment.get("created_at")):
        return None, "Refused: that comment was edited after it was written. Ask for a new one."
    role = asked[1] or ("finance" if held_on(policy, who, "approver", at[:10])[0] is None and held_on(policy, who, "finance", at[:10])[0] is not None else "approver")
    said = check(policy, approver=who, requester=requester, amount=amount, on=at[:10], role=role)
    if not said["ok"]:
        return None, said["sentence"]
    source = {"kind": "forge comment", "forge": "github", "url": str(comment.get("html_url") or ""), "comment_id": int(comment.get("id") or 0),
              "body_sha256": sha256_hex(str(comment.get("body") or ""))}
    return event(subject=subject, amount=amount, requester=requester, approver=who, approver_id=int(user.get("id") or 0), role=role, at=at,
                 authority=said["authority"], source=source, policy_sha256=sha256_hex(policy_text) if policy_text else ""), said["sentence"]


def read_log(text: str) -> list[dict]:
    """The events of an approvals log: one JSON object a line; a line that is not one is skipped."""
    out = []
    for line in str(text).splitlines():
        try:
            e = json.loads(line) if line.strip() else None
        except ValueError:
            e = None
        if isinstance(e, dict) and e.get("type") == TYPE:
            out.append(e)
    return out


def verified(e: dict, comment: dict) -> bool:
    """Whether an event of the log is the comment the forge has: the same account, time and text, never edited."""
    return (read_comment(comment.get("body") or "") is not None and _same((comment.get("user") or {}).get("login", ""), e.get("approver"))
            and comment.get("created_at") == e.get("at") == comment.get("updated_at", comment.get("created_at"))
            and sha256_hex(str(comment.get("body") or "")) == (e.get("source") or {}).get("body_sha256"))


def gate(files: dict[str, str], *, vendor: str, rate: int, budget: int, on: str, fetch=None) -> tuple[bool, str]:
    """Whether a `/knos offer @vendor rate R budget B` comment may fund on the day `on`, by the buyer's own procurement
    files: (ok, one sentence). `files`: {path: text} of everything under .knos/procurement/ on the default branch.
    `fetch(comment id) -> the forge's comment`, when given, is asked for every approval, and one the forge does not
    confirm is not counted. A repository with no approval policy is held to nothing more: (True, "")."""
    root, c = controls.PROCUREMENT, controls
    if f"{root}/policy.yaml" not in files:
        return True, ""

    def sound(path: str, problems) -> dict:
        try:
            doc = c.read_yaml(files.get(path, ""))
        except c.Unread as why:
            raise ValueError(f"Refused: {path}: {why}") from None
        bad = problems(doc)
        if bad:
            raise ValueError(f"Refused: {path} is not a valid policy. {bad[0]}")
        return doc
    try:
        policy = sound(f"{root}/policy.yaml", policy_problems)
        for path in sorted(files):
            if not path.startswith(f"{root}/{c.FILES['standing-offer']}/"):
                continue
            offer = sound(path, c.offer_problems)
            if offer["suppliers"] == "anyone" or not any(_same(s, vendor) for s in offer["suppliers"]) or units_of(offer["cap"]) != budget:
                continue
            card = sound(f"{root}/{c.FILES['rate-card']}/{offer['rate_card']}.yaml", lambda d: c.card_problems(d, c.published_terms()))
            row = c.outcome_of(card, offer["outcome"])
            if c.offer_problems(offer, card) or row is None or units_of(row["price"]) != rate or not (day_of(offer["starts"]) or 0) <= (day_of(on) or 0) <= (day_of(offer["ends"]) or 0):
                continue
            envelope = sound(f"{root}/{c.FILES['budget-envelope']}/{offer['envelope']}.yaml", c.envelope_problems)
            events = [e for e in read_log(files.get(f"{root}/{LOG}", "")) if fetch is None or verified(e, fetch(int((e.get("source") or {}).get("comment_id") or 0)) or {})]
            got = chain(policy, subject=f"offer:{offer['name']}", requester=str(offer["requested_by"]), amount=c.commitment(offer)["value"], events=events, on=on)
            if not got["met"]:
                return False, f"Refused: offer `{offer['name']}` is not approved. {got['sentence']}"
            return True, f"Offer `{offer['name']}`, envelope `{envelope['name']}`. {got['sentence']}"
    except ValueError as why:
        return False, str(why)
    return False, f"Refused: no standing offer under {root}/offers/ names @{vendor} at this rate and cap today."


def gate_order(files: dict[str, str], *, subject: str, requester: str, amount: int, on: str, fetch=None) -> tuple[bool, str]:
    """Whether a funding that is no standing offer (`/knos fund`, `/knos tip`, a private order) may go on, by the same
    files: (ok, one sentence). `subject` is what the approvers sign, `issue:<number>` or `tip:<number>`; `requester`
    the account whose comment asks for the money; `amount` what the order holds, in millionths. The requester must
    hold the requester role, and the approvals log must hold what the policy's threshold asks for this amount, each
    approval judged again and, with `fetch`, confirmed by the forge. No approval policy: (True, ""). What it does not
    ask: a rate card or an envelope, which a plain order names none of (knos.enforce says so cell by cell)."""
    root = controls.PROCUREMENT
    if f"{root}/policy.yaml" not in files:
        return True, ""
    try:
        policy = controls.read_yaml(files[f"{root}/policy.yaml"])
    except controls.Unread as why:
        return False, f"Refused: {root}/policy.yaml: {why}"
    bad = policy_problems(policy)
    if bad:
        return False, f"Refused: {root}/policy.yaml is not sound. {bad[0]}"
    if held_on(policy, requester, "requester", on)[0] is None:
        return False, f"Refused: @{requester} does not hold the requester role on {on}, and `{root}/policy.yaml` says who may ask for money."
    events = [e for e in read_log(files.get(f"{root}/{LOG}", "")) if fetch is None or verified(e, fetch(int((e.get("source") or {}).get("comment_id") or 0)) or {})]
    got = chain(policy, subject=subject, requester=requester, amount=amount, events=events, on=on)
    if not got["met"]:
        return False, f"Refused: `{subject}` is not approved. {got['sentence']}"
    return True, got["sentence"]


def sample_events() -> list[dict]:
    """The approvals of controls.sample()'s one open offer so far: one approver has signed, a second is awaited."""
    src = {"kind": "forge comment", "forge": "github", "url": f"https://github.com/{controls.SAMPLE_REPOSITORY}/issues/12#issuecomment-2291", "comment_id": 2291,
           "body_sha256": sha256_hex(comment_line("offer:bug-fix-octocat"))}
    return [event(subject="offer:bug-fix-octocat", amount=1_200_000_000, requester="ravi-acme", approver="mei-acme", approver_id=7001, role="approver",
                  at="2026-10-02T09:14:00Z", authority="approver from 2026-01-01 to 2026-12-31, up to 25,000.00", source=src, policy_sha256="")]


def sample_deliverable() -> dict:
    """One accepted deliverable of the sample offer, as the invoice approver's screen takes it (web/console.js sevenOf)."""
    from . import ids
    return {"id": ids.deliverable(controls.published_terms()["bugfix"], f"{controls.SAMPLE_REPOSITORY}#31"), "offer": "bug-fix-octocat", "outcome": "bug-fix", "supplier": "octocat",
            "artifact": "pull request #31", "requirements": [{"name": "unit", "passed": True}, {"name": "lint", "passed": True}, {"name": "only src/ and tests/ changed", "passed": True}],
            "verdict": "accepted", "evaluations": 2, "invoice_lines": 1, "amount": "50", "paid": "50", "held": "0", "credited": "0", "owed": "0", "disputed": False,
            "evidence": "audit/drexthealpha.json"}


# ---- the commands -------------------------------------------------------------------------------------------------------
def _load(path: Path, problems, what: str, stop) -> tuple[dict, str]:
    try:
        text = path.read_text(encoding="utf-8")
        doc = controls.read_yaml(text)
    except OSError:
        raise stop(f"There is no {what} at {path}.") from None
    except controls.Unread as why:
        raise stop(f"{path}: {why}") from None
    bad = problems(doc)
    if bad:
        raise stop(f"{path} is not a sound {what}:", "\n".join(f"  {b}" for b in bad))
    return doc, text


def request_of(offer_file: Path, stop) -> tuple[str, str, int, Path]:
    """(subject, requester, amount, the procurement directory) of an offer file: what an approval of it is about."""
    root = offer_file.resolve().parent.parent
    offer, _ = _load(offer_file, controls.offer_problems, "standing offer", stop)
    return f"offer:{offer['name']}", str(offer["requested_by"]), controls.commitment(offer)["value"], root


def register(app, help_lines: list | None = None) -> None:
    """`knos approve record | check | status`, on the main app. `help_lines`: cli._HELP, which gets the group's line."""
    import time

    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    approve_app = typer.Typer(add_completion=False, no_args_is_help=True,
                              help="Approvals under a policy: record one from a forge comment, check an approver's authority, see what a request waits for.")
    app.add_typer(approve_app, name="approve")
    if help_lines is not None:
        help_lines.append(("approve", "For money", "Approvals under a policy file: record one from a comment, check authority, see what waits for whom."))
    policy_opt = typer.Option(None, "--policy", help="the policy file (default: policy.yaml beside the offer, or .knos/procurement/policy.yaml)")
    offer_opt = typer.Option(None, "--offer", help="a standing offer's file: the request is the offer, its requester and what it commits")
    subject_opt = typer.Option(None, "--subject", help="without --offer: what is approved, like offer:bug-fix-octocat or a deliverable's id")
    requester_opt = typer.Option(None, "--requester", help="without --offer: the forge account that asked")
    amount_opt = typer.Option(None, "--amount", help="without --offer: the amount, like 1200 or 12.5")
    log_opt = typer.Option(None, "--log", help=f"the approvals log (default: {LOG} beside the policy)")

    def request(cli, offer, subject, requester, amount, policy) -> tuple[str, str, int, dict, str, Path]:
        if offer is not None:
            subject, requester, units, root = request_of(offer, cli.Stop)
        elif subject and requester and amount:
            units, root = cli._units(amount, 6), Path(controls.PROCUREMENT)
        else:
            raise cli.Stop("Say what is approved: --offer FILE, or --subject, --requester and --amount together.")
        where = policy or root / "policy.yaml"
        doc, text = _load(where, policy_problems, "approval policy", cli.Stop)
        return subject, requester, units, doc, text, where

    today = lambda: time.strftime("%Y-%m-%d", time.gmtime())  # noqa: E731

    @approve_app.command("check")
    def check_(approver: str = typer.Option(..., "--approver", help="the forge account that would approve"),
               role: str = typer.Option("approver", "--as", help="approver or finance"),
               on: str = typer.Option(None, "--on", help="the day judged, like 2026-10-06 (default: today, UTC)"),
               offer: Path = offer_opt, subject: str = subject_opt, requester: str = requester_opt, amount: str = amount_opt, policy: Path = policy_opt) -> None:
        """Would this account's approval count on that day? Nothing is recorded. Refused in one sentence when the account does not hold the role, the role has ended or not begun, the request is its own, or the amount is over its limit. Exit status 1 when refused."""
        from . import cli
        _subject, who, units, doc, _text, _where = request(cli, offer, subject or "-", requester, amount, policy)
        if on is not None and day_of(on) is None:
            raise cli.Stop("--on is a date like 2026-10-06.")
        said = check(doc, approver=approver, requester=who, amount=units, on=on or today(), role=role)
        cli.out.print(said["sentence"], markup=False)
        if not said["ok"]:
            raise typer.Exit(1)

    @approve_app.command("record")
    def record_(repo: str = typer.Option(..., "--repo", help="the repository the comment is in: owner/name"),
                comment: int = typer.Option(..., "--comment", help="the comment's number: the digits after issuecomment- in its link"),
                offer: Path = offer_opt, subject: str = subject_opt, requester: str = requester_opt, amount: str = amount_opt, policy: Path = policy_opt,
                log: Path = log_opt, dry_run: bool = typer.Option(False, "--dry-run", help="judge and print the event; write nothing")) -> None:
        """Record one approval: read the comment from the forge, take its author and time from the forge's answer, judge the author's authority for that day, and append the event to the approvals log. A refusal writes nothing and says why. Commit the log with the offer."""
        from . import cli
        what, who, units, doc, text, where = request(cli, offer, subject, requester, amount, policy)
        got = cli._github(f"repos/{repo}/issues/comments/{comment}")
        made, said = from_comment(doc, got, subject=what, requester=who, amount=units, policy_text=text)
        if made is None:
            raise cli.Stop(said, "Nothing was recorded.")
        file = log or where.parent / LOG
        before = read_log(file.read_text(encoding="utf-8")) if file.is_file() else []
        known = any(e.get("id") == made["id"] for e in before)
        cli.out.print(said, markup=False)
        if known:
            cli.out.print(f"Already recorded in {file}: nothing was written.", markup=False)
        elif dry_run:
            typer.echo(json.dumps(made, sort_keys=True))
        else:
            file.parent.mkdir(parents=True, exist_ok=True)
            with file.open("a", encoding="utf-8", newline="") as f:
                f.write(json.dumps(made, sort_keys=True) + "\n")
            cli.out.print(f"Recorded in {file} as {made['id']}. Commit that file.", markup=False)
        events = before if known else [*before, made]
        cli.out.print(chain(doc, subject=what, requester=who, amount=units, events=events, on=today())["sentence"], markup=False)

    @approve_app.command("status")
    def status_(offer: Path = offer_opt, subject: str = subject_opt, requester: str = requester_opt, amount: str = amount_opt, policy: Path = policy_opt,
                log: Path = log_opt, on: str = typer.Option(None, "--on", help="the day judged for who may still sign (default: today, UTC)"),
                as_json: bool = typer.Option(False, "--json", help="print the answer as JSON")) -> None:
        """What a request waits for, and for whom: the threshold its amount falls under, every approval counted with the authority it was given under, every one refused with the reason, and who may still sign. Exit status 1 until it is approved."""
        from . import cli
        what, who, units, doc, _text, where = request(cli, offer, subject, requester, amount, policy)
        file = log or where.parent / LOG
        got = chain(doc, subject=what, requester=who, amount=units, events=read_log(file.read_text(encoding="utf-8")) if file.is_file() else [], on=on or today())
        if as_json:
            typer.echo(json.dumps(got, sort_keys=True))
        else:
            cli.out.print(f"{what}, {money(units)} test USDC, asked for by @{who}", markup=False)
            cli.out.print(got["sentence"], markup=False)
            for c in got["counted"]:
                cli.out.print(f"  counted: @{c['approver']} on {c['at']}, {c['authority']}", markup=False)
            for r in got["refused"]:
                cli.out.print(f"  not counted: {r['sentence']}", markup=False)
            for w in got["waiting"]:
                cli.out.print(f"  waits for {w['count']} of {w['role']}: " + (", ".join("@" + a for a in w["who"]) or "nobody in the policy can sign this"), markup=False)
        if not got["met"]:
            raise typer.Exit(1)
