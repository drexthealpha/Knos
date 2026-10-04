"""Who is paid, where, and who holds an issue: decided by what GitHub authenticates (who opened the pull request, who
assigned whom, who wrote which comment, who can write to the repository), never by what a description says."""

from __future__ import annotations

import time

from _hub import BOT, Hub, comment, user
from knos import who

MONA, EVE, ALICE = user("mona", 4242), user("eve", 666), user("alice", 11)
HUBOT, TRIAGE = user("hubot", 1), user("tri", 2)                     # hubot can write; tri can only triage
DEVIN = user("devin-ai-integration[bot]", 158243242, "Bot")
ADDRESS, OTHER = "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo", "AT1aKj1DpgaWerxmS4YjDkNpWPNUtCCKVDvxLhFxg5Jc"
TERMS = {"accept": "", "checks": [], "deny": [".github/**", ".knos/**"], "mode": "merge", "paths": [], "reserve": 7, "v": 1}
T0 = 1_790_000_000.0                                                  # "now" for these tests
DAY = 86_400


def stamp(at: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))


def permission(login: str) -> str:
    return {"hubot": "admin", "writer": "write", "keeper": "maintain", "tri": "read"}.get(login, "none")


def pull(author=MONA, body="Fixes #7", assignees=(), merged_at=None) -> dict:
    return {"number": 12, "body": body, "user": author, "assignees": list(assignees), "head": {"sha": "a" * 40}, "merged_at": merged_at}


def issue(*assignees) -> dict:
    return {"number": 7, "assignees": list(assignees), "user": HUBOT}


def assigned(whom: dict, by: dict, at: float, kind: str = "assigned") -> dict:
    """An issue event as GET /repos/{repo}/issues/{n}/events gives it: `actor` is the assignee there."""
    return {"event": kind, "actor": whom, "assignee": whom, "assigner": by, "created_at": stamp(at)}


def paid(*args, **kw) -> dict:
    kw.setdefault("permission", permission)
    kw.setdefault("terms", TERMS)
    kw.setdefault("now", T0)
    return who.payee(*args, **kw)


# ---- a person's pull request -----------------------------------------------------------------------------------------

def test_a_persons_pull_request_pays_that_person_whatever_it_says():
    assert who.payee(pull()) == {"id": 4242, "login": "mona", "why": "the pull request's author"}
    redirect = pull(body="Fixes #7\n\nKnos-Pay-To: @eve\nRequested by: @eve", assignees=[EVE])
    comments = [comment(1, EVE, "/knos mine"), comment(2, HUBOT, "/knos pay @eve")]
    assert paid(redirect, issue(), [], comments, [], head_message="Co-authored-by: e <666+eve@users.noreply.github.com>") == \
        {"id": 4242, "login": "mona", "why": "the pull request's author"}                 # no hint either: nothing to hint at
    assert who.payee({"user": {"login": "mona", "id": 4242}})["id"] == 4242                # GitHub's event always says the type
    ghost = who.payee({"user": {"login": "ghost", "type": "User"}})
    assert ghost["id"] is None and ghost["kind"] == "payee" and "did not say who opened" in ghost["why"]
    assert who.payee({})["id"] is None


# ---- a bot's pull request: three ways GitHub can authenticate the person ---------------------------------------------

def test_a_bots_pull_request_pays_nobody_until_github_authenticates_a_person():
    got = paid(pull(DEVIN), issue(), [], [], [])
    assert got == {"id": None, "login": None, "kind": "payee",
                   "why": "devin-ai-integration[bot] is a bot account, and nothing GitHub authenticates names the person who ran it",
                   "fix": "A maintainer comments `/knos pay @login` on this pull request."}
    assert who.payee(pull(DEVIN))["id"] is None                                           # with nothing fetched: nobody
    # the pull request names a person in its assignees: that alone is the bot's word, and it tells them what to type
    named = paid(pull(DEVIN, assignees=[MONA, DEVIN]), issue(), [], [], [])
    assert named["id"] is None and named["fix"] == \
        "A maintainer comments `/knos pay @login` on this pull request, or @mona (named in its assignees) comments `/knos mine`."


def test_one_the_issue_is_one_persons_by_a_maintainers_assignment_or_their_own_take():
    by_maintainer = [assigned(MONA, HUBOT, T0 - 30 * DAY)]
    assert paid(pull(DEVIN), issue(MONA), by_maintainer, [], []) == \
        {"id": 4242, "login": "mona", "why": "issue #7 is theirs: maintainer @hubot assigned it to them"}
    took = [assigned(MONA, BOT, T0 - DAY)]
    take = [comment(5, MONA, "/knos take", stamp(T0 - DAY))]
    assert paid(pull(DEVIN), issue(MONA), took, [], take) == \
        {"id": 4242, "login": "mona", "why": "issue #7 is theirs: they took it with `/knos take`"}
    assert paid(pull(DEVIN), issue(MONA, DEVIN), took, [], take)["id"] == 4242             # a bot assignee is not a second person
    # the same assignment without an act GitHub authenticates names nobody
    for events, comments in ((took, []),                                                   # a workflow assigned them; they never asked
                             (took, [comment(5, EVE, "/knos take")]),                      # someone else's take
                             (took, None),                                                 # the issue's comments could not be read
                             ([assigned(MONA, TRIAGE, T0 - DAY)], take),                   # assigned by someone who cannot write
                             ([assigned(MONA, MONA, T0 - DAY)], take),                     # self-assigned, and cannot write
                             ([assigned(MONA, user("app[bot]", 77, "Bot"), T0 - DAY)], take),   # another app did it
                             ([], take), (None, take)):                                    # GitHub does not say who assigned them
        got = paid(pull(DEVIN), issue(MONA), events, [], comments)
        assert got["id"] is None and got["kind"] == "payee", (events, comments)
    assert paid(pull(DEVIN), issue(HUBOT), [assigned(HUBOT, HUBOT, T0 - DAY)], [], [])["id"] == 1   # a maintainer took their own issue
    # two people hold it: it is not one person's
    two = paid(pull(DEVIN), issue(MONA, EVE), [assigned(MONA, HUBOT, T0 - DAY), assigned(EVE, HUBOT, T0 - DAY)], [], [])
    assert two["id"] is None
    # a take that lapsed holds nothing
    lapsed = paid(pull(DEVIN), issue(MONA), [assigned(MONA, BOT, T0 - 8 * DAY)], [], take)
    assert lapsed["id"] is None and lapsed["kind"] == "payee"
    assert paid(pull(DEVIN), issue(MONA), by_maintainer, [], [], permission=None)["id"] is None   # nobody to ask who can write


