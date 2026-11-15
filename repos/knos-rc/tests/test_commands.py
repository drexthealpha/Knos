"""What people tell Knos in a comment: read generously, strict about money, and every `/knos` line gets an answer."""

from __future__ import annotations

import os

import pytest

from knos import commands as c
from knos import terms

ADDRESS = "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo"


def bad(body: str, kind: str = "malformed") -> str:
    got = c.parse(body)
    assert isinstance(got, c.Error) and got.kind == kind, (body, got)
    assert got.reply.startswith("Knos: ") and not got.reply.startswith("/knos")
    return got.reply


# ---- reading ---------------------------------------------------------------------------------------------------------

def test_every_command_is_read_into_its_own_type():
    assert c.parse("/knos fund 20") == c.Fund(20_000_000, None, (), 14, 7)
    assert c.parse("/knos bounty 20") == c.parse("/knos fund 20")                       # the old word still works
    assert c.parse("/knos take") == c.Take() and c.parse("/knos release") == c.Release()
    assert c.parse(f"/knos address {ADDRESS}") == c.Address(ADDRESS)
    assert c.parse("/knos mine") == c.Mine() and c.parse("/knos pay @octo-cat") == c.Pay("octo-cat")
    assert c.parse("/knos reject") == c.Reject("") and c.parse("/knos reject not the fix we want") == c.Reject("not the fix we want")
    assert c.parse("/knos tip 2.5") == c.Tip(2_500_000)
    assert c.parse("/knos appeal the test I added passes") == c.Appeal("the test I added passes")
    assert isinstance(c.parse("/knos appeal"), c.Error) and "say why after it" in c.parse("/knos appeal").reply     # an appeal says why
    assert c.parse("/knos settle") == c.Settle() and c.parse("/knos status") == c.Status() and c.parse("/knos help") == c.Help()
    assert c.parse("/knos reserve 500 for @acme until 2026-12-31") == c.Reserve(500_000_000, "acme", "2026-12-31")
    assert [k.name for k in (c.Fund, c.Offer, c.Reserve, c.Raise, c.Cancel, c.Take, c.Release, c.Address, c.Mine, c.Pay, c.Split, c.Reject, c.Appeal, c.Tip, c.Settle, c.Faucet, c.Status, c.Help)] == list(c.FORMS)
    # a request for test USDC is read here and judged nowhere here: knos.faucet takes the word as typed
    assert c.parse(f"/knos faucet {ADDRESS}") == c.Faucet(ADDRESS) and c.parse("/knos FAUCET passkey") == c.Faucet("passkey")
    assert c.parse("/knos faucet") == c.Faucet("") and c.parse("/knos faucet not-an-address and more") == c.Faucet("not-an-address")
    assert c.parse(f"/knos faucet {ADDRESS}", on_pull=False) == c.Faucet(ADDRESS) and c.parse(f"/knos faucet {ADDRESS}", on_pull=True).kind == "misplaced"
    assert c.parse("/knos") == c.Help() == c.parse("/knos help me please")              # a bare /knos asks what there is


def test_the_command_is_the_first_line_that_starts_with_knos():
    assert c.parse("Thanks for the fix!\n\n/knos tip 5\n\nmore words") == c.Tip(5_000_000)
    assert c.parse("\n\n   /knos take   \n") == c.Take()                               # up to three spaces is still prose
    assert c.parse("/knos take\n/knos release") == c.Take()                             # the first one
    assert c.parse("/KNOS Fund 20") == c.parse("/Knos\tFUND\t20") == c.parse("/knos\u00a0fund\u00a020") == c.Fund(20_000_000)
    assert c.parse("/knos reject  wrong   approach ") == c.Reject("wrong   approach")
    for nothing in ("", None, "no command here", "see /knos fund 20", "please /knos take", "/knosx", "/knos-memory", "/knos:take",
                    "> /knos pay @mallory",                                             # a quote shows what someone else typed
                    "```\n/knos fund 20\n```", "~~~\n/knos fund 20\n~~~", "```\n/knos fund 20",   # so does code, closed or not
                    "    /knos fund 20", "\t/knos fund 20", "- /knos take", "`/knos take`",
                    "<!--\n/knos fund 20\n-->", "<!-- a template's example:\n/knos fund 20", "<!-- /knos take -->"):   # nobody sees it
        assert c.parse(nothing) is None, nothing
    assert c.parse("<!-- hidden -->\n/knos take") == c.Take() == c.parse("<!-- a --> <!-- b -->\n/knos take <!-- c -->")
    assert c.parse("```\ncode\n```\n/knos take") == c.Take()                            # after the fence closes it counts again
    assert bad("/knos " + "x" * 2000) and "too long" in bad("/knos fund " + "1" * 1200)
    assert c.parse("\n".join(["line"] * 1999 + ["/knos take"])) == c.Take() and c.parse("\n".join(["line"] * 2001 + ["/knos take"])) is None


