"""Which issue a pull request closes: GitHub's own answer first, its documented keywords when that cannot be had, and
a word to the author who mentions a funded issue without closing it."""

from __future__ import annotations

import time

from knos import closing

REPO = "octo/widgets"


def test_githubs_documented_keywords_close_an_issue():
    for word in ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"):
        for form in (word, word.upper(), word.capitalize()):
            assert closing.closing_issues(f"{form} #10", REPO) == [10], form
            assert closing.closing_issues(f"{form}: #10", REPO) == [10], form
            assert closing.closing_issues(f"This pull request {form} octo/widgets#10.", REPO) == [10], form
    said = "Resolves #10, resolves #123, resolves octo-org/octo-repo#100"                 # GitHub's own example
    assert closing.closing_issues(said, REPO) == [10, 123] and closing.closing_issues(said, "octo-org/octo-repo") == [10, 123, 100]
    assert closing.closing_issues("Fixes #10, #11 and #12", REPO) == [10]                 # a keyword before every one
    assert closing.closing_issues("Fixes #3. Closes #1.\n\n(fixes #3)\nFIXES:\t #7", REPO) == [3, 1, 7]   # as named, each once
    assert closing.closing_issues("Fixes Octo/Widgets#5", REPO) == [5] == closing.closing_issues("fixes   #5.", "Octo/Widgets")


def test_what_is_not_a_closing_keyword_closes_nothing():
    for said in ("", None, "See #3", "prefixes #3", "hotfix #3", "auto-fix #3", "fixing #3", "closest #3", "unresolved #3", "fix-#3", "fixes#3",
                 "fixes # 3", "fixes #3abc", "Fixes issue #3", "fixes\n#3", "Fixes #0", "Fixes #12345678901", "fixes :#3", "Fixes: : #3",
                 "Fixes other/repo#3",                                                     # another repository's issue is not this one's
                 "Fixes https://github.com/octo/widgets/issues/3",                         # not a form GitHub documents
                 "`Fixes #3`", "Use `git commit -m 'fixes #3'` to", "```\nFixes #3\n```", "~~~\nFixes #3\n~~~", "```\nFixes #3",   # code
                 "<!-- Fixes #3 -->", "<!-- e.g.\nFixes #3\n-->", "<!-- left open\nFixes #3"):                                    # a comment
        assert closing.closing_issues(said, REPO) == [], said
    assert closing.closing_issues("<!-- template --> Fixes #3 <!-- more -->", REPO) == [3]
    assert closing.closing_issues("```py\nx = 1\n```\nFixes #3", REPO) == [3]
    t = time.monotonic()
    closing.closing_issues("<!--" * 50_000 + "fixes " * 20_000 + "`" * 50_000, REPO)
    assert time.monotonic() - t < 1                                                        # no input makes it slow


def test_githubs_own_answer_is_read_and_anything_less_than_a_whole_answer_is_none():
    def answer(nodes, total=None, **more) -> dict:
        return {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"totalCount": len(nodes) if total is None else total,
                                                                                    "nodes": nodes}}}}, **more}
    here, there = {"nameWithOwner": "Octo/Widgets"}, {"nameWithOwner": "other/repo"}
    nodes = [{"number": 30, "repository": here}, {"number": 5, "repository": there}, {"number": 31}, {"number": 30, "repository": here}]
    assert closing.closing_from_graphql(answer(nodes), REPO) == [30, 31]                  # this repository's, each once
    assert closing.closing_from_graphql(answer(nodes)) == [30, 5, 31]                     # no repository named: every one
    assert closing.closing_from_graphql(answer([]), REPO) == [] == closing.closing_from_graphql(answer([]))   # it closes nothing
    assert closing.closing_from_graphql({"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": nodes[:1]}}}}}, REPO) == [30]
    for broken in (None, {}, [], "x", {"data": None}, {"data": {"repository": None}}, {"data": {"repository": {"pullRequest": None}}},
                   answer(nodes, errors=[{"message": "rate limited"}]), answer(nodes[:1], total=101),       # cut short
                   answer([None]), answer([{"repository": here}]), answer([{"number": "x", "repository": here}]), answer("nodes")):
        assert closing.closing_from_graphql(broken, REPO) is None, broken
    assert "closingIssuesReferences(first:100)" in closing.QUERY and "$number:Int!" in closing.QUERY
    assert closing.variables("octo/widgets", "12") == {"owner": "octo", "name": "widgets", "number": 12}
    # asked through the one door to GitHub: a post to /graphql
    asked = []

    def post(path, payload):
        asked.append((path, payload))
        return answer(nodes)
    assert closing.read(REPO, 12, post) == [30, 31]
    assert asked == [("graphql", {"query": closing.QUERY, "variables": {"owner": "octo", "name": "widgets", "number": 12}})]

    def down(path, payload):
        raise OSError("502")
    assert closing.read(REPO, 12, down) is None and closing.read(REPO, 12, lambda path, payload: {"errors": [{"message": "no"}]}) is None