def test_two_a_maintainer_names_the_person_on_the_pull_request():
    assert paid(pull(DEVIN), issue(), [], [comment(1, HUBOT, "/knos pay @mona"), comment(2, MONA, "thanks")], []) == \
        {"id": 4242, "login": "mona", "why": "maintainer @hubot named them with `/knos pay`"}
    for level in ("writer", "keeper"):                                                     # write and maintain are maintainers too
        assert paid(pull(DEVIN), issue(), [], [comment(1, user(level, 9), "/knos pay @Mona"), comment(2, MONA, "x")], [])["id"] == 4242
    # the newest counts: a maintainer can correct themselves
    corrected = [comment(1, HUBOT, "/knos pay @eve", "2026-10-01T10:00:00Z"), comment(2, HUBOT, "/knos pay @mona", "2026-10-01T11:00:00Z"),
                 comment(3, EVE, "hi"), comment(4, MONA, "hi")]
    assert paid(pull(DEVIN), issue(), [], corrected, [])["login"] == "mona"
    assert paid(pull(DEVIN), issue(), [], list(reversed(corrected)), [])["login"] == "mona"
    # what does not count: the label on a comment, an edit, a bot, the wrong place
    for bad in (comment(1, TRIAGE, "/knos pay @mona", association="MEMBER"),               # MEMBER is a label, not write access
                comment(1, EVE, "/knos pay @eve", association="OWNER"),
                comment(1, HUBOT, "/knos pay @mona", edited="2026-10-01T10:05:00Z"),      # anyone with write access can edit a comment
                comment(1, user("hubot", 1, "Bot"), "/knos pay @mona"),
                comment(1, HUBOT, "> /knos pay @mona"), comment(1, HUBOT, "/knos pay"), {"id": 1}, "noise"):
        assert paid(pull(DEVIN), issue(), [], [bad, comment(9, MONA, "x")], [])["id"] is None, bad
    assert paid(pull(DEVIN), issue(), [], [], [comment(1, HUBOT, "/knos pay @mona"), comment(2, MONA, "x")])["id"] is None   # on the issue: not here
    # the login must be a person GitHub knows: from what was fetched, else asked
    asked = []

    def lookup(login):
        asked.append(login)
        return {"alice": ALICE, "some-bot": user("some-bot", 9, "Bot"), "odd": {"login": "odd", "id": 5}}[login]
    assert paid(pull(DEVIN), issue(), [], [comment(1, HUBOT, "/knos pay @alice")], [], user=lookup)["id"] == 11 and asked == ["alice"]
    assert paid(pull(DEVIN, assignees=[ALICE]), issue(), [], [comment(1, HUBOT, "/knos pay @ALICE")], [], user=lookup)["id"] == 11 and asked == ["alice"]
    for login in ("ghost", "some-bot", "odd"):
        got = paid(pull(DEVIN), issue(), [], [comment(1, HUBOT, f"/knos pay @{login}")], [], user=lookup)
        assert got["id"] is None and got["why"] == f"maintainer @hubot named @{login}, which GitHub did not confirm as a person's account"
        assert got["fix"] == "A maintainer comments `/knos pay @login` on this pull request, with a person's login."
    assert paid(pull(DEVIN), issue(), [], [comment(1, HUBOT, "/knos pay @alice")], [])["id"] is None            # nobody to ask
    assert paid(pull(DEVIN), issue(), [], [comment(1, HUBOT, f"/knos pay @{DEVIN['login'][:5]}")], [], user=lookup)["id"] is None
    named_the_bot = paid(pull(DEVIN), issue(), [], [comment(1, HUBOT, "/knos pay @some-bot"), comment(2, user("some-bot", 9, "Bot"), "x")], [])
    assert named_the_bot["id"] is None and "did not confirm as a person's account" in named_the_bot["why"]
    # a broken instruction is not skipped in favour of someone's claim
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], [comment(1, MONA, "/knos mine"), comment(2, HUBOT, "/knos pay @ghost")], [], user=lookup)["id"] is None

    def down(login):
        raise OSError("502")
    unread = paid(pull(DEVIN), issue(), [], [comment(1, HUBOT, "/knos pay @mona"), comment(2, MONA, "x")], [], permission=down)
    assert unread["id"] is None and "GitHub did not answer who has write access; run this again" in unread["why"]


def test_three_a_person_the_pull_request_names_claims_it():
    assert paid(pull(DEVIN, assignees=[MONA, DEVIN]), issue(), [], [comment(1, MONA, "/knos mine")], []) == \
        {"id": 4242, "login": "mona", "why": "named in the assignees of devin-ai-integration[bot]'s pull request, and claimed it with `/knos mine`"}
    for bad in ([comment(1, EVE, "/knos mine")],                                           # not named in its assignees
                [comment(1, MONA, "/knos mine", edited="2026-10-01T10:05:00Z")],
                [comment(1, MONA, "this one is /knos mine")], [comment(1, MONA, "/knos mine please")],
                [comment(1, {**MONA, "type": "Bot"}, "/knos mine")], None):
        assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], bad, [])["id"] is None, bad
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], [], [comment(1, MONA, "/knos mine")])["id"] is None   # on the issue: not here
    both = paid(pull(DEVIN, assignees=[MONA, EVE]), issue(), [], [comment(1, MONA, "/knos mine"), comment(2, EVE, "/knos mine"),
                                                                 comment(3, MONA, "/knos mine", "2026-10-01T12:00:00Z")], [])
    assert both["id"] is None and both["why"] == "more than one person claimed devin-ai-integration[bot]'s pull request with `/knos mine` (@eve, @mona)"
    assert both["fix"] == "A maintainer decides: they comment `/knos pay @login` on this pull request."


def test_the_three_ways_are_tried_in_order():
    comments = [comment(1, EVE, "/knos mine"), comment(2, HUBOT, "/knos pay @alice"), comment(3, ALICE, "x")]
    held = [assigned(MONA, HUBOT, T0 - DAY)]
    assert paid(pull(DEVIN, assignees=[EVE]), issue(MONA), held, comments, [])["login"] == "mona"    # the issue's one person
    by_pay = paid(pull(DEVIN, assignees=[EVE]), issue(), [], comments, [])
    assert by_pay["login"] == "alice" and "`/knos pay`" in by_pay["why"]                               # then the maintainer's word
    assert paid(pull(DEVIN, assignees=[EVE]), issue(), [], comments[:1], [])["login"] == "eve"         # then the claim


def test_a_description_is_a_hint_to_show_and_never_decides():
    for line in ("Link to Devin session: https://x\nRequested by: @Mona", "PR created automatically by Jules for task 7 started by @mona",
                 "Knos-Pay-To: @mona."):
        got = paid(pull(DEVIN, body="Fixes #7\n\n" + line), issue(), [], [], [])
        assert got["id"] is None, line                                                     # 0.3.11 paid @mona here
        assert got["hint"] == "its text names @mona, which is a hint and decides nothing"
        assert got["fix"] == "A maintainer comments `/knos pay @mona` on this pull request."            # the exact comment
    co = "Fix the slug\n\nCo-authored-by: mona <4242+mona@users.noreply.github.com>"
    assert paid(pull(DEVIN), issue(), [], [], [], head_message=co)["hint"].startswith("its text names @mona")
    assert who.hinted(pull(DEVIN, body="Requested by: @alice\nKnos-Pay-To: @Bob"), co + "\nCo-authored-by: z <1+zed@users.noreply.github.com>") == \
        ["alice", "bob", "mona", "zed"]
    two = paid(pull(DEVIN, body="Requested by: @alice\nKnos-Pay-To: @bob"), issue(), [], [], [])
    assert two["hint"] == "its text names @alice, @bob, which is a hint and decides nothing" and "`/knos pay @login`" in two["fix"]
    # prose, quotes and code are not the description's own lines
    for noise in ("Builds on the work started by @mallory.", "> Knos-Pay-To: @mallory", "```\nKnos-Pay-To: @mallory\n```",
                  "~~~\nRequested by: @mallory\n~~~", "As requested by @mallory in the issue.", "requested by\n\n@mallory",
                  "Knos-Pay-To: @mallory " + "x" * 300):
        assert who.hinted(pull(DEVIN, body=noise)) == [], noise
    assert who.hinted(pull(DEVIN, body=None)) == [] == who.hinted({}, "Co-authored-by: x <x@example.com>\n" + "y" * 400)
    # a hint rides along with whoever GitHub's facts name, and changes nothing
    hinted = paid(pull(DEVIN, body="Requested by: @mallory", assignees=[MONA]), issue(), [], [comment(1, MONA, "/knos mine")], [])
    assert hinted["id"] == 4242 and hinted["hint"].startswith("its text names @mallory")
    t = time.monotonic()
    who.payee(pull(DEVIN, body="requested by @a" + " " * 60_000 + "x\n" + "y" * 900_000))
    assert time.monotonic() - t < 1                                                        # no pattern that can be made slow