def test_fund_takes_its_options_in_any_order_and_any_spacing():
    full = c.parse("/knos fund 12.5 checks: test, build (ubuntu-latest, 3.12), lint paths: src/**, docs/*.md days 30 reserve 3")
    assert full == c.Fund(12_500_000, ("test", "build (ubuntu-latest, 3.12)", "lint"), ("src/**", "docs/*.md"), 30, 3)
    assert c.parse("/knos fund 12.5 reserve 3 days 30 paths: src/**, docs/*.md checks: test, build (ubuntu-latest, 3.12), lint") == full
    assert c.parse("/knos fund 12.5 CHECKS :test,build (ubuntu-latest, 3.12) ,lint,  Paths:src/**,docs/*.md Days: 30 RESERVE:3") == full
    # a comma inside brackets belongs to the name; quotes and backticks take a name whole
    assert c.parse('/knos fund 20 checks: "a, b", `days 3`, c [x, y] {p, q}, d').checks == ("a, b", "days 3", "c [x, y] {p, q}", "d")
    assert c.parse("/knos fund 20 checks: test, test, build,").checks == ("test", "build")              # said twice is said once
    assert c.parse("/knos fund 20 checks: prove / check, CI / test (3.12)").checks == ("prove / check", "CI / test (3.12)")
    assert c.parse("/knos fund 20 checks: code review, dependency-review").checks == ("code review", "dependency-review")
    assert c.parse("/knos fund 20 checks: none") == c.Fund(20_000_000, ()) and c.parse("/knos fund 20 checks: None").checks == ()
    assert c.parse("/knos fund 20 checks: none, test").checks == ("none", "test")
    assert c.parse("/knos fund 20 paths: ./src/**, /docs/, src/**").paths == ("src/**", "docs/")       # from the repository's root
    assert c.parse("/knos fund 20 days 1 reserve 0") == c.Fund(20_000_000, None, (), 1, 0)
    assert c.parse("/knos fund 20 days 90 reserve 90") == c.Fund(20_000_000, None, (), 90, 90)
    assert c.parse("/knos fund 20 checks: a) b") == c.Fund(20_000_000, ("a) b",))                        # a stray bracket is a letter


def test_a_fund_command_that_is_not_understood_says_why_and_shows_the_form():
    form = "Type it like this: `/knos fund <amount> [checks: a, b] [paths: glob, ...] [days N] [reserve N]`, for example `/knos fund 20`."
    for body, why in (("/knos fund", "the amount is missing"), ("/knos fund checks: test", "the amount is digits"),
                      ("/knos fund 20 usdc", "`usdc` is not something this command takes"),
                      ("/knos fund 20 <script>", "`script` is not something this command takes"),
                      ("/knos fund 20 review 0", "there is no `review` any more"),
                      ("/knos fund 20 days", "`days` needs a whole number after it"), ("/knos fund 20 reserve: soon", "`reserve` needs a whole number"),
                      ("/knos fund 20 days 0", "`days` must be from 1 to 90"), ("/knos fund 20 days 91", "`days` must be from 1 to 90"),
                      ("/knos fund 20 reserve 91", "`reserve` must be from 0 to 90"), ("/knos fund 20 days 3 days 4", "`days` is written twice"),
                      ("/knos fund 20 checks: a checks: b", "`checks` is written twice"), ("/knos fund 20 days 3.5", "`days` needs a whole number"),
                      ("/knos fund 20 checks:", "`checks:` needs at least one name after it, or `checks: none`"),
                      ("/knos fund 20 checks: , ,", "`checks:` needs at least one name"), ("/knos fund 20 paths:", "`paths:` needs at least one name after it."),
                      ("/knos fund 20 checks: test (ubuntu", "quote or bracket is not closed"), ('/knos fund 20 checks: "test', "quote or bracket is not closed"),
                      ("/knos fund 20 checks: " + "x" * 201, "at most 200 characters"),
                      ("/knos fund 20 paths: ../secrets", "a path is a glob from the repository's root"), ("/knos fund 20 paths: !src", "a path is a glob"),
                      ("/knos fund 20 paths: a\\b", "a path is a glob"), ("/knos fund 20 paths: /", "a path is a glob")):
        said = bad(body)
        assert why in said and said.endswith(form), (body, said)
        assert c.parse(body).command == "fund"