def test_what_one_pull_request_closes_is_githubs_list_and_its_own_keywords():
    def pull(body, ref="main"):
        return {"body": body, "base": {"ref": ref, "repo": {"full_name": "octo/widgets", "default_branch": "main"}}}
    assert closing.closed_by(pull("Fixes #7, fixes octo/widgets#8, fixes other/repo#9")) == [7, 8]
    assert closing.closed_by(pull("Fixes #7"), [30, 7]) == [30, 7]                       # GitHub's list first, each once
    assert closing.closed_by(pull("no keyword"), [30]) == [30] and closing.closed_by(pull("no keyword"), None) == []
    assert closing.closed_by(pull("Fixes #7", "release/1.x")) == []                       # a keyword counts against the default branch only
    assert closing.closed_by(pull("Fixes #7", "release/1.x"), [7]) == [7]                 # GitHub's own link holds anywhere
    assert closing.closed_by({"body": "Fixes #7"}) == [7] == closing.closed_by({"body": "Fixes #7", "base": {"ref": "dev"}})   # the default is not known
    assert closing.closed_by({}) == [] == closing.closed_by({"body": None, "base": None})
    # who is paid at the merge asks exactly this
    from knos import who
    mona = {"login": "mona", "id": 4242, "type": "User"}
    for p, listed in ((pull("Fixes #7"), None), (pull("Fixes #7", "release/1.x"), None), (pull("x"), [8]), (pull("Fixes #7", "dev"), [7])):
        for n in (7, 8):
            got = who.payee({**p, "user": mona}, {"number": n, "assignees": []}, [], [], [], strict=True, closes=listed)
            assert (got["id"] == 4242) == (n in closing.closed_by(p, listed)), (p, listed, n)


def test_a_funded_issue_that_is_mentioned_but_not_closed_is_pointed_out():
    body = ("Related to #30 and octo/widgets#31; see https://github.com/Octo/Widgets/issues/32 and other/repo#33 and "
            "https://github.com/other/repo/issues/36. Fixes #34. Not `#35`. Also x#37, &#38; and PR https://github.com/octo/widgets/pull/39.")
    funded = [30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40]
    assert closing.mentions_without_closing(body, funded, REPO) == [30, 31, 32, 39]
    assert closing.mentions_without_closing(body, funded) == [30]                         # without the repository: only a bare #N
    assert closing.mentions_without_closing(body, [34, 40], REPO) == []                   # closed, or not mentioned
    assert closing.mentions_without_closing("Fixes #30, and #30 again", [30], REPO) == []
    assert closing.mentions_without_closing("#30 first thing", ["30"], REPO) == [30]
    for nothing in ((body, []), (body, None), ("", funded), (None, funded), ("<!-- #30 -->", funded), ("```\n#30\n```", funded)):
        assert closing.mentions_without_closing(*nothing, REPO) == []
    assert closing.mention_note([]) == "" == closing.mention_note(None)
    assert closing.mention_note([30]) == ("This mentions funded issue #30 but does not close it. If this pull request is for that "
                                          "bounty, write `Fixes #30` in its description.")
    assert closing.mention_note([30, 31]) == ("This mentions funded issues #30, #31 but does not close them. If this pull request is "
                                              "for those bounties, write `Fixes #30` in its description.")
    assert closing.closing_issues("Fixes #30", REPO) == [30]                              # and what it says to write does close it


def test_a_description_edited_at_or_after_the_merge_is_told_from_one_edited_before_it():
    def answer(merged, edited, **more) -> dict:
        return {"data": {"repository": {"pullRequest": {"mergedAt": merged, "lastEditedAt": edited,
                                                        "closingIssuesReferences": {"totalCount": 0, "nodes": []}}}}, **more}
    at = "2026-10-02T12:00:00Z"
    assert closing.edited_late(answer(at, "2026-10-02T12:00:01Z")) == 1790942401.0         # after the merge: when
    assert closing.edited_late(answer(at, at)) == 1790942400.0                             # the same second is not known to be before
    assert closing.edited_late(answer(at, "2026-10-02T11:59:59Z")) is False                # what was merged
    assert closing.edited_late(answer(at, None)) is False and closing.edited_late(answer(None, at)) is False   # never edited; not merged
    for broken in (None, {}, "x", {"data": None}, {"data": {"repository": {"pullRequest": {"mergedAt": at}}}}, answer(at, "soon"),
                   answer("then", at), answer(at, at, errors=[{"message": "rate limited"}])):
        assert closing.edited_late(broken) is None, broken
    assert "mergedAt" in closing.QUERY and "lastEditedAt" in closing.QUERY
    # one question gives both; no answer gives neither
    assert closing.facts(REPO, 12, lambda path, payload: answer(at, "2026-10-03T08:00:00Z")) == ([], 1791014400.0)

    def down(path, payload):
        raise OSError("502")
    assert closing.facts(REPO, 12, down) == (None, None)