# ---- an assigned issue is its assignee's -----------------------------------------------------------------------------

def test_an_assigned_issue_pays_only_its_assignees_pull_request():
    held = [assigned(MONA, HUBOT, T0 - 30 * DAY), assigned(HUBOT, HUBOT, T0 - 30 * DAY)]
    assert paid(pull(MONA), issue(HUBOT, MONA), held)["id"] == 4242
    theirs = paid(pull(EVE), issue(HUBOT, MONA), held)
    assert theirs == {"id": None, "login": None, "kind": "assigned",
                      "why": "issue #7 is assigned to @hubot, @mona; only an assignee's pull request is paid for it",
                      "fix": "A maintainer can change the issue's assignee; a `/knos take` lapses on the date shown."}
    assert paid(pull(EVE), issue(), [])["id"] == 666 == paid(pull(EVE), None, None)["id"]                # open to anyone
    assert paid(pull(EVE), issue(MONA), None)["kind"] == "assigned"                                    # when it was assigned is unknown: it holds
    # a take holds for the bounty's `reserve` days and says until when
    taken = [assigned(MONA, BOT, T0 - 2 * DAY)]
    got = paid(pull(EVE), issue(MONA), taken)
    assert got["why"] == f"issue #7 is assigned to @mona until {who.when(T0 + 5 * DAY)}; only an assignee's pull request is paid for it"
    assert paid(pull(EVE), issue(MONA), taken, now=T0 + 5 * DAY + 1)["id"] == 666                      # lapsed: anyone's is paid
    assert paid(pull(EVE), issue(MONA), taken, terms={**TERMS, "reserve": 1})["id"] == 666
    assert paid(pull(EVE), issue(MONA), taken, terms=None)["kind"] == "assigned"                       # no terms: nothing says it lapsed
    assert paid(pull(MONA), issue(MONA), taken, now=T0 + 30 * DAY)["id"] == 4242                       # the holder's own, lapsed or not
    # the agent an assignee ran: the bot opened it, the assignee is paid; and a bot the issue is assigned to
    mine = [comment(1, MONA, "/knos mine")]
    assert paid(pull(DEVIN, assignees=[MONA]), issue(MONA, EVE), held, mine, [])["id"] == 4242
    assert paid(pull(DEVIN, assignees=[ALICE]), issue(MONA, EVE), held, [comment(1, ALICE, "/knos mine")], [])["kind"] == "assigned"
    assert paid(pull(DEVIN, assignees=[ALICE]), issue(DEVIN), [assigned(DEVIN, HUBOT, T0)], [comment(1, ALICE, "/knos mine")], [])["id"] == 11
    assert who.excluded(issue(MONA), pull(EVE), {"id": 666}) and not who.excluded(issue(MONA), pull(EVE), {"id": 4242})
    assert who.excluded({"number": 7, "assignees": [{"login": "x"}]}, pull(EVE), {"id": 666}) == ""    # no account, no hold


def test_reservation_says_who_holds_the_issue_since_when_until_when_and_whether_it_lapsed():
    events = [assigned(MONA, HUBOT, T0 - 40 * DAY), assigned(MONA, HUBOT, T0 - 39 * DAY, "unassigned"),
              assigned(MONA, BOT, T0 - 3 * DAY),                                           # the newest assignment is the one that holds
              assigned(EVE, HUBOT, T0 - 100 * DAY), {"event": "labeled", "created_at": stamp(T0)}, "noise",
              {"event": "assigned", "assignee": DEVIN, "actor": HUBOT, "created_at": stamp(T0 - DAY)},   # the timeline's shape: `actor` did it
              {"event": "assigned", "assignee": ALICE, "assigner": HUBOT, "created_at": "not a time"}]
    holds = who.reservation(issue(MONA, EVE, DEVIN, ALICE, {"login": "nobody"}), events, TERMS, T0)
    assert holds == [who.Hold(4242, "mona", True, T0 - 3 * DAY, T0 + 4 * DAY, False, "github-actions[bot]", True),
                     who.Hold(666, "eve", True, T0 - 100 * DAY, None, False, "hubot", False),        # a person's assignment does not lapse
                     who.Hold(DEVIN["id"], DEVIN["login"], False, T0 - DAY, None, False, "hubot", False),
                     who.Hold(11, "alice", True, None, None, False, "", False)]
    later = who.reservation(issue(MONA), events, TERMS, T0 + 4 * DAY + 1)[0]
    assert later.lapsed and later.until == T0 + 4 * DAY
    assert not who.reservation(issue(MONA), events, TERMS, T0 + 4 * DAY)[0].lapsed                    # until, to the second
    assert who.reservation(issue(MONA), events, {**TERMS, "reserve": 0}, T0)[0].lapsed               # no reservations: none holds
    for terms in (None, {}, {"reserve": "7"}):
        assert who.reservation(issue(MONA), events, terms, T0 + 99 * DAY)[0].until is None           # no terms say how long
    assert who.reservation(issue(MONA), events, TERMS, None)[0].lapsed is False
    assert who.reservation(issue(MONA), None, TERMS, T0) == [who.Hold(4242, "mona", True, None, None, False, "", False)]
    assert who.reservation(None, events, TERMS, T0) == [] == who.reservation(issue(), events, TERMS, T0) == who.reservation({}, None, None, None)
    by_login = [{"event": "assigned", "assignee": MONA, "assigner": {"login": "github-actions[bot]"}, "created_at": stamp(T0)}]
    assert who.reservation(issue(MONA), by_login, TERMS, T0)[0].taken


# ---- /knos take, /knos release ---------------------------------------------------------------------------------------

def test_take_reserves_an_issue_nobody_holds():
    got = who.take(issue(), [], TERMS, MONA, T0)
    assert got == who.Outcome(f"Knos: issue #7 is reserved for @mona until {who.when(T0 + 7 * DAY)}. Open a pull request whose "
                              "description says `Fixes #7`; until then only yours is paid for it. After that it is open to everyone "
                              "again. `/knos release` gives it back sooner.", assign=("mona",), unassign=())
    # someone's lapsed take is cleared for the new one (a bot account is left as it is)
    stale = [assigned(EVE, BOT, T0 - 9 * DAY), assigned(DEVIN, BOT, T0 - 9 * DAY)]
    got = who.take(issue(EVE, DEVIN), stale, TERMS, MONA, T0)
    assert got.assign == ("mona",) and got.unassign == ("eve",) and got.reply.endswith("(@eve's reservation had lapsed.)")
    assert who.take(issue(DEVIN), [assigned(DEVIN, HUBOT, T0 - 9 * DAY)], TERMS, MONA, T0).assign == ()     # an agent a person assigned holds it
    assert who.take(issue(), [assigned(MONA, HUBOT, T0 - 50 * DAY), assigned(MONA, HUBOT, T0 - 49 * DAY, "unassigned")], TERMS, MONA, T0).assign == ("mona",)