def test_amounts_are_plain_decimals_within_what_the_escrow_takes():
    for text, units in (("1", 1_000_000), ("20", 20_000_000), ("12.5", 12_500_000), ("0001.000001", 1_000_001), ("500", 500_000_000),
                        ("500.000000", 500_000_000), ("1.10", 1_100_000), ("3.141592", 3_141_592)):
        assert c.parse(f"/knos fund {text}").units == units == c.parse(f"/knos tip {text}").units, text
    assert [c.amount(u) for u in (1_000_000, 12_500_000, 1_000_001, 500_000_000, 3)] == ["1", "12.5", "1.000001", "500", "0.000003"]
    for text in ("-5", "+5", "1e3", "1E3", "0x10", "1,000", "20.", ".5", "1.0000001", "$20", "20usdc", "twenty", "١٢", "1_000", "NaN", "inf",
                 "9" * 10, "1 000", "²"):
        assert "the amount is digits with at most 6 decimals" in bad(f"/knos tip {text}"), text
    assert "`000` is not something this command takes" in bad("/knos fund 1 000")
    assert "`reserve` needs a whole number" in bad("/knos fund 20 reserve ٣")              # digits are 0 to 9
    for text in ("0", "0.999999", "100000.000001", "100001", "999999999"):
        assert "the amount must be from 1 to 100000" in bad(f"/knos fund {text}"), text
        assert "the amount must be from 1 to 100000" in bad(f"/knos tip {text}")
    assert "the amount is missing" in bad("/knos tip") and bad("/knos tip").endswith("Type it like this: `/knos tip <amount>`.")
    assert (c.MIN_UNITS, c.MAX_UNITS) == (1_000_000, 100_000_000_000)                        # knos-pay's MIN_AMOUNT and MAX_AMOUNT


def test_an_address_is_32_bytes_in_canonical_base58():
    from solders.pubkey import Pubkey
    for raw in (bytes(range(32)), bytes(31) + b"\x01", b"\x00" * 3 + bytes(range(3, 32)), b"\xff" * 32, *(os.urandom(32) for _ in range(300))):
        assert c.address_ok(str(Pubkey.from_bytes(raw))), raw.hex()
    assert c.parse(f"/knos address {ADDRESS}").address == ADDRESS
    for text in ("", "abc", "2" * 31, "2" * 32, ADDRESS + "1", "1" + ADDRESS, ADDRESS.replace("4", "0", 1), ADDRESS.replace("G", "O"),
                 ADDRESS.replace("c", "l", 1), ADDRESS.replace("z", "I", 1), "z" * 44, ADDRESS + " " + ADDRESS,
                 "1" * 32, "1" * 44,                                                    # all zeros: nobody's wallet
                 f"<{ADDRESS}>", "0x" + "ab" * 20, ADDRESS.lower(), "é" * 40):
        assert not c.address_ok(text), text
        assert "that is not a Solana address" in bad(f"/knos address {text}"), text

    def solana_reads(text: str) -> bool:
        try:
            Pubkey.from_string(text)
        except ValueError:
            return False
        return True
    import random
    rng = random.Random(7)                  # strings of the right length are an address or not by their value alone
    tried = [ADDRESS[:-1], ADDRESS[:-2], "2" * 43, "2" * 44, "y" * 43, "5" * 44, "1" * 10 + "2" * 30,
             *("".join(rng.choice(c._B58) for _ in range(rng.choice((43, 44)))) for _ in range(400))]
    assert all(c.address_ok(text) == solana_reads(text) for text in tried)          # the same answer as Solana's own reader
    assert 20 < sum(map(c.address_ok, tried)) < len(tried) - 20                     # and both answers were seen
    assert not c.address_ok(None) and not c.address_ok(ADDRESS.encode())
    assert bad("/knos address").endswith("Type it like this: `/knos address <your Solana address>`.")