def test_an_agents_own_account_takes_and_is_paid_only_where_the_order_was_funded_auto():
    # take: a Bot account reserves an `auto` order's issue as a person would; without `auto` it is refused as before
    got = who.take(issue(), [], TERMS, DEVIN, T0, auto=True)
    assert got.assign == (DEVIN["login"],) and got.reply.startswith(f"Knos: issue #7 is reserved for @{DEVIN['login']} until {who.when(T0 + 7 * DAY)}.")
    refusal = "Knos: `/knos take` is for people, not bot accounts. The person who runs the agent can take the issue from their own account."
    assert who.take(issue(), [], TERMS, DEVIN, T0) == who.Outcome(refusal)
    assert who.take(issue(), [], TERMS, BOT, T0, auto=True) == who.Outcome(refusal)                 # never the workflow's own token
    assert who.take(issue(), [], TERMS, {"login": "acme", "id": 5, "type": "Organization"}, T0, auto=True) == who.Outcome(refusal)
    assert who.take(issue(), [], TERMS, MONA, T0, auto=True).assign == ("mona",)                    # a person, as ever
    from knos import commands
    for auto, assign in ((True, (DEVIN["login"],)), (False, ())):
        assert who.answer(commands.parse("/knos take", False), DEVIN, issue=issue(), events=[], terms=TERMS, now=T0, auto=auto).assign == assign
    # every other command still asks for a person, `auto` or not
    bot = pull(DEVIN, assignees=[{**MONA, "type": "Bot"}])
    assert who.answer(commands.parse("/knos mine", True), {**MONA, "type": "Bot"}, pull=bot, permission=permission, now=T0, auto=True) \
        == who.Outcome(commands.reply("not_allowed", "mine"))
    # payee: on an `auto` order an open pull request pays its author, an agent's account too
    got = paid(pull(DEVIN), issue(), [], [], [], strict=True, auto=True)
    assert (got["id"], got["login"]) == (DEVIN["id"], DEVIN["login"]) and got["why"] == "the pull request's author, an agent's account: the order was funded `auto`"
    assert paid(pull(MONA), issue(), [], [], [], strict=True, auto=True)["why"] == "the pull request's author"
    # ... and where a human is required it still is: an order without `auto`, a tip, the workflow's own account
    assert paid(pull(DEVIN), issue(), [], [], [], strict=True)["id"] is None
    assert paid(pull(DEVIN, merged_at=stamp(T0)), None, None, [], None, strict=True, tip=True, auto=True)["id"] is None
    assert paid(pull(BOT), issue(), [], [], [], strict=True, auto=True)["id"] is None
    # what holds for a person holds for the agent: it must close the issue, a maintainer's reject stops it, a held issue is its holder's
    assert paid(pull(DEVIN, body="no issue"), issue(), [], [], [], strict=True, auto=True)["kind"] == "issue"
    assert paid(pull(DEVIN), issue(), [], [comment(1, HUBOT, "/knos reject")], [], strict=True, auto=True)["kind"] == "rejected"
    assert paid(pull(DEVIN), issue(MONA), [assigned(MONA, BOT, T0 - DAY)], [], [], strict=True, auto=True)["kind"] == "assigned"
    assert paid(pull(DEVIN), issue(DEVIN), [assigned(DEVIN, BOT, T0 - DAY)], [], [], strict=True, auto=True)["id"] == DEVIN["id"]


def test_take_changes_nothing_when_it_cannot_reserve():
    def said(*args) -> str:
        got = who.take(*args)
        assert got.assign == () == got.unassign and got.reply.startswith("Knos: "), got
        return got.reply
    assert said(issue(), [], None, MONA, T0) == "Knos: issue #7 has no bounty, so there is nothing to reserve."
    assert said({**issue(), "state": "closed"}, [], TERMS, MONA, T0) == "Knos: issue #7 is closed, so there is nothing to reserve."
    assert who.take({**issue(), "state": "open"}, [], TERMS, MONA, T0).assign == ("mona",)
    assert said(issue(), [], TERMS, DEVIN, T0) == "Knos: `/knos take` is for people, not bot accounts. The person who runs the agent can take the issue from their own account."
    assert said(issue(MONA), [assigned(MONA, BOT, T0 - DAY)], TERMS, MONA, T0) == f"Knos: you already hold issue #7 until {who.when(T0 + 6 * DAY)}."
    assert said(issue(MONA), [assigned(MONA, HUBOT, T0 - DAY)], TERMS, MONA, T0) == "Knos: you already hold issue #7."
    lapsed = said(issue(MONA), [assigned(MONA, BOT, T0 - 8 * DAY)], TERMS, MONA, T0)
    assert lapsed.startswith(f"Knos: your reservation of issue #7 lapsed on {who.when(T0 - DAY)}, and taking it again does not renew it.")
    assert "open to everyone now, you included" in lapsed
    with_other = said(issue(MONA, EVE), [assigned(MONA, BOT, T0 - 8 * DAY), assigned(EVE, HUBOT, T0 - DAY)], TERMS, MONA, T0)
    assert with_other.startswith("Knos: issue #7 is assigned to @eve, so only their pull request is paid.")   # lapsed, and someone else holds it
    assert said(issue(EVE), [assigned(EVE, BOT, T0 - DAY)], TERMS, MONA, T0) == \
        (f"Knos: issue #7 is assigned to @eve until {who.when(T0 + 6 * DAY)}, so only their pull request is paid until then. "
         "After that it is open to everyone, and you can take it.")
    assert said(issue(EVE), [assigned(EVE, HUBOT, T0 - 90 * DAY)], TERMS, MONA, T0) == \
        "Knos: issue #7 is assigned to @eve, so only their pull request is paid. A maintainer can change the assignee."
    assert said(issue(EVE), None, TERMS, MONA, T0).startswith("Knos: issue #7 is assigned to @eve, so only their pull request is paid.")
    assert said(issue(), [], {**TERMS, "reserve": 0}, MONA, T0).startswith("Knos: the bounty on issue #7 takes no reservations.")
    assert said(issue(), None, TERMS, MONA, T0) == "Knos: GitHub did not answer for issue #7's history, so nothing was reserved. Comment `/knos take` again."
    # a reservation is given once: released or removed, it is not taken again
    before = [assigned(MONA, BOT, T0 - 20 * DAY), assigned(MONA, MONA, T0 - 18 * DAY, "unassigned")]
    again = said(issue(), before, TERMS, MONA, T0)
    assert again.startswith(f"Knos: you took issue #7 before, on {who.when(T0 - 20 * DAY)}, and a reservation is given once.")
    assert "you can still open the pull request" in again and "A maintainer can also assign you." in again


def test_release_gives_back_only_what_the_commenter_holds():
    for events in ([assigned(MONA, BOT, T0 - DAY)], [assigned(MONA, HUBOT, T0 - DAY)], [assigned(MONA, BOT, T0 - 30 * DAY)], None):
        assert who.release(issue(MONA), events, TERMS, MONA, T0) == \
            who.Outcome("Knos: @mona gave issue #7 back. It is open to everyone. `/knos take` reserves it.", unassign=("mona",))
    both = [assigned(MONA, HUBOT, T0 - DAY), assigned(EVE, HUBOT, T0 - DAY)]
    assert who.release(issue(MONA, EVE), both, TERMS, MONA, T0) == \
        who.Outcome("Knos: @mona gave issue #7 back. It is still assigned to @eve.", unassign=("mona",))
    gone = [assigned(MONA, HUBOT, T0 - DAY), assigned(EVE, BOT, T0 - 30 * DAY)]            # the other's take had lapsed: nobody is left
    assert who.release(issue(MONA, EVE), gone, TERMS, MONA, T0).reply.endswith("It is open to everyone. `/knos take` reserves it.")
    assert who.release(issue(MONA), [], {**TERMS, "reserve": 0}, MONA, T0).reply == "Knos: @mona gave issue #7 back. It is open to everyone."
    nothing = who.release(issue(EVE), [assigned(EVE, HUBOT, T0)], TERMS, MONA, T0)
    assert nothing == who.Outcome("Knos: you do not hold issue #7, so nothing changed. It is assigned to @eve; a maintainer can change that.")
    assert who.release(issue(), [], TERMS, MONA, T0).reply == "Knos: you do not hold issue #7, so nothing changed."
    assert who.release(issue(EVE), [assigned(EVE, HUBOT, T0)], TERMS, HUBOT, T0).unassign == ()         # not even a maintainer releases another
    assert who.release(issue(MONA), [], None, MONA, T0) == who.Outcome("Knos: issue #7 has no bounty, so there is nothing to release.")


# ---- /knos reject ----------------------------------------------------------------------------------------------------

def test_a_maintainers_reject_before_the_merge_means_nobody_is_paid():
    no = comment(3, HUBOT, "/knos reject not `the` fix we want", "2026-10-01T10:00:00Z")
    assert who.rejected(pull(), [comment(1, MONA, "x"), no], permission) == \
        {"by": "hubot", "reason": "not the fix we want", "at": "2026-10-01T10:00:00Z", "comment": 3}
    got = paid(pull(), issue(), [], [no], [])
    assert got == {"id": None, "login": None, "kind": "rejected", "why": "@hubot rejected this pull request for the bounty (not the fix we want)",
                   "fix": "To undo, @hubot deletes that `/knos reject` comment."}
    assert paid(pull(), issue(), [], [comment(3, HUBOT, "/knos reject")], [])["why"] == "@hubot rejected this pull request for the bounty"
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], [comment(1, MONA, "/knos mine"), no], [])["kind"] == "rejected"
    # before the merge only: once a payment is made it is final
    merged = pull(merged_at="2026-10-01T10:00:01Z")
    assert who.rejected(merged, [no], permission)["by"] == "hubot"
    for late in ("2026-10-01T10:00:00Z", "2026-10-01T09:00:00Z"):
        assert who.rejected(pull(merged_at=late), [no], permission) is None and paid(pull(merged_at=late), issue(), [], [no], [])["id"] == 4242
    assert who.rejected(merged, [{**no, "created_at": "?", "updated_at": "?"}], permission) is None    # when it was written is unknown
    # who and what does not count
    for bad in (comment(3, EVE, "/knos reject"), comment(3, TRIAGE, "/knos reject", association="MEMBER"),
                comment(3, HUBOT, "/knos reject", edited="2026-10-01T11:00:00Z"), comment(3, {**HUBOT, "type": "Bot"}, "/knos reject"),
                comment(3, HUBOT, "I would /knos reject this"), comment(3, HUBOT, "> /knos reject")):
        assert who.rejected(pull(), [bad], permission) is None, bad
    assert who.rejected(pull(), None, permission) is None and who.rejected(pull(), [no], None) is None
    newest = who.rejected(pull(), [no, comment(4, user("writer", 9), "/knos reject twice", "2026-10-01T11:00:00Z")], permission)
    assert newest["by"] == "writer" and newest["comment"] == 4


def test_at_the_merge_what_github_did_not_answer_pays_nobody_yet():
    """A payment is final, so where money moves nothing is decided on a read that failed: it is run again."""
    no = comment(3, HUBOT, "/knos reject")

    def down(login):
        raise OSError("502")
    assert paid(pull(), issue(), [], [], [], strict=True)["id"] == 4242 == paid(pull(), issue(), None, [], None, strict=True)["id"]
    for args, said in (((pull(), None, [], [], []), "GitHub did not give the issue, so who is paid cannot be decided yet"),
                       ((pull(), issue(), [], None, []), "GitHub did not give this pull request's comments, so who is paid cannot be decided yet"),
                       ((pull(), issue(MONA), None, [], []), "GitHub did not say who assigned the issue, and when, so who is paid cannot be decided yet")):
        assert paid(*args)["id"] == 4242                                                   # before a merge: nothing is held against it
        got = paid(*args, strict=True)
        assert got == {"id": None, "login": None, "kind": "unread", "why": said, "fix": "Run this again."}
    # an assignee nobody can date: whether it still holds the issue is not known, so it is not called anyone's yet
    assert paid(pull(EVE), issue(MONA), None, [], [])["kind"] == "assigned" and paid(pull(EVE), issue(MONA), None, [], [], strict=True)["kind"] == "unread"
    # a reject whose writer GitHub would not vouch for either way is not waved through
    assert paid(pull(), issue(), [], [no], [], permission=down)["id"] == 4242
    for unknown in (down, None):
        got = paid(pull(), issue(), [], [no], [], permission=unknown, strict=True)
        assert got["kind"] == "unread" and got["why"].startswith("GitHub did not say whether @hubot, who wrote `/knos reject`, can write")
    assert paid(pull(), issue(), [], [comment(3, EVE, "/knos reject")], [], strict=True)["id"] == 4242      # GitHub answered: she cannot
    assert paid(pull(), issue(), [], [no], [], strict=True)["kind"] == "rejected"
    late = pull(merged_at="2026-10-01T09:00:00Z")
    assert paid(late, issue(), [], [no], [], permission=down, strict=True)["id"] == 4242                    # written after the merge: no question
    assert paid(pull(DEVIN), issue(), [], [], [], strict=True)["kind"] == "payee"


def test_a_description_edited_after_the_merge_closes_nothing_where_money_moves():
    """The merge accepted what the description said then. Its author can edit it afterwards, and what it closes
    follows the edit, so `edited` (knos.closing.edited_late) decides at the merge: when it was edited late, nobody
    is paid; when GitHub did not say, nothing is decided; before a merge, and for a tip, it is not asked."""
    merged = pull(merged_at="2026-10-01T09:00:00Z")
    assert paid(merged, issue(), [], [], [], strict=True)["id"] == 4242 == paid(merged, issue(), [], [], [], strict=True, edited=False)["id"]
    got = paid(merged, issue(), [], [], [], strict=True, edited=1_790_859_600.0)
    assert got == {"id": None, "login": None, "kind": "issue", "fix": "",
                   "why": "its description was edited on 2026-10-01 13:00 UTC, after it was merged, so what it says it closes no longer "
                          "counts (anyone who can edit it could add `Fixes #7` later)"}
    assert paid(merged, issue(), [], [], [], strict=True, edited=None) == {
        "id": None, "login": None, "kind": "unread", "fix": "Run this again.",
        "why": "GitHub did not say whether this pull request's description was edited after it was merged, so who is paid cannot be decided yet"}
    for edited in (None, 1_790_859_600.0):
        assert paid(pull(), issue(), [], [], [], strict=True, edited=edited)["id"] == 4242      # not merged: paid by its checks, nothing to be late for
        assert paid(merged, issue(), [], [], [], edited=edited)["id"] == 4242                   # advice, before money moves
        assert paid(merged, None, None, [], None, strict=True, tip=True, edited=edited)["id"] == 4242      # a tip names the pull request itself