def test_the_other_commands_are_exact():
    for body in ("/knos take this", "/knos release it", "/knos mine too", "/knos settle now", "/knos status ?"):
        said = bad(body)
        name = body.split()[1]
        assert "nothing goes after it" in said and said.endswith(f"Type it like this: `/knos {name}`."), said
    for body in ("/knos pay", "/knos pay @", "/knos pay @a b", "/knos pay @-a", "/knos pay @a--b", "/knos pay @a_b", "/knos pay @" + "a" * 40,
                 "/knos pay @some[bot]", "/knos pay https://github.com/octocat"):
        assert "name one GitHub account" in bad(body) and bad(body).endswith("Type it like this: `/knos pay @login`.")
    assert c.parse("/knos pay octocat") == c.Pay("octocat") == c.parse("/knos Pay @octocat") and c.parse("/knos pay @" + "a" * 39).login == "a" * 39
    assert c.parse("/knos reject " + "x" * 500).reason == "x" * 200                    # a reason is one short line
    unknown = bad("/knos frobnicate `x` <!-- @all -->", "unknown")
    assert unknown.startswith("Knos: `frobnicate` is not a command. These are:\n- `/knos fund <amount>")
    assert all(f"`{form}`" in unknown for form in c.FORMS.values()) and unknown.count("\n") == len(c.FORMS)
    assert bad("/knos <<<>>>", "unknown").startswith("Knos: that is not a command.")    # nothing of it is safe to say back
    assert bad("/knos mine!", "unknown").startswith("Knos: `mine!` is not a command.")
    assert bad("/knos @everyone", "unknown").startswith("Knos: `everyone` is not a command.") and "@" not in bad("/knos @everyone", "unknown").split("These")[0]
    assert bad("/knos Fünd 20", "unknown").startswith("Knos: `Fnd` is not a command.")


# ---- answering -------------------------------------------------------------------------------------------------------

BOUGHT = {"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge",
          "paths": [], "reserve": 7, "v": 1}