def test_at_the_merge_a_bots_pull_request_is_not_decided_on_half_an_answer():
    """Each of the three ways rests on something GitHub says. Before a merge a way that could not be read names
    nobody and the next is tried; where money moves the next way is not tried: the first might have named another."""
    calls = []

    def down(login):
        calls.append(login)
        raise OSError("502")

    def said(what: str) -> dict:
        return {"id": None, "login": None, "kind": "unread", "fix": "Run this again.",
                "why": f"GitHub did not {what}, so who is paid cannot be decided yet"}
    claim = comment(1, MONA, "/knos mine")
    # (1) a take whose comment could not be read; an assignment whose maker GitHub would not vouch for
    took, by_hubot = [assigned(MONA, BOT, T0 - DAY)], [assigned(MONA, HUBOT, T0 - DAY)]
    assert paid(pull(DEVIN), issue(MONA), took, [], None, strict=True) == said("give the issue's comments")
    assert paid(pull(DEVIN), issue(MONA), took, [], [comment(5, MONA, "/knos take")], strict=True)["id"] == 4242
    assert paid(pull(DEVIN), issue(MONA), took, [], [], strict=True)["kind"] == "payee"                # read, and they never asked
    assert paid(pull(DEVIN), issue(MONA), by_hubot, [], [], permission=down, strict=True) == \
        said("say whether @hubot, who assigned the issue, can write to the repository")
    assert paid(pull(DEVIN), issue(MONA), by_hubot, [], [], permission=None, strict=True)["kind"] == "unread"
    loose = paid(pull(DEVIN), issue(MONA), by_hubot, [], [], permission=down)
    assert loose["kind"] == "payee" and "GitHub did not answer who has write access; run this again" in loose["why"]
    assert paid(pull(DEVIN), issue(MONA), [assigned(MONA, TRIAGE, T0 - DAY)], [], [], strict=True)["kind"] == "payee"   # answered: cannot write
    assert paid(pull(DEVIN), issue(MONA), [], [], [], strict=True)["kind"] == "payee"                  # read: GitHub names no assigner
    # (2) a `/knos pay` whose writer GitHub would not vouch for is not skipped in favour of a claim
    pay = [comment(2, HUBOT, "/knos pay @alice"), comment(3, ALICE, "x"), claim]
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], pay, [])["login"] == "alice"
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], pay, [], permission=down)["login"] == "mona"     # advisory: the next way
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], pay, [], permission=down, strict=True) == \
        said("say whether @hubot, who wrote `/knos pay`, can write to the repository")
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], [comment(2, EVE, "/knos pay @eve"), claim], [], strict=True)["login"] == "mona"
    # the login a maintainer named, when GitHub would not say whose it is
    def lookup(login):
        if login == "ghost":
            return None                                                                    # GitHub answered: nobody's
        raise OSError("502")
    asks = [comment(2, HUBOT, "/knos pay @alice"), claim]
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], asks, [], user=lookup, strict=True) == said("say whose account @alice is")
    assert "did not confirm as a person's account" in paid(pull(DEVIN, assignees=[MONA]), issue(), [], asks, [], user=lookup)["why"]
    nobodys = paid(pull(DEVIN), issue(), [], [comment(2, HUBOT, "/knos pay @ghost")], [], user=lookup, strict=True)
    assert nobodys["kind"] == "payee" and "did not confirm as a person's account" in nobodys["why"]
    # (3) rests on the pull request alone
    assert paid(pull(DEVIN, assignees=[MONA]), issue(), [], [claim], None, permission=down, strict=True)["id"] == 4242
    # GitHub is asked once about each account, however many comments they wrote
    calls.clear()
    rejects = [comment(i, HUBOT, "/knos reject", f"2026-10-01T10:00:0{i}Z") for i in range(4)]
    assert paid(pull(), issue(), [], rejects, [], permission=down, strict=True)["kind"] == "unread" and calls == ["hubot"]
    seen = []

    def answers(login):
        seen.append(login)
        return permission(login)
    twice = [comment(1, HUBOT, "/knos reject"), comment(2, EVE, "/knos reject"), comment(3, EVE, "/knos pay @eve"), comment(4, HUBOT, "/knos pay @mona")]
    assert paid(pull(DEVIN), issue(), [], twice, [], permission=answers, strict=True)["kind"] == "rejected" and sorted(seen) == ["eve", "hubot"]


def test_at_the_merge_the_pull_request_must_close_the_issue_it_is_paid_for():
    """The bounty is for the pull request that closes the issue: GitHub lists the issue among those it closes (a
    maintainer may have linked it by hand), or the description closes it with one of GitHub's keywords."""
    def base(ref="main"):
        return {"ref": ref, "repo": {"full_name": "octo/widgets", "default_branch": "main"}}
    for closes, body in (([7], "no keyword at all"), ([3, 7], "Fixes #3"), (None, "Fixes #7"), (None, "Resolves: octo/widgets#7"),
                         ([], "Fixes #7"), ([8], "Fixes #7")):                             # either says so: it closes it
        assert paid({**pull(body=body), "base": base()}, issue(), [], [], [], strict=True, closes=closes)["id"] == 4242, (closes, body)
    for closes in (None, [], [8]):
        for body in ("Related to #7", "Fixes #8", "Fixes other/repo#7", None):
            got = paid({**pull(body=body), "base": base()}, issue(), [], [], [], strict=True, closes=closes)
            assert got == {"id": None, "login": None, "kind": "issue", "why": "this pull request does not close issue #7",
                           "fix": "Its description must say `Fixes #7`."}, (closes, body)
    other = paid({**pull(), "base": base("release/1.x")}, issue(), [], [], [], strict=True)
    assert other["kind"] == "issue" and other["why"] == ("this pull request is against `release/1.x`, and GitHub closes an issue only "
                                                         "from a pull request against the default branch")
    assert paid({**pull(), "base": base("release/1.x")}, issue(), [], [], [], strict=True, closes=[7])["id"] == 4242   # GitHub linked it by hand
    assert paid({**pull(), "base": {"ref": "dev"}}, issue(), [], [], [], strict=True)["id"] == 4242                   # the default is not known
    assert paid(pull(body="no keyword"), issue(), [], [], [])["id"] == 4242                # before a merge the check says who would be paid
    # a rejection, and a read that failed, are said first
    assert paid(pull(body="x"), issue(), [], [comment(3, HUBOT, "/knos reject")], [], strict=True, closes=[])["kind"] == "issue"
    assert paid(pull(body="x"), None, [], [], [], strict=True, closes=[])["kind"] == "unread"


def test_a_tip_goes_to_the_person_behind_the_pull_request_whatever_was_said_about_a_bounty():
    """`/knos tip` pays partial work on a merged pull request: often the very one a maintainer rejected for the
    bounty. It is decided on the pull request alone, and like every payment never on a read that failed."""
    def down(login):
        raise OSError("502")
    merged = pull(merged_at="2026-10-01T12:00:00Z")
    no = comment(3, HUBOT, "/knos reject only half of it", "2026-10-01T10:00:00Z")
    assert paid(merged, issue(), [], [no], [])["kind"] == "rejected"                       # the bounty: no
    assert paid(merged, issue(EVE), None, [no], None, tip=True) == {"id": 4242, "login": "mona", "why": "the pull request's author"}
    assert paid(merged, None, None, None, None, permission=down, tip=True)["id"] == 4242   # a person's: nothing to read
    assert paid(pull(body="no keyword", merged_at="2026-10-01T12:00:00Z"), None, strict=True, tip=True)["id"] == 4242   # nothing to close
    assert paid(pull(), tip=True) == {"id": None, "login": None, "kind": "unmerged", "why": "this pull request is not merged",
                                      "fix": "A tip is for a merged pull request: merge it first."}
    assert paid({**pull(), "merged": True}, tip=True)["id"] == 4242
    # a bot's: a maintainer's word or an assignee's claim on the pull request; who holds an issue is not asked
    bot = pull(DEVIN, assignees=[MONA], merged_at="2026-10-01T12:00:00Z")
    claim = comment(1, MONA, "/knos mine")
    assert paid(bot, issue(ALICE), [assigned(ALICE, HUBOT, T0 - DAY)], [claim], [], tip=True)["id"] == 4242
    assert paid(bot, issue(ALICE), [assigned(ALICE, HUBOT, T0 - DAY)], [claim], [])["login"] == "alice"       # the bounty: the issue's holder
    assert paid(bot, None, None, [comment(2, HUBOT, "/knos pay @alice"), comment(3, ALICE, "x"), claim], None, tip=True)["login"] == "alice"
    assert paid(bot, None, None, [], None, tip=True)["kind"] == "payee"
    unread = paid(bot, None, None, None, None, tip=True)
    assert unread["kind"] == "unread" and unread["why"].startswith("GitHub did not give this pull request's comments")
    half = paid(bot, None, None, [comment(2, HUBOT, "/knos pay @alice"), claim], None, permission=down, tip=True)
    assert half["kind"] == "unread" and "who wrote `/knos pay`" in half["why"]              # not the claim in its place


# ---- one comment, answered -------------------------------------------------------------------------------------------

def test_every_knos_comment_gets_an_answer_and_only_who_github_vouches_for_is_obeyed():
    from knos import commands
    ADDR = f"/knos address {ADDRESS}"

    def answer(body, commenter, on_pull=True, **kw):
        kw.setdefault("permission", permission)
        kw.setdefault("now", T0)
        return who.answer(commands.parse(body, on_pull), commenter, **kw)
    assert answer("looks good to me", MONA) is None                                        # no command: no reply
    # not a command as written: the reply says what to type
    for body, on_pull, start in (("/knos frobnicate", True, "Knos: `frobnicate` is not a command."),
                                 ("/knos pay", True, "Knos: that was not understood: name one GitHub account."),
                                 ("/knos take", True, "Knos: `/knos take` belongs on the issue, not on a pull request."),
                                 ("/knos mine", False, "Knos: `/knos mine` belongs on the pull request, not on an issue.")):
        got = answer(body, MONA, on_pull)
        assert got.reply.startswith(start) and got.then == "" and got.assign == () == got.unassign, body
    assert answer("/knos", MONA).reply.startswith("Knos acts on the first line of a comment that starts with `/knos`:")
    # what needs the chain is handed on: who may spend is decided there
    assert answer("/knos fund 20", EVE, False) == who.Outcome("", then="fund") and answer("/knos status", EVE) == who.Outcome("", then="status")
    done = pull(merged_at="2026-10-01T12:00:00Z")
    assert answer("/knos tip 5", HUBOT, pull=done) == who.Outcome("", then="tip")
    assert answer("/knos tip 5", HUBOT, pull=pull()).reply == "Knos: this pull request is not merged. A tip is for a merged pull request: merge it first."
    assert answer("/knos settle", EVE, pull=done) == who.Outcome("Knos: trying this pull request's payment again. The result follows here.", then="settle")
    assert answer("/knos settle", EVE, pull={**pull(), "merged": True}).then == "settle"
    assert answer("/knos settle", EVE, pull=pull()) == who.Outcome("Knos: this pull request is not merged. Its payment is tried once it is.")
    assert answer("/knos settle", EVE) == who.Outcome("Knos: this pull request is not merged. Its payment is tried once it is.")
    # take and release: the assignees to change
    took = answer("/knos take", MONA, False, issue=issue(), events=[], terms=TERMS)
    assert took.assign == ("mona",) and took.reply.startswith("Knos: issue #7 is reserved for @mona until ")
    assert answer("/knos take", MONA, False, issue=issue(), events=[]).reply == "Knos: issue #7 has no bounty, so there is nothing to reserve."
    assert answer("/knos release", MONA, False, issue=issue(MONA), events=[], terms=TERMS).unassign == ("mona",)
    assert who.answer(commands.parse("/knos take", False), MONA, issue=issue(), events=[], terms=TERMS).assign == ("mona",)   # the clock is read
    # a maintainer's commands: whoever GitHub says can write, now
    bot = pull(DEVIN, assignees=[MONA])
    said = [comment(1, HUBOT, "/knos pay @mona"), comment(2, MONA, "x")]
    assert answer("/knos pay @mona", HUBOT, pull=bot, pull_comments=said).reply == \
        "Knos: noted. This pull request pays @mona: maintainer @hubot named them with `/knos pay`."
    assert answer("/knos pay @eve", HUBOT, pull=pull(), pull_comments=[]).reply == "Knos: noted. This pull request pays @mona: the pull request's author."
    for name, body in (("pay", "/knos pay @eve"), ("reject", "/knos reject")):
        assert answer(body, EVE, pull=bot) == who.Outcome(commands.reply("not_allowed", name)), name
        assert answer(body, TRIAGE, pull=bot).reply.startswith(f"Knos: `/knos {name}` is for people with write access to this repository.")
        for unknown in (None, lambda login: 1 / 0):
            assert answer(body, HUBOT, pull=bot, permission=unknown) == who.Outcome(
                "Knos: GitHub did not answer whether @hubot can write to this repository, so nothing was noted. Post the comment again.")
    assert answer("/knos reject too broad", HUBOT, pull=bot).reply.startswith(
        "Knos: noted. This pull request does not take the bounty (rejected by @hubot: too broad).")
    assert answer("/knos reject", HUBOT, pull=done).reply == ("Knos: this pull request is already merged. `/knos reject` counts only "
                                                              "before the merge: a payment that was made is final.")
    # /knos mine: a person the bot's pull request names
    claim = [comment(1, MONA, "/knos mine")]
    assert answer("/knos mine", MONA, pull=bot, pull_comments=claim).reply == (
        "Knos: noted. This pull request pays @mona: named in the assignees of devin-ai-integration[bot]'s pull request, and claimed "
        "it with `/knos mine`.")
    held = answer("/knos mine", MONA, pull=bot, pull_comments=claim, issue=issue(EVE), events=[assigned(EVE, BOT, T0 - DAY)], terms=TERMS)
    assert held.reply.startswith("Knos: nobody is paid for this pull request yet: issue #7 is assigned to @eve until ")
    theirs = answer("/knos mine", MONA, pull=bot, pull_comments=claim, issue=issue(EVE), events=[assigned(EVE, HUBOT, T0 - DAY)])
    assert theirs.reply == "Knos: this pull request pays @eve, not @mona: issue #7 is theirs: maintainer @hubot assigned it to them."
    assert answer("/knos mine", EVE, pull=bot, pull_comments=[comment(1, EVE, "/knos mine")]) == who.Outcome(commands.reply("not_allowed", "mine"))
    assert answer("/knos mine", {**MONA, "type": "Bot"}, pull=bot) == who.Outcome(commands.reply("not_allowed", "mine"))
    assert answer("/knos mine", EVE, pull={**bot, "assignees": [EVE, "noise"]}, pull_comments=[comment(1, EVE, "/knos mine")]).reply.startswith(
        "Knos: noted. This pull request pays @eve")
    assert answer("/knos mine", EVE, pull=pull()).reply == ("Knos: a person opened this pull request, so it pays them (@mona). `/knos mine` "
                                                            "is for a pull request a bot account opened.")
    # /knos address: the person the pull request pays
    noted = answer(ADDR, MONA, pull=pull(), pull_comments=[comment(1, MONA, ADDR)])
    assert noted.reply.startswith(f"Knos: noted. @mona's payment for this pull request goes to {ADDRESS}, unless a wallet is bound")
    rejected = [comment(1, HUBOT, "/knos reject"), comment(2, MONA, ADDR)]
    assert answer(ADDR, MONA, pull=pull(), pull_comments=rejected).reply.startswith("Knos: noted.")    # a tip would still pay them
    assert answer(ADDR, EVE, pull=pull(), pull_comments=[]) == who.Outcome(commands.reply("not_allowed", "address"))
    assert answer(ADDR, MONA, pull=bot, pull_comments=[*claim, comment(2, MONA, ADDR)]).reply.startswith("Knos: noted. @mona's payment")
    early = answer(ADDR, MONA, pull=bot, pull_comments=[comment(2, MONA, ADDR)])
    assert early.reply == ("Knos: `/knos address` is for the person this pull request pays. An address counts once this pull request "
                           "pays you: if an agent opened it for you and you are one of its assignees, comment `/knos mine`; or a "
                           "maintainer comments `/knos pay @you`. Then post the address again.")
    assert answer(ADDR, EVE, pull=bot, pull_comments=[*claim, comment(2, EVE, ADDR)]) == who.Outcome(commands.reply("not_allowed", "address"))
    assert answer(ADDR, {"login": "ghost"}, pull={"user": {"login": "x"}}) == who.Outcome(commands.reply("not_allowed", "address"))
    for got in (noted, early, held, took):
        assert not got.reply.startswith("/knos")                                           # a reply is never a command