def test_understood_says_what_was_understood_and_what_happens_next():
    said = c.reply("understood", c.parse("/knos fund 12.5 days 30"), issue=7, terms=BOUGHT, source="funder")
    assert said == ("Knos: 12.5 test USDC for issue #7. It is paid when a maintainer merges a pull request that closes this issue, if "
                    "these checks passed at that pull request's last commit: `test` (the checks you named). The pull request may not "
                    "change `.github/**` or `.knos/**`. `/knos take` reserves the issue for 7 days. If it is not paid within 30 days, "
                    "the money goes back to where it came from. Next: the bounty is opened on Solana, and Knos confirms here.")
    assert c.reply("understood", c.Fund(20_000_000), money="USDC").startswith("Knos: 20 USDC. If it is not paid within 14 days")
    guess = terms.build(c.parse("/knos fund 20 checks: lint"), [], [], [])                # what was assumed is said too
    said = c.reply("understood", c.Fund(20_000_000, ("lint",)), issue=7, terms=guess.terms, source=guess.source, notes=guess.notes)
    assert "`lint` (any source) (the checks you named)." in said and "from any source will count. If it is not paid within" in said
    built = terms.build(c.parse("/knos fund 20 checks: none"))
    assert "You asked for no checks; your merge alone is the acceptance." in c.reply("understood", c.Fund(20_000_000, ()), issue=7,
                                                                                    terms=built.terms, source=built.source)
    assert c.reply("understood", c.Tip(5_000_000), login="mona") == \
        "Knos: a tip of 5 test USDC to @mona for this merged pull request. Next: it is paid on Solana, and Knos confirms here."
    assert "a tip of 5 test USDC for this merged" in c.reply("understood", c.Tip(5_000_000))
    address = c.reply("understood", c.Address(ADDRESS), login="mona")
    assert address.startswith(f"Knos: noted. @mona's payment for this pull request goes to {ADDRESS}, unless a wallet is bound")
    assert "Do not edit that comment: an edited comment does not count." in address and "post a new one" in address
    assert c.reply("understood", c.Address(ADDRESS)).startswith("Knos: noted. The payment for this pull request goes to")
    paid = {"id": 4242, "login": "mona", "why": "maintainer @hubot named them with `/knos pay`"}
    for command in (c.Mine(), c.Pay("mona")):
        assert c.reply("understood", command, paid=paid) == "Knos: noted. This pull request pays @mona: maintainer @hubot named them with `/knos pay`."
    nobody = {"id": None, "why": "x[bot] is a bot account", "fix": "A maintainer comments `/knos pay @login` on this pull request."}
    assert c.reply("understood", c.Mine(), paid=nobody) == \
        "Knos: nobody is paid for this pull request yet: x[bot] is a bot account. A maintainer comments `/knos pay @login` on this pull request."
    assert c.reply("understood", c.Pay("x")) == "Knos: nobody is paid for this pull request yet: nothing names a person."
    assert c.reply("understood", c.Reject("not `the` fix <!-- x -->"), login="hubot") == \
        ("Knos: noted. This pull request does not take the bounty (rejected by @hubot: not the fix !-- x --). It can still be merged. "
         "To undo, delete that comment.")
    assert c.reply("understood", c.Reject()) == ("Knos: noted. This pull request does not take the bounty (rejected). It can still "
                                                 "be merged. To undo, delete that comment.")
    assert c.reply("understood", c.Settle()) == "Knos: trying this pull request's payment again. The result follows here."
    assert c.reply("understood", c.Help()) == "Knos acts on the first line of a comment that starts with `/knos`:\n" + "\n".join(
        f"- `{form}`: {c._ABOUT[name]}" for name, form in c.FORMS.items())
    assert c.reply("understood", c.Status(), text="20 test USDC is in escrow for issue #7.") == "Knos: 20 test USDC is in escrow for issue #7."
    assert c.reply("understood", c.Take()) == "Knos: understood `/knos take`."            # knos.who.take writes the real one


def test_someone_who_may_not_is_told_who_may_and_what_they_can_do_instead():
    assert c.reply("not_allowed", c.Fund(1_000_000)) == c.reply("not_allowed", "fund") == c.reply("not_allowed", c.Fund) == \
        ("Knos: `/knos fund` is for the repository's owner and the people they let spend its balance. You can ask them to fund it: "
         "they comment `/knos fund 20` on the issue.")
    for name in ("fund", "tip", "pay", "reject", "mine", "address", "release", "take"):
        said = c.reply("not_allowed", name)
        assert said.startswith(f"Knos: `/knos {name}` is for ") and said.count(". ") >= 1 and len(said) < 260, said
    assert "comment `/knos mine`" in c.reply("not_allowed", "pay") and "`/knos pay @you`" in c.reply("not_allowed", "mine")
    assert c.reply("not_allowed", "address", who="@mona, whom this pull request pays", instead="Nothing changed.") == \
        "Knos: `/knos address` is for @mona, whom this pull request pays. Nothing changed."
    assert c.reply("not_allowed", "settle") == "Knos: `/knos settle` is for someone else."    # anyone may: never said in practice


def test_a_command_in_the_wrong_place_is_told_where_it_belongs():
    for body in ("/knos fund 20", "/knos bounty 20", "/knos take", "/knos release"):
        name = "fund" if "20" in body else body.split()[1]
        assert c.parse(body, on_pull=False) == c.parse(body)
        got = c.parse(body, on_pull=True)
        assert got == c.Error("misplaced", f"Knos: `/knos {name}` belongs on the issue, not on a pull request. Comment it there.", name)
    for body in (f"/knos address {ADDRESS}", "/knos mine", "/knos pay @x", "/knos reject", "/knos tip 5", "/knos settle"):
        name = body.split()[1]
        assert c.parse(body, on_pull=True) == c.parse(body)
        got = c.parse(body, on_pull=False)
        assert got == c.Error("misplaced", f"Knos: `/knos {name}` belongs on the pull request, not on an issue. Comment it there.", name)
    for body in ("/knos status", "/knos help", "/knos"):                                # these go anywhere
        assert c.parse(body, on_pull=True) == c.parse(body, on_pull=False) == c.parse(body)
    assert c.parse("/knos frob", on_pull=True).kind == "unknown" and c.parse("/knos take it", on_pull=True).kind == "malformed"
    assert c.parse("no command", on_pull=True) is None


def test_every_outcome_has_a_reply_and_no_reply_is_a_command():
    replies = [c.reply("unknown", word="x"), c.reply("unknown"), c.reply("malformed"), c.reply("malformed", "nope", why="odd"),
               *(c.reply("malformed", name, why="it is wrong") for name in c.FORMS),
               *(c.reply("not_allowed", name) for name in c.FORMS), *(c.reply("misplaced", name) for name in c.FORMS)]
    for said in replies:
        assert said.startswith("Knos") and c.parse(said) is None and "\n\n" not in said, said
    assert c.reply("malformed") == "Knos: that was not understood. `/knos help` lists the commands."
    assert c.reply("malformed", "take", why="nothing goes after it") == "Knos: that was not understood: nothing goes after it. Type it like this: `/knos take`."
    with pytest.raises(ValueError):
        c.reply("shrug", "take")


def test_a_work_orders_words_are_read_as_strictly_as_the_rest():
    f = c.parse("/knos fund 20 checks: test warranty 14 holdback 20 arbiter @erin neutral off")
    assert f == c.Fund(20_000_000, ("test",), warranty=14, holdback=20, arbiter="erin", neutral=False)
    assert c.parse("/knos fund 20") == c.Fund(20_000_000) and c.Fund(20_000_000).neutral is None        # unsaid: the policy, then the default
    assert c.parse("/knos fund 20 checks: test (a, b), lint days 30 neutral on").checks == ("test (a, b)", "lint")
    o = c.parse("/knos offer @acme-agents rate 12 budget 600 checks: test")
    assert o == c.Offer("acme-agents", 12_000_000, 600_000_000, ("test",))
    assert c.parse("/knos offer @acme rate 12 budget 100 checks: test days 30") == c.Offer("acme", 12_000_000, 100_000_000, ("test",), (), 30)
    assert c.parse("/knos raise 10") == c.Raise(10_000_000) and c.parse("/knos cancel") == c.Cancel()
    assert c.parse("/knos split @ana 60 @ben 40") == c.Split((("ana", 60), ("ben", 40))) == c.parse("/knos split ana 60%, ben 40%")
    for line, why in (("/knos fund 20 warranty 91", "`warranty` must be from 0 to 90"), ("/knos fund 20 holdback 51", "`holdback` must be from 0 to 50"),
                      ("/knos fund 20 arbiter", "`arbiter` needs a GitHub login"), ("/knos fund 20 neutral maybe", "`neutral` is `neutral off`"),
                      ("/knos fund 20 rate 3", "`rate` is not something this command takes"), ("/knos offer rate 12 budget 100", "name the vendor"),
                      ("/knos offer @acme rate 12", "`budget 100`"), ("/knos offer @acme rate 50 budget 20", "the budget is under the rate"),
                      ("/knos split @ana 60 @ben 30", "add up to 90"), ("/knos split @ana 100 extra", "name each person"),
                      ("/knos split @a 20 @b 20 @c 20 @d 20 @e 20", "one to four people"), ("/knos raise", "the amount is missing"),
                      ("/knos cancel now", "nothing goes after it")):
        got = c.parse(line)
        assert isinstance(got, c.Error) and why in got.reply and got.reply.startswith("Knos: that was not understood"), (line, got)
    assert c.parse("/knos split @ana 100", on_pull=False).kind == "misplaced" and c.parse("/knos cancel", on_pull=True).kind == "misplaced"