# ---- the payout address ----------------------------------------------------------------------------------------------

def test_the_payout_address_is_the_bound_wallet_else_the_payees_own_unedited_comment():
    mona = {"id": 4242, "login": "mona", "why": "the pull request's author"}
    comments = [comment(1, MONA, f"/knos address {OTHER}", "2026-10-01T10:00:00Z"),
                comment(2, MONA, f"my wallet:\n/knos address {ADDRESS}", "2026-10-01T11:00:00Z"),
                comment(3, EVE, f"/knos address {OTHER}", "2026-10-01T12:00:00Z"),                     # not the payee's
                comment(4, MONA, "/knos address nonsense", "2026-10-01T13:00:00Z"), comment(5, MONA, "thanks", "2026-10-01T14:00:00Z"), "noise"]
    assert who.payout_address(mona, comments) == {"address": ADDRESS, "from": "comment", "comment": 2,
                                                  "why": "@mona's `/knos address` comment on this pull request"}
    assert who.payout_address(mona, list(reversed(comments)))["address"] == ADDRESS                   # the newest, whatever the order
    assert who.payout_address(mona, comments, bound=OTHER) == {"address": OTHER, "from": "bound",
                                                               "why": "the wallet bound to @mona's GitHub account"}
    for none in ([], None, comments[2:]):
        got = who.payout_address(mona, none)
        assert got["address"] is None and got["from"] is None and "the bounty is held for them until they bind a wallet" in got["why"]
    # an edited comment never counts, and the address it replaced is not used in its place
    edited = [comments[0], comment(2, MONA, f"/knos address {ADDRESS}", "2026-10-01T11:00:00Z", edited="2026-10-01T11:05:00Z")]
    got = who.payout_address(mona, edited)
    assert got["address"] is None and "was edited, so it does not count" in got["why"] and "again in a new comment" in got["why"]
    assert who.payout_address(mona, [*edited, comment(6, MONA, f"/knos address {ADDRESS}", "2026-10-01T12:00:00Z")])["address"] == ADDRESS
    assert who.payout_address({"id": None, "why": "x"}, comments, bound=OTHER) == {"address": None, "from": None, "why": "nobody is paid"}


# ---- small things everything above rests on --------------------------------------------------------------------------

def test_a_comment_counts_only_as_it_was_first_written():
    assert who.unedited(comment(1, MONA, "x")) and not who.unedited(comment(1, MONA, "x", edited="2026-10-01T10:00:01Z"))
    assert not who.unedited({"body": "x"}) and not who.unedited({"created_at": "2026-10-01T10:00:00Z"})
    assert not who.unedited({"created_at": None, "updated_at": None})


def test_a_maintainer_is_whoever_github_says_can_write_now():
    assert [who.is_maintainer(x, permission) for x in ("hubot", "writer", "keeper", "tri", "eve")] == [True, True, True, False, False]
    assert who.is_maintainer("x", lambda login: "ADMIN") is True and who.is_maintainer("x", lambda login: None) is False
    assert who.is_maintainer("", permission) is None and who.is_maintainer("hubot", None) is None

    def down(login):
        raise OSError("timeout")
    assert who.is_maintainer("hubot", down) is None


def test_times_are_githubs():
    assert who._ts("2026-10-02T12:00:00Z") == 1790942400.0 == who._ts("2026-10-02T13:00:00+01:00") == who._ts("2026-10-02T12:00:00")
    assert who._ts(None) is None and who._ts("soon") is None and who.when(1790942400) == "2026-10-02 12:00 UTC"


def test_what_payee_needs_is_read_from_github_in_one_place():
    full = [comment(i, MONA, "x") for i in range(100)]
    hub = Hub({"repos/o/r/issues/7": issue(MONA), "repos/o/r/issues/7/events": [assigned(MONA, HUBOT, T0)],
               "repos/o/r/issues/12/comments?per_page=100&page=1": full, "repos/o/r/issues/12/comments?per_page=100&page=2": full[:3],
               "repos/o/r/issues/7/comments": [comment(1, MONA, "/knos take")],
               "repos/o/r/collaborators/hubot/permission": {"permission": "admin", "role_name": "admin", "user": HUBOT},
               "users/mona": MONA})
    facts = who.read("o/r", 12, "7", hub)
    assert facts["issue"]["number"] == 7 and len(facts["events"]) == 1 and len(facts["pull_comments"]) == 103 and len(facts["issue_comments"]) == 1
    assert who.read("o/r", 12, 7, hub)["issue"]["number"] == 7
    assert who.permission_of("o/r", hub)("hubot") == "admin" and who.user_of(hub)("mona") == MONA
    paid_ = who.payee(pull(DEVIN), facts["issue"], facts["events"], facts["pull_comments"], facts["issue_comments"],
                      who.permission_of("o/r", hub), TERMS, T0, "", who.user_of(hub))
    assert paid_["id"] == 4242 and "maintainer @hubot assigned it to them" in paid_["why"]
    # no issue to ask about; and what GitHub does not give is None, never a guess
    assert who.read("o/r", 12, "", hub) == {"issue": None, "events": None, "pull_comments": facts["pull_comments"], "issue_comments": None}
    assert who.read("o/r", 12, "seven", hub)["issue"] is None
    for silent in (Hub({"repos/o/r/issues/8": ["not an issue"]}), Hub()):
        assert who.read("o/r", 99, "8", silent) == {"issue": None, "events": None, "pull_comments": None, "issue_comments": None}
    assert who.is_maintainer("eve", who.permission_of("o/r", hub)) is None                              # GitHub did not answer: unknown, not "no"

    def unknown_there(path):
        import urllib.error
        raise urllib.error.HTTPError(f"https://api.github.com/{path}", 404, "Not Found", None, None)
    assert who.permission_of("o/r", unknown_there)("ghost") == "none" and who.is_maintainer("ghost", who.permission_of("o/r", unknown_there)) is False
    assert who.user_of(unknown_there)("ghost") is None                                                  # nobody's account: an answer
    try:
        who.user_of(Hub())("mona")                                                                      # no answer is not "nobody's"
        raise AssertionError("a read that failed was taken for an answer")
    except OSError:
        pass
    # so a stranger's `/knos reject` cannot hold a payment up: GitHub answers for them, and the answer is no
    no = [comment(3, user("ghost", 99), "/knos reject")]
    assert paid(pull(), issue(), [], no, [], permission=who.permission_of("o/r", unknown_there), strict=True)["id"] == 4242
