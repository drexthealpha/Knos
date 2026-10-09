"""The four commands a repository's workflow runs (knos.flow), each outcome acted out against a GitHub, a chain and a
relay of the tests' own (tests/_flow.py). What is asserted is what people read: the comment, or the job's summary."""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import types

import pytest

from _flow import (ADDRESS, DEVIN, EVE, HUBOT, MONA, REPO, REPO_ID, T0, WALLET, WF_REPO, World, check, claims, key, sha, stamp)
from _hub import BOT
from knos import commands, flow, judge, terms
from knos.cli import main
from knos.proof import memory
from knos.settle.v2 import pay

FAUCET = pay.faucet_balance_pda(HUBOT["id"])
JOB = pay.job_pda(REPO_ID, 7, FAUCET)                        # issue #7's job, funded from the owner's faucet Balance
BOUGHT = {"accept": "", "checks": [{"app": 15368, "name": "build"}, {"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"],
          "mode": "merge", "paths": [], "reserve": 7, "v": 1}
MONEY = "test USDC"                                          # what devnet's money is called, every time
EXPLORER = "https://explorer.solana.com"

FUNDED = f"""Knos: 20.00 {MONEY} from the devnet faucet is in escrow for issue #7 ([job on Solana]({EXPLORER}/address/{JOB}?cluster=devnet)), 38 s after the comment.

It is paid when a maintainer merges a pull request that closes this issue, if these checks passed at that pull request's last commit: `test` (this branch's required checks). The pull request may not change `.github/**` or `.knos/**`. If it is not paid by 2026-10-05 14:13 UTC, the money goes back to where it came from.

To earn it: open a pull request whose description says `Fixes #7`. `/knos take` reserves the issue for 7 days. For the money to reach you when it is paid, comment `/knos address <your Solana address>` on your pull request; without an address it waits for you until you bind a wallet (180 days at most)."""

# an acceptance check that never loads the pull request's code: it asks that code through $KNOS_RUN and compares the answer
BLACKBOX = b'out=$("$KNOS_RUN" python3 -c "import slug; print(slug.slug(\'a b\'))")\n[ "$out" = "a-b" ]\n'

PAID = (f"Knos: paid. @mona received 19.50 {MONEY} for issue #7: the bounty of 20.00 less Knos's fee of 0.50. It went to `{WALLET}`, the "
        f"wallet bound to @mona's GitHub account ([transaction]({EXPLORER}/tx/sig2?cluster=devnet), 34 s after the merge).")

HELD = (f"Knos: held for @mona. 20.00 {MONEY} for issue #7 waits for them until 2027-03-20 15:13 UTC, because no wallet is "
        "known for them: none is bound to their GitHub account and no `/knos address` comment counted. To receive it, @mona binds a "
        "wallet: https://drexthealpha.github.io/Knos/#payee=mona in the browser, or `knos claim <their Solana address>` in a terminal. It "
        "is then paid, less Knos's fee of 0.50; after that date it goes back to where it came from "
        f"([transaction]({EXPLORER}/tx/sig2?cluster=devnet), 34 s after the merge).")

REFUSED = f"""Knos: not paid. This pull request does not take the bounty on issue #7 (20.00 {MONEY}) as it stands; its checks are read at its last commit (`{sha('head-12')[:7]}`).
- `build`: passed
- `test`: failed
If a check that did not pass is run again on that commit and passes, comment `/knos settle`. A maintainer can pay this work anyway with `/knos tip <amount>`. The money stays in escrow until 2026-10-05 14:13 UTC, then goes back to where it came from."""


def world(tmp_path, **kw) -> World:
    """o/r with issue #7 open, hubot its owner."""
    w = World(tmp_path, **kw)
    w.hub.issue(7, "Slugify keeps punctuation.")
    return w


def bounty(tmp_path, bought: dict = BOUGHT, units: int = 20_000_000, author: dict = MONA, body: str = "Fixes #7", **kw) -> World:
    """Issue #7 funded an hour ago, and pull request #12 open for it with the bounty's checks passed at its head."""
    w = world(tmp_path, **kw)
    w.chain.fund(7, units, bought)
    w.clock.sleep(3600)
    head = w.hub.pull(12, author, body)["head"]["sha"]
    w.hub.checks[head] = [check("test"), check("build")]
    return w


def plain(text: str, most: int = 1100) -> str:
    """What every comment must be: Knos speaking, nothing left unfilled, no line that reads as a command, short."""
    text, _, line = text.partition("\n\n[![paid on proof: #")     # a payment's badge line (knos.badge, tests/test_badge.py) is read apart
    assert not line or (re.search(r"\b[Pp]aid\. ", text) and line.endswith(".html)") and "\n" not in line), line
    assert text.startswith(("Knos", flow.MARK)) and len(text) <= most, (len(text), text)
    assert not any(bad in text for bad in ("None", "{", "}", "  ", "Traceback", " ,")), text
    assert commands.parse(text) is None
    return text


def only(w: World, n: int) -> str:
    """The one thing Knos said on `n`."""
    said = w.hub.knos(n)
    assert len(said) == 1, said
    return plain(said[0])


# ---- knos command: funding -------------------------------------------------------------------------------------------

def test_an_ordinary_comment_gets_no_reply_and_an_edit_is_not_a_new_command(tmp_path):
    w = world(tmp_path)
    for body in ("Thanks, this looks right.", "you could type `/knos fund 20` here", "```\n/knos fund 20\n```", "> /knos fund 20", ""):
        assert flow.command(w.run(w.hub.commented(7, HUBOT, body))) == 0
    again = w.hub.commented(7, HUBOT, "/knos fund 20")
    for action in ("edited", "deleted"):                                                   # said once, when it was written
        assert flow.command(w.run({**again, "action": action})) == 0
    assert flow.command(w.run({"action": "edited", "issue": {**w.hub.issues[7], "body": "/knos fund 20"}})) == 0
    assert flow.command(w.run({})) == 0 == flow.command(w.run({"action": "created", "comment": {"body": "/knos help"}}))
    assert w.hub.knos(7) == [] and w.hub.wrote == [] and w.signer.asked == [] and w.chain.jobs() == []


def test_the_owner_funds_an_issue_with_one_comment_and_test_money(tmp_path, capsys):
    w = world(tmp_path)
    w.hub.required = [{"context": "test", "integration_id": 15368}]
    run = w.run(w.hub.commented(7, HUBOT, "/knos fund 20", at=T0 - 8), GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"))
    assert flow.command(run) == 0
    assert only(w, 7) == FUNDED
    # what GitHub was asked to sign names the Balance, and the chain holds the job with its terms for everyone to read
    raw = w.chain.logs[str(JOB)]
    assert w.signer.asked == [pay.fund_audience(7, 20_000_000, pay.MERGE, pay.terms_hash(raw), FAUCET, 14 * 86_400)]
    assert terms.parse(raw) == {**BOUGHT, "checks": [{"app": 15368, "name": "test"}]}
    (address, job), = w.chain.jobs(7)
    assert address == str(JOB) and (job.state, job.amount, job.faucet, job.funder_id) == ("open", 20_000_000, True, HUBOT["id"])
    assert job.wf_repo_hash == pay.wf_repo_hash(WF_REPO) and w.relay.submitted[0][1] == raw       # the relay carried the terms JSON
    # the same words are on the run's page and in the job's log
    assert FUNDED in (tmp_path / "summary.md").read_text(encoding="utf-8") and FUNDED in capsys.readouterr().out
    assert run.outputs == {} and "collaborators" not in " ".join(w.hub.asked)             # the owner can write: nobody is asked


def test_the_terms_are_what_the_repository_has_and_the_reply_says_each_in_words(tmp_path):
    def funded(body="/knos fund 20", arrange=lambda w: None) -> tuple[World, str]:
        w = world(tmp_path)
        arrange(w)
        assert flow.command(w.run(w.hub.commented(7, HUBOT, body))) == 0
        return w, only(w, 7)
    # no rule on the branch: the checks that ran on its latest commit (`/knos bounty` is the same command)
    w, said = funded("/knos bounty 20")
    assert ("if these checks passed at that pull request's last commit: `test` (the checks that ran on the default branch's "
            "latest commit).") in said
    # a repository with no CI at all: said out loud, and the merge alone is the acceptance
    w, said = funded(arrange=lambda w: w.hub.checks.update({w.hub.head: []}))
    assert "\n\nThis repository has no checks; your merge alone is the acceptance. The pull request may not change" in said
    assert terms.parse(w.chain.logs[str(JOB)])["checks"] == []
    # the funder's own words: checks, paths, days and the reservation
    w, said = funded("/knos fund 20 checks: test paths: src/**, docs/*.md days 30 reserve 0")
    assert ("last commit: `test` (the checks you named). The pull request may not change `.github/**` or `.knos/**`, and may only "
            "change files matching `docs/*.md` or `src/**`.") in said
    assert "If it is not paid by 2026-10-21 14:13 UTC, the money goes back" in said
    assert "Nobody can reserve it: the first accepted pull request is paid." in said and w.signer.asked[0].split(":")[6] == str(30 * 86_400)
    # more checks than a bounty's terms hold: nothing is funded, and the funder is told to name the ones that count
    many = [check(f"integration tests on a matrix entry with a long name, number {i}") for i in range(30)]
    w, said = funded(arrange=lambda w: w.hub.checks.update({w.hub.head: many}))
    assert said.startswith("Knos: This repository's 30 checks do not fit in a bounty's terms (600 bytes; they take ")
    assert said.endswith("Name the ones that must pass: `checks: a, b`.") and w.signer.asked == [] and w.chain.jobs() == []


def test_real_money_comes_from_the_largest_balance_that_lists_the_commenter_and_holds_enough(tmp_path):
    w = world(tmp_path)
    w.hub.can["mona"] = "write"
    w.chain.balance("small", 30_000_000, spenders=[MONA["id"]])
    big = w.chain.balance("big", 60_000_000, spenders=[9, MONA["id"]])
    w.chain.balance("capped", 400_000_000, spenders=[MONA["id"]], cap=10_000_000)        # holds more, lets one job take less
    w.chain.balance("someone else's", 500_000_000, spenders=[EVE["id"]])
    w.chain.balance("another owner's", 900_000_000, spenders=[MONA["id"]], owner=77)
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos fund 40 checks: test days 30 reserve 3"))) == 0
    said = only(w, 7)
    job = pay.job_pda(REPO_ID, 7, big)
    assert said.startswith(f"Knos: 40.00 {MONEY} from the balance `{big}` is in escrow for issue #7 "
                           f"([job on Solana]({EXPLORER}/address/{job}?cluster=devnet)), 30 s after the comment.")
    assert "`test` (the checks you named)" in said and "If it is not paid by 2026-10-21 14:13 UTC" in said
    assert "`/knos take` reserves the issue for 3 days." in said
    assert w.signer.asked[0].endswith(f":{30 * 86_400}:{big}") and w.chain.held(big) == 20_000_000
    assert not w.chain.jobs(7)[0][1].faucet and w.chain.jobs(7)[0][1].funder_id == MONA["id"]


def test_a_strangers_balance_in_a_token_of_their_own_is_never_spent_by_a_comment(tmp_path):
    """Any wallet can open a Balance for any GitHub owner, in a token of its own making, holding any number of it, and
    the owner spends every Balance opened for their id. A comment spends test USDC, or a Balance opened by the wallet
    bound to the commenter's or the owner's GitHub account: nobody else can make a funder's bounty be in their token."""
    junk = key("a made-up mint")
    w = world(tmp_path)
    theirs = w.chain.balance("a stranger's", 10 ** 15, mint=junk)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 0
    assert only(w, 7).startswith(f"Knos: 20.00 {MONEY} from the devnet faucet is in escrow for issue #7 ")
    assert w.signer.asked[0].endswith(f":{FAUCET}") and w.chain.held(theirs) == 10 ** 15
    # the owner's own test USDC is spent, however much more of its token the stranger's holds
    w = world(tmp_path)
    theirs, own = w.chain.balance("a stranger's", 10 ** 15, mint=junk), w.chain.balance("own", 30_000_000)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 0
    assert only(w, 7).startswith(f"Knos: 20.00 {MONEY} from the balance `{own}` is in escrow for issue #7 ")
    assert w.chain.held(own) == 10_000_000 and w.chain.held(theirs) == 10 ** 15
    # more than the faucet gives and nothing else: nothing is funded, and the reply says why that balance is not spent
    w = world(tmp_path)
    theirs = w.chain.balance("a stranger's", 10 ** 15, mint=junk)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 200"))) == 0
    assert only(w, 7) == (
        "Knos: nothing was funded: no balance you can spend holds 200.00.\n"
        f"- Balance `{theirs}` holds 1000000000.00 of the test token `{junk}`, which a comment does not spend: Knos does not name "
        "that token, and the wallet that opened the balance is not the one bound to your GitHub account or to this repository's "
        "owner's.\n"
        "- The devnet faucet gives at most 100.00 test USDC for one job: `/knos fund 100` works now.\n"
        "Then post the comment again.")
    assert w.signer.asked == [] and w.chain.jobs() == []
    # a balance in another token that the wallet bound to the commenter's own GitHub account opened is theirs, and is spent
    w = world(tmp_path)
    mine = w.chain.balance("mine", 50_000_000, mint=junk)
    w.chain.bind(HUBOT, str(key("mine-wallet")))
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 0
    assert only(w, 7).startswith(f"Knos: 20.00 of the test token `{junk}` from the balance `{mine}` is in escrow for issue #7 ")


def test_with_no_money_the_reply_says_exactly_how_to_add_it(tmp_path):
    w = world(tmp_path)
    low = w.chain.balance("low", 30_000_000)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 200"))) == 0
    assert only(w, 7) == (
        "Knos: nothing was funded: no balance you can spend holds 200.00.\n"
        f"- Balance `{low}` holds 30.00 test USDC: send 170.00 more to its token account `{pay.baltok_pda(low)}` (a plain token "
        "transfer; anyone can).\n"
        "- The devnet faucet gives at most 100.00 test USDC for one job: `/knos fund 100` works now.\n"
        "Then post the comment again.")
    assert w.signer.asked == [] and w.chain.jobs() == []                                   # nothing was signed
    # a Balance whose wallet caps one job
    w = world(tmp_path)
    capped = w.chain.balance("capped", 400_000_000, cap=10_000_000)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 200"))) == 0
    assert f"- Balance `{capped}` holds 400.00 test USDC, and its wallet lets one job take at most 10.00." in only(w, 7)
    # off devnet there is no faucet: with no Balance at all, the owner is told what must exist
    w = world(tmp_path)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"), KNOS_CLUSTER="mainnet")) == 0
    assert only(w, 7) == ("Knos: nothing was funded: no balance you can spend holds 20.00.\n"
                          "- No Balance on Solana is set aside for this repository's owner (GitHub id 1). A wallet opens one for that id "
                          "with `knos balance open`, lists the GitHub ids that may spend it, and adds money with `knos balance deposit`.\n"
                          "Then post the comment again.")
    # a maintainer no Balance lists: the wallet that opened it has to name them
    w = world(tmp_path)
    w.hub.can["mona"] = "maintain"
    w.chain.balance("the owner's", 500_000_000)
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos fund 20"), KNOS_CLUSTER="mainnet")) == 0
    assert only(w, 7) == ("Knos: nothing was funded: no balance you can spend holds 20.00.\n"
                          "- 1 Balance is set aside on Solana for this repository's owner, and it does not list your GitHub id (4242) as "
                          "a spender. The wallet that opened it adds you with `knos balance set`.\nThen post the comment again.")
    assert w.signer.asked == [] and w.chain.jobs() == []


def test_only_someone_with_write_access_may_fund(tmp_path):
    w = world(tmp_path)
    assert flow.command(w.run(w.hub.commented(7, EVE, "/knos fund 20"))) == 0
    assert only(w, 7) == ("Knos: `/knos fund` is for people with write access to this repository. You can ask them to fund it: they "
                          "comment `/knos fund 20` on the issue.")
    assert w.signer.asked == [] and w.chain.jobs() == []
    # what GitHub answers for the account decides (write, maintain, admin); the label on a comment never does
    for level, allowed in (("write", True), ("maintain", True), ("admin", True), ("triage", False), ("read", False)):
        w = world(tmp_path)
        w.hub.can["mona"] = level
        event = w.hub.commented(7, MONA, "/knos fund 20")
        event["comment"]["author_association"] = "OWNER"
        assert flow.command(w.run(event)) == 0
        assert only(w, 7).startswith(f"Knos: 20.00 {MONEY} from the devnet faucet is in escrow" if allowed else "Knos: `/knos fund` is for people with write"), level
        assert "repos/o/r/collaborators/mona/permission" in w.hub.asked
    # a spender a Balance lists who cannot write to the repository may not fund from a comment either
    w = world(tmp_path)
    w.chain.balance("wallet", 60_000_000, spenders=[MONA["id"]])
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos fund 20"))) == 0
    assert only(w, 7).startswith("Knos: `/knos fund` is for people with write access") and w.signer.asked == []
    # GitHub does not answer who can write: nothing is assumed either way
    w = world(tmp_path)
    w.hub.down = ("/collaborators/",)
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos fund 20"))) == 1
    assert only(w, 7) == ("Knos: GitHub did not answer whether @mona can write to this repository, so nothing was funded. Post the "
                          "comment again.")


def test_an_issue_that_already_has_a_job_from_that_balance_gets_no_second_one(tmp_path):
    w = world(tmp_path)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 0
    asked = list(w.signer.asked)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 5"))) == 0
    first, second = w.hub.knos(7)
    assert plain(second) == (f"Knos: nothing was added. Issue #7 already has 20.00 {MONEY} in escrow from this balance, open until "
                             f"2026-10-05 14:13 UTC ([job on Solana]({EXPLORER}/address/{JOB}?cluster=devnet)). A balance holds one "
                             "bounty on an issue at a time; `/knos status` shows it.")
    assert w.signer.asked == asked and len(w.chain.jobs(7)) == 1
    # a Balance of real money that has not funded this issue yet can add to it
    other = w.chain.balance("wallet", 50_000_000)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 5"))) == 0
    assert plain(w.hub.knos(7)[-1]).startswith(f"Knos: 5.00 {MONEY} from the balance `{other}` is in escrow for issue #7")
    assert sorted(j.amount for _a, j in w.chain.jobs(7)) == [5_000_000, 20_000_000] and str(other) in w.signer.asked[-1]
    # past its deadline a job pays nobody, and still holds its place until it is refunded. The deadline is the chain's
    # to judge: its clock, not this machine's, says whether the time has run out
    w.clock.sleep(14 * 86_400 - 120)
    w.chain.ahead = 300
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 5"))) == 0
    assert "open until its time ran out on 2026-10-05 14:14 UTC: it pays nobody now and goes back to where it came from" in w.hub.knos(7)[-1]


def test_without_a_relay_key_the_token_is_posted_and_the_public_worker_carries_it(tmp_path):
    here, there = world(tmp_path), world(tmp_path, relay_key=False)
    assert flow.command(here.run(here.hub.commented(7, HUBOT, "/knos fund 20 checks: none"))) == 0
    assert flow.command(there.run(there.hub.commented(7, HUBOT, "/knos fund 20 checks: none"), KNOS_RELAY_LOG_REPO="knos/log")) == 0
    # the same reply either way (the worker's next pass came 9 seconds later)
    assert only(there, 7) == only(here, 7).replace("30 s after the comment", "39 s after the comment")
    assert "You asked for no checks; your merge alone is the acceptance." in only(here, 7)
    # the comment the worker reads: the token under its marker, the terms that travel with it, and the word it searches for
    token, jwt = there.hub.comments[7][1]["body"], there.relay.submitted[0][0]
    raw = there.chain.logs[str(JOB)].decode()
    assert token.startswith(f"knos-fund: {jwt}\nknos-terms: {raw}\n\n<sub>knosrelay: ") and token.endswith("</sub>")
    assert there.worker.waited == [(there.worker.token_id(jwt), "knos/log", 600)]
    assert here.worker.waited == [] and len(there.chain.jobs(7)) == 1 == len(here.chain.jobs(7))
    # the worker's log by default is Knos's own
    again = world(tmp_path, relay_key=False)
    flow.command(again.run(again.hub.commented(7, HUBOT, "/knos fund 20")))
    assert again.worker.waited[0][1:] == ("drexthealpha/Knos", 600)


def test_a_funding_the_chain_refuses_or_nobody_relays_is_said_with_what_to_do(tmp_path):
    w = world(tmp_path)
    w.relay.refusals = [{"ok": False, "kind": "fund", "why": pay.ERRORS[94]}]
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 1
    assert only(w, 7) == ("Knos: nothing was funded. GitHub signed the request and Solana did not take it: the balance does not hold "
                          "that much; add money to it or fund less. To try again, post the comment again.")
    # the faucet serves a repository once a minute: the job waits it out and tries the same token again
    w = world(tmp_path)
    w.relay.refusals = [{"ok": False, "kind": "fund", "why": pay.ERRORS[90], "retry": True}] * 2
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 0
    assert len(w.relay.submitted) == 3 and len({jwt for jwt, _terms in w.relay.submitted}) == 1 and w.clock.slept.count(20) == 2
    assert only(w, 7).startswith(f"Knos: 20.00 {MONEY} from the devnet faucet is in escrow for issue #7") and "130 s after the comment" in only(w, 7)
    w = world(tmp_path)
    w.relay.refusals = [{"ok": False, "kind": "fund", "why": pay.ERRORS[90], "retry": True}] * 9
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 1 and len(w.relay.submitted) == 4
    assert "Solana did not take it: the faucet gives test USDC once per repository per minute" in only(w, 7)
    # nobody carried the posted token within ten minutes
    w = world(tmp_path, relay_key=False)
    w.worker.silent = True
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 1
    assert only(w, 7) == ("Knos: not confirmed yet. GitHub signed the request (it is posted above) and no relayer carried it to Solana "
                          "within 10 minutes. Solana takes the signed token until an hour after it expires: if one carries it, the bounty is funded, and `/knos "
                          "status` shows it. Otherwise post the comment again.")
    # the worker carried it and the chain said no
    w = world(tmp_path, relay_key=False)
    w.relay.refusals = [{"ok": False, "kind": "fund", "why": pay.ERRORS[91]}]
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 1
    assert "Solana did not take it: this token is not newer than the last one used here, and a token works once; comment again for a new one. To" in only(w, 7)


def test_funding_stops_with_a_reason_before_anything_is_signed(tmp_path):
    def said(body="/knos fund 20", arrange=lambda w: None, code=0, **env) -> str:
        w = world(tmp_path)
        arrange(w)
        assert flow.command(w.run(w.hub.commented(7, HUBOT, body), **env)) == code
        assert w.signer.asked == [] and w.chain.jobs() == []
        return only(w, 7)
    # the terms cannot be fixed: checks still running on the default branch, or GitHub unreadable
    running = said(arrange=lambda w: w.hub.checks.update({w.hub.head: [check("test", None, status="in_progress")]}))
    assert running.startswith("Knos: Checks are still running on the default branch's latest commit (test).") and "`checks: none`" in running
    assert said(arrange=lambda w: setattr(w.hub, "down", ("/check-runs",))) == \
        "Knos: GitHub did not answer for this repository's checks, so the bounty's terms could not be fixed. Send the command again."
    assert said("/knos fund 20 checks: knos / check").startswith("Knos: `knos / check` is Knos's own job, and a bounty cannot require it.")
    assert said(arrange=lambda w: setattr(w.hub, "down", ("/contents/.knos",)), code=1) == (
        "Knos: GitHub did not answer for this issue's acceptance checks (.knos/acceptance/7/ on the default branch: 502 "
        f"repos/o/r/contents/.knos/acceptance?ref={sha('main')}), so the bounty's terms could not be fixed and nothing was funded. "
        "Post the comment again.")
    # new funding is paused on chain: said with the date it ends, before GitHub is asked to sign anything
    assert said(arrange=lambda w: w.chain.pause(T0 + 3 * 86_400)) == (
        "Knos: nothing was funded. New funding is paused on Solana until 2026-09-24 14:13 UTC (a pause lasts 7 days at most); "
        "payments, refunds and withdrawals go on. Post the comment again after that.")
    w = world(tmp_path)
    w.chain.pause(T0 - 60)                                                                 # a pause that has ended stops nothing
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 0 and len(w.chain.jobs(7)) == 1
    # a closed issue, a re-run, a chain that does not answer, GitHub not signing
    assert said(arrange=lambda w: w.hub.issues[7].update(state="closed")) == \
        "Knos: issue #7 is closed, so nothing was funded. Reopen it and post the comment again."
    assert said(GITHUB_RUN_ATTEMPT="2") == ("Knos: nothing was funded. This is a re-run, and money moves only on the first run of a "
                                            "comment. Post the comment again.")
    assert said(arrange=lambda w: setattr(w.chain, "down", True), code=1) == \
        "Knos: Solana could not be read just now (the cluster did not answer), so nothing was funded. Post the comment again."
    w = world(tmp_path)
    w.signer.down = True
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 1
    assert only(w, 7) == ("Knos: GitHub did not sign the request (GitHub's token endpoint did not answer), so nothing was funded. "
                          "Post the comment again.")
    assert said("/knos fund lots").startswith("Knos: that was not understood: the amount is digits with at most 6 decimals")


def test_a_new_issue_with_a_fund_line_is_funded_and_acceptance_checks_on_the_default_branch_make_it_tests_mode(tmp_path):
    w = World(tmp_path)
    files = {"blackbox.sh": BLACKBOX, "data/cases.json": b"[1, 2]\n"}                      # black-box: its checks alone may pay
    bundle = tmp_path / "checkout" / ".knos" / "acceptance" / "8"                          # the same files, as a checkout holds them
    for name, text in files.items():
        (bundle / name).parent.mkdir(parents=True, exist_ok=True)
        (bundle / name).write_bytes(text)
    w.hub.bundles = {8: files, 80: {"other.py": b"pass\n"}}
    w.hub.issue(8, "Slugify keeps punctuation.\n\n/knos fund 12.5 checks: none paths: src/**\n", at=T0 - 3)
    assert flow.command(w.run({"action": "opened", "issue": w.hub.issues[8], "repository": w.hub.repo})) == 0
    said = only(w, 8)
    assert said.startswith(f"Knos: 12.50 {MONEY} from the devnet faucet is in escrow for issue #8 ([job on Solana](")
    assert "), 33 s after the issue was opened." in said
    assert ("It is paid when its acceptance checks (.knos/acceptance/ for this issue) pass on a pull request. The pull request may not "
            "change `.github/**` or `.knos/**`, and may only change files matching `src/**`.") in said
    bought = terms.parse(w.chain.logs[str(pay.job_pda(REPO_ID, 8, FAUCET))])
    # no job checks the repository out: the files are read through GitHub's API at the default branch's head, and
    # hash to exactly what the judge computes from its checkout
    assert bought["mode"] == "tests" and bought["accept"] == judge.checks_hash(bundle) and bought["paths"] == ["src/**"]
    assert f"repos/o/r/contents/.knos/acceptance?ref={sha('main')}" in w.hub.asked
    assert w.signer.asked[0].split(":")[4] == "1" and w.chain.jobs(8)[0][1].mode == pay.TESTS
    # a link among the checks would not hash the same in a checkout: refused with what to do
    w.hub.issue(9, "/knos fund 5")
    w.hub.bundles[9] = {"check.sh": (b"../../../run.sh",)}
    assert flow.command(w.run({"action": "opened", "issue": w.hub.issues[9], "repository": w.hub.repo})) == 0
    assert only(w, 9) == ("Knos: `.knos/acceptance/9/check.sh` is a link or a submodule, and a bounty's acceptance checks are plain "
                          "files. Put the file itself there.")
    # acceptance checks that share a process with the pull request's code can be fooled from inside, and no veto
    # follows a proof: such a bundle buys merge mode, and the reply says why and what would change it
    w.hub.issue(30, "/knos fund 5 checks: none")
    w.hub.bundles[30] = {"test_slug.py": b"from slug import slug\n\n\ndef test_slug():\n    assert slug('a b') == 'a-b'\n"}
    assert flow.command(w.run({"action": "opened", "issue": w.hub.issues[30], "repository": w.hub.repo})) == 0
    said = only(w, 30)
    assert ("You asked for no checks; your merge alone is the acceptance. The pull request may not change `.github/**` or `.knos/**`. "
            "Its acceptance checks (.knos/acceptance/30/) load the pull request's code into the process that judges it, so only your "
            "merge pays this bounty (a pull request can fool such checks). To have the checks alone pay, add a `blackbox.sh` there "
            "that runs the pull request's code through `$KNOS_RUN` and compares its output. If it is not paid by ") in said
    bought = terms.parse(w.chain.logs[str(pay.job_pda(REPO_ID, 30, FAUCET))])
    assert (bought["mode"], bought["accept"]) == ("merge", "") and w.signer.asked[-1].split(":")[4] == "0" and w.chain.jobs(30)[0][1].mode == pay.MERGE
    # the same for a black-box file that another runner would run, or that opens the tree itself; and what runs the
    # checks is never guessed: GitHub not answering for .knos/proof.toml funds nothing
    for n, bundle, toml, why in ((31, {"blackbox.sh": BLACKBOX}, 'runner = "python"\n', "share a process with the pull request's code (runner `python`)"),
                                 (32, {"blackbox.sh": BLACKBOX}, '[judge]\nrun = "make check"\n', "are a `[judge] run` command, run inside the pull request's tree"),
                                 (33, {"blackbox.sh": BLACKBOX}, "runner = [", "cannot be checked: `.knos/proof.toml` is not valid TOML"),
                                 (34, {"blackbox.py": b"import os, sys\nsys.path.insert(0, os.environ['KNOS_TREE'])\nimport slug  # KNOS_RUN\n"}, None,
                                  "open the pull request's tree themselves (`KNOS_TREE`)"),
                                 (35, {"blackbox": b"exit 0\n"}, None, "never run the pull request's code through `$KNOS_RUN`"),
                                 (36, {"sub/blackbox.sh": BLACKBOX}, None, "load the pull request's code into the process that judges it")):
        w.hub.issue(n, "/knos fund 5 checks: none")
        w.hub.bundles[n] = bundle
        w.hub.contents = {} if toml is None else {".knos/proof.toml": toml}
        w.clock.sleep(61)                                                                  # the faucet serves a repository once a minute
        assert flow.command(w.run({"action": "opened", "issue": w.hub.issues[n], "repository": w.hub.repo})) == 0, n
        assert f" Its acceptance checks (.knos/acceptance/{n}/) {why}, so only your merge pays this bounty (a pull" in only(w, n), n
        assert w.chain.jobs(n)[0][1].mode == pay.MERGE and terms.parse(w.chain.logs[str(pay.job_pda(REPO_ID, n, FAUCET))])["accept"] == ""
    w.hub.issue(37, "/knos fund 5 checks: none")
    w.hub.bundles[37], w.hub.contents = {"blackbox.sh": BLACKBOX}, {".knos/proof.toml": 'runner = "blackbox"\n'}
    w.clock.sleep(61)
    assert flow.command(w.run({"action": "opened", "issue": w.hub.issues[37], "repository": w.hub.repo})) == 0
    assert w.chain.jobs(37)[0][1].mode == pay.TESTS and "acceptance checks (.knos/acceptance/37/)" not in only(w, 37)
    w.hub.issue(38, "/knos fund 5 checks: none")
    w.hub.bundles[38], w.hub.down = {"blackbox.sh": BLACKBOX}, ("/contents/.knos/proof.toml",)
    assert flow.command(w.run({"action": "opened", "issue": w.hub.issues[38], "repository": w.hub.repo})) == 1
    assert only(w, 38).startswith("Knos: GitHub did not answer for this issue's acceptance checks (.knos/acceptance/38/ on the default branch: 502 ")
    assert w.chain.jobs(38) == []
    w.hub.down, w.hub.contents = (), {}
    # an issue's description gives no other command; an issue opened without one, and one edited later, do nothing
    for n, body in ((10, "No command here."), (11, "/knos help"), (13, "/knos take")):
        w.hub.issue(n, body)
        assert flow.command(w.run({"action": "opened", "issue": w.hub.issues[n], "repository": w.hub.repo})) == 0 and w.hub.knos(n) == []
    w.hub.issue(14, "/knos fund")                                                          # a fund line that is not one is answered
    assert flow.command(w.run({"action": "opened", "issue": w.hub.issues[14], "repository": w.hub.repo})) == 0
    assert only(w, 14).startswith("Knos: that was not understood: the amount is missing. Type it like this: `/knos fund <amount>")
    assert flow.command(w.run({"action": "opened", "issue": w.hub.issue(15, "/knos fund 20", EVE), "repository": w.hub.repo})) == 0
    assert only(w, 15).startswith("Knos: `/knos fund` is for people with write access")    # the issue's author is who funds


# ---- knos command: a tip, a reservation, and the answers ---------------------------------------------------------------

def test_a_tip_is_funded_on_the_merged_pull_request_and_hands_over_to_settle(tmp_path, capsys):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.hub.merge(12)
    tipped = w.hub.commented(12, HUBOT, "/knos tip 5", at=w.clock() - 2)
    run = w.run(tipped)
    assert flow.command(run) == 0 and run.outputs == {"settle": "12"}                      # the workflow's next job pays it
    tip = pay.job_pda(REPO_ID, 12, FAUCET)
    assert only(w, 12) == (f"Knos: a tip of 5.00 {MONEY} for this pull request is in escrow ([job on Solana]({EXPLORER}/address/{tip}"
                           "?cluster=devnet)), 32 s after the comment. It is paid to @mona next; the result follows here.")
    assert w.chain.logs[str(tip)] == terms.canonical(terms.tip()) and w.signer.asked[-1].split(":")[6] == "86400"     # it asks for nothing; a day
    # the second job: `knos settle` on the same comment pays the tip, and only the tip (the bounty on #7 is not tried again)
    assert flow.settle(w.run(tipped)) == 0
    assert plain(w.hub.knos(12)[-1]) == (
        f"Knos: paid. @mona received 4.875 {MONEY} as a tip for this pull request: the tip of 5.00 less Knos's fee of 0.125. It went to "
        f"`{WALLET}`, the wallet bound to @mona's GitHub account ([transaction]({EXPLORER}/tx/sig4?cluster=devnet), 62 s after the "
        "comment).")
    assert [j.issue for _a, j in w.chain.jobs()] == [7] and w.signer.asked[-1].startswith(f"knos2:pay:{REPO_ID}:12:{MONA['id']}:")
    assert w.signer.asked[-1].split(":")[-2:] == ["0", "-"]                                # a tip is paid on the merge: mode 0
    # a tip `knos command` refused leaves nothing to pay: the settle job that follows the same comment adds no second answer
    said = len(w.hub.knos(12))
    refused = w.hub.commented(12, EVE, "/knos tip 5")
    assert flow.command(w.run(refused)) == 0 and w.hub.knos(12)[-1].startswith("Knos: `/knos tip` is for people with write access")
    capsys.readouterr()
    assert flow.settle(w.run(refused)) == 0 and len(w.hub.knos(12)) == said + 1
    assert "Knos settle: no tip waits for pull request #12 on Solana, so there is nothing to pay." in capsys.readouterr().out


def test_a_tip_that_could_reach_nobody_or_comes_from_nobody_is_not_put_in_escrow(tmp_path):
    w = bounty(tmp_path, author=DEVIN)
    w.hub.merge(12)
    run = w.run(w.hub.commented(12, HUBOT, "/knos tip 5"))
    assert flow.command(run) == 0 and run.outputs == {} and w.signer.asked == []
    assert plain(w.hub.knos(12)[-1]) == (
        "Knos: no tip was sent: devin-ai-integration[bot] is a bot account, and nothing GitHub authenticates names the person who ran "
        "it. A maintainer comments `/knos pay @login` on this pull request. Then post the comment again.")
    # a maintainer names the person; the tip then goes to them
    w.hub.say(12, HUBOT, "/knos pay @mona")
    run = w.run(w.hub.commented(12, HUBOT, "/knos tip 5"))
    assert flow.command(run) == 0 and run.outputs == {"settle": "12"} and "It is paid to @mona next" in w.hub.knos(12)[-1]
    # a second tip from the same balance while the first still waits
    assert flow.command(w.run(w.hub.commented(12, HUBOT, "/knos tip 2"))) == 0
    assert plain(w.hub.knos(12)[-1]).startswith(f"Knos: nothing was added. This pull request already has 5.00 {MONEY} in escrow from this balance")
    assert w.hub.knos(12)[-1].endswith("A balance holds one tip on a pull request at a time: comment `/knos settle` to have this one paid.")
    # someone who may not spend; a pull request that is not merged; an issue
    assert flow.command(w.run(w.hub.commented(12, EVE, "/knos tip 5"))) == 0
    assert w.hub.knos(12)[-1] == ("Knos: `/knos tip` is for people with write access to this repository. You can ask them: they "
                                  "comment `/knos tip 5` on the merged pull request.")
    w.hub.pull(13, MONA, "Refactor")
    assert flow.command(w.run(w.hub.commented(13, HUBOT, "/knos tip 5"))) == 0
    assert only(w, 13) == "Knos: this pull request is not merged. A tip is for a merged pull request: merge it first."
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos tip 5"))) == 0
    assert only(w, 7) == "Knos: `/knos tip` belongs on the pull request, not on an issue. Comment it there."


def test_take_and_release_change_the_issues_assignee_through_github(tmp_path):
    w = world(tmp_path)
    assert flow.command(w.run(w.hub.commented(7, EVE, "/knos take"))) == 0
    assert only(w, 7) == "Knos: issue #7 has no bounty, so there is nothing to reserve." and w.hub.issues[7]["assignees"] == []
    w.chain.fund(7, 20_000_000, {**BOUGHT, "reserve": 3})
    assert flow.command(w.run(w.hub.commented(7, EVE, "/knos take"))) == 0
    assert plain(w.hub.knos(7)[-1]) == (
        "Knos: issue #7 is reserved for @eve until 2026-09-24 14:13 UTC. Open a pull request whose description says `Fixes #7`; until "
        "then only yours is paid for it. After that it is open to everyone again. `/knos release` gives it back sooner.")
    assert w.hub.issues[7]["assignees"] == [EVE] and ("repos/o/r/issues/7/assignees", {"assignees": ["eve"]}) in w.hub.posted
    assert w.hub.events[7][-1]["assigner"] == BOT                                          # GitHub records the workflow's own token
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos take"))) == 0
    assert w.hub.knos(7)[-1].startswith("Knos: issue #7 is assigned to @eve until 2026-09-24 14:13 UTC, so only their pull request is paid")
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos release"))) == 0
    assert w.hub.knos(7)[-1].startswith("Knos: you do not hold issue #7, so nothing changed.") and w.hub.issues[7]["assignees"] == [EVE]
    assert flow.command(w.run(w.hub.commented(7, EVE, "/knos release"))) == 0
    assert w.hub.knos(7)[-1] == "Knos: @eve gave issue #7 back. It is open to everyone. `/knos take` reserves it."
    assert w.hub.issues[7]["assignees"] == [] and w.hub.wrote[-2:] == ["repos/o/r/issues/7/assignees", "repos/o/r/issues/7/comments"]
    # GitHub quietly ignores a login it will not assign; GitHub refusing; a chain that cannot say whether there is a bounty
    w.hub.unassignable = {"mona"}
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos take"))) == 0
    assert w.hub.knos(7)[-1] == ("Knos: GitHub did not assign @mona to issue #7, so nothing was reserved. A maintainer can assign them "
                                 "with GitHub's own assignee control.")
    w.hub.down = ("/assignees",)
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos take"))) == 1
    assert w.hub.knos(7)[-1] == ("Knos: GitHub did not change who issue #7 is assigned to (502 repos/o/r/issues/7/assignees), so nothing "
                                 "was reserved. Post the comment again.")
    w.hub.down, w.chain.down = (), True
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos take"))) == 1
    assert w.hub.knos(7)[-1] == ("Knos: whether issue #7 has a bounty could not be read just now (the cluster did not answer), so nothing was "
                                 "changed. Post the comment again.")
    w.chain.down = False
    del w.chain.logs[str(JOB)]                                                             # a job whose terms cannot be read is not "no bounty"
    assert flow.command(w.run(w.hub.commented(7, MONA, "/knos take"))) == 1
    assert "the bounty's terms could not be read from Solana" in w.hub.knos(7)[-1] and w.hub.issues[7]["assignees"] == []


def test_every_other_knos_comment_gets_its_answer(tmp_path):
    w = bounty(tmp_path, author=DEVIN, body="Fixes #7\n\nRequested by: @mona")
    w.hub.pulls[12]["assignees"] = [MONA]

    def reply(n: int, who_: dict, body: str, code: int = 0) -> str:
        run = w.run(w.hub.commented(n, who_, body))
        assert flow.command(run) == code and run.outputs == {}
        return plain(w.hub.knos(n)[-1], 2000 if "- `/knos help`: this list" in w.hub.knos(n)[-1] else 1100)     # the list of commands is the one long answer (18 lines since 0.3.21: the reserve's)
    # an agent's pull request: nobody is paid until GitHub authenticates a person
    assert reply(12, MONA, f"/knos address {ADDRESS}").startswith("Knos: `/knos address` is for the person this pull request pays. An address counts once")
    assert reply(12, EVE, "/knos mine") == ("Knos: `/knos mine` is for a person named in this pull request's assignees, when a bot account "
                                           "opened it. A maintainer can name you instead: they comment `/knos pay @you` on the pull request.")
    assert reply(12, MONA, "/knos mine") == ("Knos: noted. This pull request pays @mona: named in the assignees of "
                                            "devin-ai-integration[bot]'s pull request, and claimed it with `/knos mine`.")
    assert reply(12, MONA, f"/knos address {ADDRESS}").startswith(f"Knos: noted. @mona's payment for this pull request goes to {ADDRESS}, unless")
    assert reply(12, EVE, "/knos pay @eve").startswith("Knos: `/knos pay` is for people with write access to this repository.")
    assert reply(12, HUBOT, "/knos pay @eve") == "Knos: noted. This pull request pays @eve: maintainer @hubot named them with `/knos pay`."
    # an address when a wallet is bound already: where the money will really go
    w.chain.bind(EVE)
    assert reply(12, EVE, f"/knos address {ADDRESS}").endswith(
        f"To change the address, post a new one. A wallet is bound to @eve's GitHub account already (`{WALLET}`), so the payment goes there.")
    assert reply(12, EVE, "/knos reject").startswith("Knos: `/knos reject` is for people with write access to this repository.")
    assert reply(12, HUBOT, "/knos reject only half of it") == (
        "Knos: noted. This pull request does not take the bounty (rejected by @hubot: only half of it). It can still be merged. To undo, "
        "delete that comment.")
    # what is not a command as written, and what is in the wrong place
    assert reply(12, EVE, "/knos").startswith("Knos acts on the first line of a comment that starts with `/knos`:\n- `/knos fund <amount>")
    assert reply(12, EVE, "/knos frobnicate").startswith("Knos: `frobnicate` is not a command. These are:")
    assert reply(12, EVE, "/knos pay") == "Knos: that was not understood: name one GitHub account. Type it like this: `/knos pay @login`."
    assert reply(12, HUBOT, "/knos fund 20") == "Knos: `/knos fund` belongs on the issue, not on a pull request. Comment it there."
    assert reply(7, EVE, "/knos mine") == "Knos: `/knos mine` belongs on the pull request, not on an issue. Comment it there."
    assert reply(12, EVE, "/knos settle") == "Knos: this pull request is not merged. Its payment is tried once it is."
    # `/knos settle` on a merged pull request: the answer, and the pull request's number for the job that settles
    w.hub.merge(12)
    run = w.run(w.hub.commented(12, EVE, "/knos settle"))
    assert flow.command(run) == 0 and run.outputs == {"settle": "12"}
    assert w.hub.knos(12)[-1] == "Knos: trying this pull request's payment again. The result follows here."
    assert w.signer.asked == []                                                            # none of this asked GitHub to sign anything
    # GitHub not answering for the pull request is said, not guessed around
    w.hub.down = ("/pulls/12",)
    assert reply(12, HUBOT, "/knos pay @mona", 1) == "Knos: GitHub did not answer for this pull request, so nothing was done. Post the comment again."


def test_status_says_what_is_in_escrow_its_terms_and_who_holds_the_issue(tmp_path):
    w = world(tmp_path)

    def status(n: int = 7, code: int = 0) -> str:
        assert flow.command(w.run(w.hub.commented(n, EVE, "/knos status"))) == code
        return plain(w.hub.knos(n)[-1])
    assert status() == "Knos: nothing is in escrow for issue #7. A maintainer puts a bounty on it with `/knos fund <amount>`."
    w.chain.fund(7, 20_000_000, BOUGHT)
    job = f"([job on Solana]({EXPLORER}/address/{JOB}?cluster=devnet))"
    told = ("It is paid when a maintainer merges a pull request that closes this issue, if these checks passed at that pull request's "
            "last commit: `build`, `test`. The pull request may not change `.github/**` or `.knos/**`. `/knos take` reserves the issue "
            "for 7 days.")
    assert status() == f"Knos: 20.00 {MONEY} is in escrow for issue #7 until 2026-10-05 14:13 UTC {job}. {told} Nobody holds it."
    flow.command(w.run(w.hub.commented(7, MONA, "/knos take")))
    assert status().endswith(f"{told} It is assigned to @mona until 2026-09-28 14:13 UTC: only their pull request is paid for it.")
    # a second job, from a wallet's Balance; and one already proven and held for someone
    other = w.chain.fund(7, 5_000_000, {**BOUGHT, "checks": []}, source=key("wallet"), faucet=False)
    assert status().startswith(f"Knos: 20.00 {MONEY} is in escrow for issue #7 until 2026-10-05 14:13 UTC {job}.") and \
        f"\n\n5.00 {MONEY} is in escrow for issue #7 until 2026-10-05 14:13 UTC ([job on Solana]({EXPLORER}/address/{other}?cluster=devnet)). This repository has no checks; your merge alone is the acceptance." in w.hub.knos(7)[-1]
    w.hub.issue(9)
    w.chain.fund(9, 20_000_000, BOUGHT, state=3, payee=MONA["id"], hold_until=int(T0) + 180 * 86_400)
    held = pay.job_pda(REPO_ID, 9, FAUCET)
    assert status(9) == (f"Knos: 20.00 {MONEY} for issue #9 is held for GitHub user id 4242 until 2027-03-20 14:13 UTC: it is paid "
                         f"when they bind a wallet ([job on Solana]({EXPLORER}/address/{held}?cluster=devnet)).")
    w.chain.down = True
    assert status(code=1) == ("Knos: Solana could not be read just now (the cluster did not answer), so what is in escrow for issue #7 "
                              "is not known. Comment `/knos status` again.")


def test_status_on_a_merged_pull_request_says_what_a_settle_would_do_and_signs_nothing(tmp_path):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.hub.merge(12)
    assert flow.command(w.run(w.hub.commented(12, EVE, "/knos status"))) == 0
    assert only(w, 12) == (
        f"Knos: everything the bounty on issue #7 (20.00 {MONEY}) asks for holds.\n- `build`: passed\n- `test`: passed\nIt pays @mona "
        f"(the pull request's author) at `{WALLET}`, the wallet bound to their GitHub account.\nComment `/knos settle` to have it paid.")
    assert w.signer.asked == [] and len(w.chain.jobs(7)) == 1
    w = bounty(tmp_path)
    w.hub.checks[w.hub.pulls[12]["head"]["sha"]] = [check("build"), check("test", "failure")]
    w.hub.merge(12)
    assert flow.command(w.run(w.hub.commented(12, EVE, "/knos status"))) == 0 and only(w, 12) == REFUSED
    w.hub.pull(13, EVE, "Typo.")
    w.hub.merge(13)
    assert flow.command(w.run(w.hub.commented(13, EVE, "/knos status"))) == 0
    assert only(w, 13) == ("Knos: nothing to pay: this pull request closes no issue (its description would say `Fixes #N`), and no tip "
                           "waits for it.")
    w.chain.down = True                                                                    # an answer Solana left incomplete fails the job
    assert flow.command(w.run(w.hub.commented(12, EVE, "/knos status"))) == 1
    assert w.hub.knos(12)[-1] == ("Knos: Solana could not be read for issue #7, so whether anything is in escrow there is not known. "
                                  "Comment `/knos status` to try again.")


def test_a_reply_github_will_not_take_is_on_the_runs_page_and_the_job_fails(tmp_path, capsys, monkeypatch):
    w = world(tmp_path)
    w.hub.readonly = True
    run = w.run(w.hub.commented(7, EVE, "/knos help"), GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"))
    assert flow.command(run) == 1 and w.hub.knos(7) == []
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith("GitHub did not take this comment on #7 (HTTP Error 403: Resource not accessible by integration):\n\n"
                              "Knos acts on the first line of a comment that starts with `/knos`:")
    assert "Knos acts on the first line" in capsys.readouterr().out
    # anything unforeseen is told to the commenter too, never dropped
    w = world(tmp_path)
    w.chain.program_accounts = lambda *a, **k: 1 / 0
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 1
    assert only(w, 7) == "Knos: Solana could not be read just now (division by zero), so nothing was funded. Post the comment again."
    w = world(tmp_path)
    monkeypatch.setattr(flow, "_status", lambda *a: [][0])
    assert flow.command(w.run(w.hub.commented(7, EVE, "/knos status"))) == 1
    assert only(w, 7) == ("Knos: this stopped before it was finished (IndexError: list index out of range). `/knos status` shows what "
                          "is in escrow now; post the comment again to retry.")
    w = world(tmp_path)
    w.hub.repo = {**w.hub.repo, "default_branch": None}                                    # GitHub's event without what the chain keys on
    w.hub.down = ("repos/o/r",)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 1
    assert w.hub.knos(7) == []                                                             # GitHub is down: the words are in the job's log
    assert "GitHub did not answer for this repository, so nothing was funded." in capsys.readouterr().out


# ---- knos settle -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("how", ["merge", "squash", "rebase"])
def test_a_merge_pays_the_bounty_to_the_authors_bound_wallet_however_it_was_merged(tmp_path, how):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    push = w.hub.merge(12, how)
    assert len(push["commits"]) == {"merge": 3, "squash": 1, "rebase": 2}[how]
    w.clock.sleep(4)                                                                       # the workflow starts
    assert flow.settle(w.run(push)) == 0
    assert only(w, 12) == PAID
    assert w.chain.jobs() == [] and w.hub.knos(7) == []                                    # the job is closed; the issue is not written on
    head = w.hub.pulls[12]["head"]["sha"]                                                  # the proof names the pull request's own head
    assert w.signer.asked == [pay.pay_audience(REPO_ID, 7, MONA["id"], head, pay.terms_hash(terms.canonical(BOUGHT)), pay.MERGE)]
    assert claims(w.relay.submitted[0][0])["aud"].endswith(":0:-") and w.relay.submitted[0][1] is None
    assert any(p.endswith("/pulls?per_page=100") for p in w.hub.asked)                     # GitHub was asked which pull request each commit is of
    # a ledger that hands the terms' log line back as the runtime prints it ("Program log: ...") is read just the same;
    # so is one whose log_of takes no check; and a line a stranger logged later, naming the job, is not taken for its terms
    for arrange in (lambda w: setattr(w.chain, "prefixed", True),
                    lambda w: setattr(w.chain, "log_of", lambda address, marker, real=w.chain.log_of: real(address, marker)),
                    lambda w: w.chain.newer.update({str(JOB): ['Program log: knos2:terms {"accept":"","checks":[]}']})):
        w = bounty(tmp_path)
        w.chain.bind(MONA)
        arrange(w)
        assert flow.settle(w.run(w.hub.merge(12, how))) == 0 and only(w, 12).startswith("Knos: paid. @mona received 19.50 ")


def test_two_pull_requests_merged_by_one_push_are_each_settled(tmp_path):
    w = bounty(tmp_path)
    w.hub.issue(9, "Another one.")
    w.chain.fund(9, 5_000_000, {**BOUGHT, "checks": []})
    w.hub.pull(13, EVE, "Closes #9")
    w.hub.pull(14, EVE, "Typo.")                                                           # no bounty: merged in the same push, never written on
    w.chain.bind(MONA)
    a, b, c = (w.hub.merge(n)["commits"][0]["id"] for n in (12, 13, 14))
    assert flow.settle(w.run(w.hub.push([a, b, c]))) == 0
    assert only(w, 12).startswith("Knos: paid. @mona received 19.50 ") and w.hub.knos(14) == []
    assert only(w, 13).startswith(f"Knos: held for @eve. 5.00 {MONEY} for issue #9 waits for them until ")
    assert [a.split(":")[3] for a in w.signer.asked] == ["7", "9"] and [j.state for _a, j in w.chain.jobs()] == ["held"]


def test_a_pull_request_that_closes_two_funded_issues_takes_both_in_one_comment(tmp_path):
    w = bounty(tmp_path, body="Fixes #7 and fixes #9.")
    w.hub.issue(9, "Another one.")
    w.chain.fund(9, 5_000_000, {**BOUGHT, "checks": [{"app": 15368, "name": "lint"}]})    # its own terms: a check this commit lacks
    w.chain.bind(MONA)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    first, second = only(w, 12).split("\n\n")
    assert first == PAID.replace("34 s", "30 s")
    assert second.startswith(f"Not paid. This pull request does not take the bounty on issue #9 (5.00 {MONEY}) as it stands;") and \
        "\n- `lint`: did not run on this commit\n" in second
    assert len(w.signer.asked) == 1 and [j.issue for _a, j in w.chain.jobs()] == [9]
    # GitHub's own list also holds an issue a maintainer linked by hand, which no word of the description closes
    w = bounty(tmp_path, body="Makes slugify strip punctuation.")
    w.hub.closes[12] = [7]
    w.chain.bind(MONA)
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and only(w, 12).startswith("Knos: paid. @mona received 19.50 ")


STATES = {
    "failed": (check("test", "failure"), "failed"),
    "skipped": (check("test", "skipped"), "was skipped, which does not count as passing"),
    "absent": (None, "did not run on this commit"),
    "pending": (check("test", None, status="in_progress"), "has not finished"),
}


@pytest.mark.parametrize("state", ["passed", "failed", "skipped", "absent", "pending", "unreadable"])
def test_each_state_of_a_required_check_has_its_own_outcome(tmp_path, state):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    head = w.hub.pulls[12]["head"]["sha"]
    if state in STATES:
        w.hub.checks[head] = [check("build"), *([STATES[state][0]] if STATES[state][0] else [])]
    if state == "unreadable":
        w.hub.down = ("/check-runs",)
    code = flow.settle(w.run(w.hub.merge(12)))
    said = only(w, 12)
    if state == "passed":
        assert code == 0 and said == PAID.replace("34 s", "30 s") and 15 not in w.clock.slept     # nothing to wait for
        return
    assert w.signer.asked == [] and len(w.chain.jobs(7)) == 1                              # nothing signed, nothing moved
    if state == "unreadable":      # never a proof on a guess: said, and the job fails so the run shows it
        assert code == 1 and said == (
            f"Knos: nothing was decided about the bounty on issue #7 (20.00 {MONEY}): something could not be read, and nothing is signed "
            "on a guess.\n- `build`: could not be read from GitHub\n- `test`: could not be read from GitHub\nNothing was paid. Comment "
            "`/knos settle` to try again.")
        assert w.clock.slept[1:] == [15] * 8
    elif state == "pending":       # waited for two minutes, then told how to finish it
        assert code == 0 and w.clock.slept[1:] == [15] * 8 and said == (
            f"Knos: not paid yet. The bounty on issue #7 (20.00 {MONEY}) needs every check below to pass at this pull request's last "
            f"commit (`{head[:7]}`), and one has not finished.\n- `build`: passed\n- `test`: has not finished\nComment `/knos settle` "
            "when it has.")
    else:
        assert code == 0 and said == REFUSED.replace("- `test`: failed", f"- `test`: {STATES[state][1]}") and w.clock.slept == [3600]


def test_a_check_that_finishes_while_settle_waits_is_paid_and_settle_again_pays_what_finished_later(tmp_path):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    head = w.hub.pulls[12]["head"]["sha"]
    w.hub.checks[head] = [check("build"), check("test", None, status="queued")]
    real = w.clock.sleep

    def sleep(seconds):            # the check finishes half a minute into the wait
        real(seconds)
        if w.clock.slept.count(15) == 2:
            w.hub.checks[head] = [check("build"), check("test")]
    w.clock.sleep = sleep
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    assert only(w, 12) == PAID.replace("34 s", "60 s") and w.clock.slept.count(15) == 2
    # a check still running after the wait: `/knos settle`, once it has passed, pays
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.hub.checks[w.hub.pulls[12]["head"]["sha"]] = [check("build"), check("test", None, status="queued")]
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and w.signer.asked == []
    w.hub.checks[w.hub.pulls[12]["head"]["sha"]] = [check("build"), check("test")]
    asked = w.hub.commented(12, EVE, "/knos settle")                                       # anyone may ask
    assert flow.settle(w.run(asked)) == 0
    assert plain(w.hub.knos(12)[-1]) == PAID.replace("34 s after the merge", "30 s after the comment").replace("sig2", "sig2")


def test_a_pull_request_a_maintainer_rejected_before_the_merge_is_not_paid(tmp_path):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.hub.say(12, HUBOT, "/knos reject not the fix we want")
    w.clock.sleep(60)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    said = only(w, 12)
    assert "\n- @hubot rejected this pull request for the bounty (not the fix we want)\n" in said and w.signer.asked == []
    assert "To undo, @hubot deletes that `/knos reject` comment. Then comment `/knos settle`. A maintainer can pay this work anyway with `/knos tip <amount>`." in said
    # a reject by someone who cannot write, one that was edited, and one written after the merge do not count
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.hub.say(12, EVE, "/knos reject")
    w.hub.say(12, HUBOT, "/knos reject", edited=True)
    w.clock.sleep(60)
    push = w.hub.merge(12)
    w.clock.sleep(60)
    w.hub.say(12, HUBOT, "/knos reject too late")
    assert flow.settle(w.run(push)) == 0 and only(w, 12).startswith("Knos: paid. @mona received 19.50 ")


def test_an_agents_pull_request_pays_only_a_person_github_authenticates(tmp_path):
    w = bounty(tmp_path, author=DEVIN, body="Fixes #7\n\nRequested by: @eve")              # what its text says names nobody
    w.hub.pulls[12]["assignees"] = [MONA]
    push = w.hub.merge(12)
    assert flow.settle(w.run(push)) == 0 and w.signer.asked == []
    assert only(w, 12) == REFUSED.replace("`test`: failed", "`test`: passed\n- devin-ai-integration[bot] is a bot account, and nothing "
                                          "GitHub authenticates names the person who ran it").replace(
        "If a check that did not pass is run again on that commit and passes, comment `/knos settle`.",
        "A maintainer comments `/knos pay @eve` on this pull request, or @mona (named in its assignees) comments `/knos mine`. Then "
        "comment `/knos settle`.")
    # the person its assignees name claims it, gives an address, and asks again
    w.hub.say(12, MONA, "/knos mine")
    w.hub.say(12, MONA, f"/knos address {ADDRESS}")
    assert flow.settle(w.run(w.hub.commented(12, MONA, "/knos settle"))) == 0
    assert plain(w.hub.knos(12)[-1]) == (
        f"Knos: paid. @mona received 19.50 {MONEY} for issue #7: the bounty of 20.00 less Knos's fee of 0.50. It went to `{ADDRESS}`, the "
        f"address in @mona's `/knos address` comment ([transaction]({EXPLORER}/tx/sig2?cluster=devnet), 30 s after the comment).")
    assert w.signer.asked[0].split(":")[4] == str(MONA["id"]) and w.signer.asked[0].endswith(f":0:{ADDRESS}")
    # a maintainer's word comes before a claim; and GitHub not answering who can write is no answer
    w = bounty(tmp_path, author=DEVIN)
    w.hub.say(12, HUBOT, "/knos pay @eve")
    w.chain.bind(EVE)
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and only(w, 12).startswith("Knos: paid. @eve received 19.50 ")
    w = bounty(tmp_path, author=DEVIN)
    w.hub.say(12, HUBOT, "/knos pay @eve")
    w.hub.down = ("/collaborators/",)
    assert flow.settle(w.run(w.hub.merge(12))) == 1 and w.signer.asked == []
    assert "\n- GitHub did not say whether @hubot, who wrote `/knos pay`, can write to the repository, so who is paid cannot be decided yet\n" in only(w, 12)


def test_an_assigned_issue_pays_only_its_assignees_pull_request(tmp_path):
    w = bounty(tmp_path)
    w.hub.issues[7]["assignees"] = [EVE]
    w.hub.events[7] = [{"event": "assigned", "assignee": EVE, "assigner": HUBOT, "created_at": stamp(T0)}]
    w.chain.bind(MONA)
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and w.signer.asked == []
    said = only(w, 12)
    assert "\n- issue #7 is assigned to @eve; only an assignee's pull request is paid for it\n" in said
    assert "A maintainer can change the issue's assignee; a `/knos take` lapses on the date shown. Then comment `/knos settle`." in said
    # eve's own pull request for it is paid
    w.hub.pull(13, EVE, "Fixes #7")
    w.hub.checks[w.hub.pulls[13]["head"]["sha"]] = [check("test"), check("build")]
    w.chain.bind(EVE)
    assert flow.settle(w.run(w.hub.merge(13))) == 0 and only(w, 13).startswith("Knos: paid. @eve received 19.50 ")
    # a `/knos take` that lapsed before the merge holds nothing
    w = bounty(tmp_path)
    w.hub.issues[7]["assignees"] = [EVE]
    w.hub.events[7] = [{"event": "assigned", "assignee": EVE, "assigner": BOT, "created_at": stamp(T0)}]
    w.clock.sleep(8 * 86_400)
    w.chain.bind(MONA)
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and only(w, 12).startswith("Knos: paid. @mona received 19.50 ")


def test_a_pull_request_merged_before_the_bounty_was_funded_does_not_take_it(tmp_path):
    w = world(tmp_path)
    head = w.hub.pull(12, MONA, "Fixes #7")["head"]["sha"]
    w.hub.checks[head] = [check("test"), check("build")]
    w.chain.bind(MONA)
    w.hub.merge(12)
    w.clock.sleep(86_400)
    w.chain.fund(7, 20_000_000, BOUGHT)                                                    # the issue is funded a day after that merge
    assert flow.settle(w.run(w.hub.commented(12, MONA, "/knos settle"))) == 0
    assert only(w, 12) == (
        f"Knos: not paid. This pull request does not take the bounty on issue #7 (20.00 {MONEY}) as it stands; its checks are read at its "
        f"last commit (`{head[:7]}`).\n- `build`: passed\n- `test`: passed\n- it was merged on 2026-09-21 14:13 UTC, before this bounty "
        "was funded (2026-09-22 14:13 UTC): a bounty pays work merged after it was funded\nA maintainer can pay this work anyway with "
        "`/knos tip <amount>`. The money stays in escrow until 2026-10-06 14:13 UTC, then goes back to where it came from.")
    assert w.signer.asked == [] and len(w.chain.jobs(7)) == 1
    # a job someone adds with the same terms after a merge cannot hold back the bounty that was there before it
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    push = w.hub.merge(12)
    w.clock.sleep(5)
    w.chain.fund(7, 1_000_000, BOUGHT, source=key("a stranger's wallet"), faucet=False)
    assert flow.settle(w.run(push)) == 0 and only(w, 12).startswith("Knos: paid. @mona received 20.45 ") and w.chain.jobs() == []


def test_a_description_edited_after_the_merge_takes_no_bounty(tmp_path):
    """A pull request's author can edit its description at any time, also after the merge. `Fixes #7` written then
    was never in front of the maintainer who merged it, so it takes nothing; an edit before the merge is the
    description that was merged."""
    w = bounty(tmp_path, body="Fixes a typo in the README.")                              # merged for what it said then
    w.chain.bind(MONA)
    push = w.hub.merge(12)
    assert flow.settle(w.run(push)) == 0 and w.hub.knos(12) == []                           # it closes no issue: nothing to say
    w.clock.sleep(600)
    w.hub.edit(12, "Fixes #7")
    head = w.hub.pulls[12]["head"]["sha"]
    assert flow.settle(w.run(w.hub.commented(12, MONA, "/knos settle"))) == 0
    assert only(w, 12) == (
        f"Knos: not paid. This pull request does not take the bounty on issue #7 (20.00 {MONEY}) as it stands; its checks are read at its "
        f"last commit (`{head[:7]}`).\n- `build`: passed\n- `test`: passed\n- its description was edited on 2026-09-21 15:23 UTC, after "
        "it was merged, so what it says it closes no longer counts (anyone who can edit it could add `Fixes #7` later)\nA maintainer can "
        "pay this work anyway with `/knos tip <amount>`. The money stays in escrow until 2026-10-05 14:13 UTC, then goes back to where it "
        "came from.")
    assert w.signer.asked == [] and len(w.chain.jobs(7)) == 1
    # GitHub's own list of what it closes follows the description, so it does not count either; `/knos status` says the same
    w.hub.closes[12] = [7]
    assert flow.command(w.run(w.hub.commented(12, EVE, "/knos status"))) == 0
    assert "after it was merged, so what it says it closes no longer counts" in w.hub.knos(12)[-1] and w.signer.asked == []
    # not knowing whether it was edited is not "it was not": nothing is signed, and the job fails so that it is run again
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.hub.merge(12)
    w.hub.down = ("graphql",)
    assert flow.settle(w.run(w.hub.commented(12, MONA, "/knos settle"))) == 1
    assert ("- GitHub did not say whether this pull request's description was edited after it was merged, so who is paid cannot be "
            "decided yet\n") in only(w, 12)
    assert w.signer.asked == [] and len(w.chain.jobs(7)) == 1
    # an edit before the merge is what the maintainer merged
    w = bounty(tmp_path, body="Work in progress.")
    w.chain.bind(MONA)
    w.hub.edit(12, "Fixes #7")
    w.clock.sleep(60)
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and only(w, 12).startswith("Knos: paid. @mona received 19.50 ")


def test_where_the_money_goes_a_bound_wallet_else_the_authors_address_else_it_is_held(tmp_path):
    # a bound wallet comes first, whatever address the pull request gives
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.hub.say(12, MONA, f"/knos address {ADDRESS}")
    push = w.hub.merge(12)
    w.clock.sleep(4)
    assert flow.settle(w.run(push)) == 0 and only(w, 12) == PAID and w.signer.asked[0].endswith(":0:-")
    # no wallet bound: the newest unedited `/knos address` of the payee
    w = bounty(tmp_path)
    w.hub.say(12, EVE, f"/knos address {WALLET}")                                          # not the payee's to give
    w.hub.say(12, MONA, f"/knos address {ADDRESS}")
    push = w.hub.merge(12)
    w.clock.sleep(4)
    assert flow.settle(w.run(push)) == 0
    assert only(w, 12) == PAID.replace(f"`{WALLET}`, the wallet bound to @mona's GitHub account", f"`{ADDRESS}`, the address in @mona's `/knos address` comment")
    assert w.signer.asked[0].endswith(f":0:{ADDRESS}") and w.chain.jobs() == []
    # neither: proven now, held for them, and they are told how to receive it
    for comments in ((), (f"/knos address {ADDRESS}",)):
        w = bounty(tmp_path)
        for body in comments:
            w.hub.say(12, MONA, body, edited=True)                                         # an edited comment does not count
        push = w.hub.merge(12)
        w.clock.sleep(4)
        assert flow.settle(w.run(push)) == 0
        assert only(w, 12) == HELD and w.signer.asked[0].endswith(":0:-")
        (_address, job), = w.chain.jobs(7)
        assert (job.state, job.payee_id, job.hold_until) == ("held", MONA["id"], int(w.clock()) + pay.HOLD)
    # a chain that cannot say whether a wallet is bound: no proof is signed that might name the wrong place
    w = bounty(tmp_path)
    real = w.chain.account
    w.chain.account = lambda address: (_ for _ in ()).throw(OSError("timeout")) if str(address) == str(pay.bind_pda(MONA["id"])) else real(address)
    assert flow.settle(w.run(w.hub.merge(12))) == 1 and w.signer.asked == []
    assert "\n- Solana did not say whether a wallet is bound to @mona's GitHub account\nNothing was paid. Comment `/knos settle` to try again." in only(w, 12)


def test_a_proof_the_chain_refuses_or_nobody_relays_is_said_with_what_to_do(tmp_path):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.relay.refusals = [{"ok": False, "kind": "pay", "why": pay.ERRORS[77]}]
    assert flow.settle(w.run(w.hub.merge(12))) == 1
    assert only(w, 12) == (
        f"Knos: not paid yet. The bounty on issue #7 (20.00 {MONEY}) met its terms for @mona and GitHub signed the token, but Solana did not "
        "take it: the key that signed this token has expired on chain; run the rotate workflow and send Refresh for the key, then relay "
        "the token again while it is fresh. Comment `/knos settle` to try again.")
    assert len(w.chain.jobs(7)) == 1
    # the cluster dropped it once: the same proof is tried again, and it is paid
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.relay.refusals = [{"ok": False, "why": "TimeoutError: not confirmed", "retry": True, "transient": True}]
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and only(w, 12) == PAID.replace("34 s", "80 s")
    # the public worker: the token is posted on the pull request; nobody carries it in ten minutes
    w = bounty(tmp_path, relay_key=False)
    w.chain.bind(MONA)
    w.worker.silent = True
    assert flow.settle(w.run(w.hub.merge(12))) == 1
    assert only(w, 12) == (
        f"Knos: not confirmed yet. The bounty on issue #7 (20.00 {MONEY}) met its terms for @mona and GitHub signed the token (it is posted "
        "below), but no relayer carried it to Solana within 10 minutes. Solana takes the signed token until an hour after it expires: if one carries it, the "
        "payment is made, and `/knos status` shows it. Otherwise comment `/knos settle` for a new token.")
    posted = w.hub.comments[12][1]["body"]                                                 # a pay token travels as knos-proof, with no terms line (under the comment that said "received")
    assert posted.startswith("knos-proof: eyJ") and "knos-terms" not in posted and "<sub>knosrelay: " in posted and w.clock.slept[-1] == 600
    # the public worker carries it: the same comment as this job's own relay writes, read back from the chain
    for bound in (True, False):
        w = bounty(tmp_path, relay_key=False)
        if bound:
            w.chain.bind(MONA)
        push = w.hub.merge(12)
        assert flow.settle(w.run(push)) == 0
        assert only(w, 12) == (PAID if bound else HELD).replace("34 s", "39 s")
    # the worker's line says the chain refused
    w = bounty(tmp_path, relay_key=False)
    w.chain.bind(MONA)
    w.relay.refusals = [{"ok": False, "kind": "pay", "why": "no open job on this issue accepted the token"}]
    assert flow.settle(w.run(w.hub.merge(12))) == 1
    assert "but Solana did not take it: no open job on this issue accepted the token. Comment `/knos settle` to try again." in only(w, 12)


def test_a_push_says_nothing_about_a_pull_request_with_nothing_in_escrow_and_a_person_who_asks_is_answered(tmp_path, capsys):
    w = world(tmp_path)
    w.hub.pull(12, MONA, "Fixes #7")
    push = w.hub.merge(12)
    assert flow.settle(w.run(push)) == 0 and w.hub.knos(12) == [] and w.hub.wrote == []
    assert "Knos settle: nothing is in escrow for pull request #12, so there is nothing to pay." in capsys.readouterr().out
    assert flow.settle(w.run(w.hub.commented(12, EVE, "/knos settle"))) == 0
    assert only(w, 12) == "Knos: nothing to pay: no bounty is open on the issue this pull request closes (#7), and no tip waits for it."
    # a workflow_dispatch that names the pull request replays it
    w.hub.pull(13, MONA, "Refactor.")
    w.hub.merge(13)
    assert flow.settle(w.run({"inputs": {"pull": "13"}, "repository": w.hub.repo})) == 0
    assert only(w, 13) == ("Knos: nothing to pay: this pull request closes no issue (its description would say `Fixes #N`), and no tip "
                           "waits for it.")
    # a bounty already proven and held is said, with how its payee receives it
    w = bounty(tmp_path)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    assert flow.settle(w.run({"inputs": {"pull": "12"}, "repository": w.hub.repo})) == 0
    assert plain(w.hub.knos(12)[-1]) == (
        "Knos: nothing to pay: no bounty is open on the issue this pull request closes (#7), and no tip waits for it. The bounty on "
        f"issue #7 (20.00 {MONEY}) is already held for @mona until 2027-03-20 15:13 UTC: it is paid when they bind a wallet "
        "(`knos claim <their Solana address>` in a terminal, or https://drexthealpha.github.io/Knos/#claim in the browser).")
    # what a dispatch or a comment cannot settle is on the run's page
    capsys.readouterr()
    w.hub.pull(14, MONA, "Fixes #7")
    for event, code, line in (({"inputs": {"pull": "14"}}, 0, "Knos settle: pull request #14 is not merged. Its payment is tried once it is."),
                              ({"inputs": {"pull": "99"}}, 1, "Knos settle: GitHub did not answer for pull request #99."),
                              ({"inputs": {}}, 1, "Knos settle: this run names no pull request (the workflow_dispatch input `pull`)."),
                              (w.hub.commented(14, EVE, "thanks!"), 0, "Knos settle: this comment asks for no payment."),
                              (w.hub.commented(7, EVE, "/knos settle"), 0, "Knos settle: this comment asks for no payment.")):
        assert flow.settle(w.run({"repository": w.hub.repo, **event})) == code and line in capsys.readouterr().out
    assert w.hub.knos(14) == []


def test_only_what_a_push_to_the_default_branch_merged_is_settled(tmp_path, capsys):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    # GitHub ties a commit to its pull request a moment late: the head commit is asked again, briefly
    push = w.hub.merge(12)
    late = w.hub.brought.pop(push["after"])
    real = w.clock.sleep

    def sleep(seconds):
        real(seconds)
        w.hub.brought[push["after"]] = late
    w.clock.sleep = sleep
    assert flow.settle(w.run(push)) == 0 and only(w, 12).startswith("Knos: paid.") and w.clock.slept[-2] == 2
    # a push straight to the default branch, a push to another branch, a branch deleted: nothing to settle
    w = bounty(tmp_path)
    w.hub.merge(12)
    for push, code in ((w.hub.push([sha("direct")]), 0), (w.hub.push([w.hub.pulls[12]["merge_commit_sha"]], "refs/heads/release"), 0),
                       ({**w.hub.push([sha("x")]), "deleted": True, "after": "0" * 40}, 0)):
        assert flow.settle(w.run(push)) == code and w.hub.knos(12) == []
        assert "Knos settle: this push merged no pull request into the default branch." in capsys.readouterr().out
    # a commit of a pull request merged into another branch, or merged by an earlier push, is not this push's merge
    w.hub.pull(13, EVE, "Fixes #7", base="release")
    w.hub.pulls[13].update(merged_at=stamp(w.clock()), merge_commit_sha=sha("13-merge"))
    w.hub.brought[sha("13-merge")] = [13]
    w.hub.brought[sha("later")] = [12]                                                    # #12's merge commit is not in this push
    assert flow.settle(w.run(w.hub.push([sha("13-merge"), sha("later")]))) == 0 and w.signer.asked == [] and w.hub.wrote == []
    # GitHub not answering for the pushed commits: nothing is guessed, and the job fails so the run shows it
    w.hub.down = ("/pulls",)
    assert flow.settle(w.run(w.hub.push([w.hub.pulls[12]["merge_commit_sha"]]))) == 1
    assert "GitHub did not answer for every commit of this push" in capsys.readouterr().out and w.hub.wrote == []


def test_what_stands_in_the_way_is_said_with_what_would_change_it(tmp_path, monkeypatch):
    def settled(arrange, code=0, bought=BOUGHT) -> tuple[World, str]:
        w = bounty(tmp_path, bought)
        w.chain.bind(MONA)
        arrange(w)
        assert flow.settle(w.run(w.hub.merge(12))) == code and w.signer.asked[1:] == [] and len(w.chain.jobs(7)) == 1
        return w, only(w, 12)
    # a file the terms do not allow
    w, said = settled(lambda w: w.hub.files.update({12: [{"filename": "src/a.py"}, {"filename": ".github/workflows/ci.yml"}]}))
    assert "\n- changes `.github/workflows/ci.yml`, which this bounty does not allow (`.github/**`)\nA maintainer can pay this work anyway" in said
    w, said = settled(lambda w: w.hub.files.update({12: [{"filename": "docs/x.md"}]}), bought={**BOUGHT, "paths": ["src/**"]})
    assert "\n- changes `docs/x.md`, outside what this bounty covers (`src/**`)\n" in said
    w, said = settled(lambda w: setattr(w.hub, "down", ("/files",)), 1)
    assert said.startswith("Knos: nothing was decided about the bounty on issue #7") and "\n- the pull request's changed files could not be read from GitHub\n" in said
    # the terms themselves: not readable from the chain, not the ones the job was funded with, not Knos's
    w, said = settled(lambda w: w.chain.logs.clear(), 1)
    assert said == (f"Knos: nothing was decided about the bounty on issue #7 (20.00 {MONEY}): something could not be read, and nothing is "
                    "signed on a guess.\n- the bounty's terms could not be read from Solana\nNothing was paid. Comment `/knos settle` to try again.")
    w, said = settled(lambda w: w.chain.logs.update({str(JOB): terms.canonical({**BOUGHT, "checks": []})}), 1)
    assert "\n- the bounty's terms could not be read from Solana\n" in said             # the only line there is not the funded one
    plain_ledger = lambda w: setattr(w.chain, "log_of", lambda address, marker, real=w.chain.log_of: real(address, marker))  # noqa: E731
    w, said = settled(lambda w: (plain_ledger(w), w.chain.logs.update({str(JOB): terms.canonical({**BOUGHT, "checks": []})})), 1)
    assert "\n- the terms Solana gave are not the ones this job was funded with\n" in said   # a ledger that gives one line, unchecked
    w = bounty(tmp_path, b'{"anything":"a wallet wrote"}')
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and w.signer.asked == []
    assert "\n- its terms are not in a form Knos reads, so Knos cannot check it\n" in only(w, 12)
    # a bounty in tests mode is paid by its acceptance checks, not by the merge
    w, said = settled(lambda w: None, bought={**BOUGHT, "mode": "tests", "accept": "ab" * 32})
    assert ("\n- this bounty is paid by its acceptance checks (.knos/acceptance/7/), which Knos runs on a pull request before the merge; "
            "the merge itself does not pay it\n") in said
    # funded through another commit of Knos's workflows: only that commit's workflow can prove it
    w, said = settled(lambda w: setattr(w.signer, "wf_sha", "d" * 40))
    assert "\n- it was funded through Knos's workflows at commit `ccccccc`, and only a run at that commit is accepted for it; this run used `ddddddd`\n" in said
    assert f"Point this repository's workflow file at commit `{'c' * 40}` of Knos's workflows again. Then comment `/knos settle`." in said
    assert w.relay.submitted == []                                                         # signed, and not sent: the chain would refuse it
    # GitHub not signing; a deadline that has passed
    w, said = settled(lambda w: setattr(w.signer, "down", True), 1)
    assert "\n- GitHub did not sign the token (GitHub's token endpoint did not answer)\nNothing was paid. Comment `/knos settle` to try again." in said
    w, said = settled(lambda w: w.clock.sleep(15 * 86_400))
    assert "\n- its time ran out on 2026-10-05 14:13 UTC: the money goes back to where it came from\n" in said and "stays in escrow" not in said
    # a chain that does not answer: said on a pull request that closes an issue, and the job fails
    w, said = settled(lambda w: setattr(w.chain, "down", True), 1)
    assert said == ("Knos: Solana could not be read for issue #7, so whether anything is in escrow there is not known. Comment `/knos "
                    "settle` to try again.")
    # anything unforeseen after a person asked is told on the pull request
    w = bounty(tmp_path)
    w.hub.merge(12)
    monkeypatch.setattr(flow, "_record", lambda *a, **k: [][0])
    assert flow.settle(w.run(w.hub.commented(12, EVE, "/knos settle"))) == 1
    assert only(w, 12).startswith("Knos: this pull request's payment stopped before it was finished (") and "comment `/knos settle` to try again." in only(w, 12)


def test_two_jobs_on_one_issue_are_each_accounted_for_and_a_bad_one_never_stops_the_other(tmp_path, monkeypatch):
    # the same terms from two Balances: one proof pays both, and the comment says so
    w = bounty(tmp_path)
    w.chain.fund(7, 5_000_000, BOUGHT, source=key("wallet"), faucet=False)
    w.chain.bind(MONA)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    assert only(w, 12) == (f"Knos: paid. @mona received 24.375 {MONEY} for issue #7: the bounty (2 jobs) of 25.00 less Knos's fee of 0.625. "
                           f"It went to `{WALLET}`, the wallet bound to @mona's GitHub account ([transaction]({EXPLORER}/tx/sig2?cluster=devnet), "
                           "30 s after the merge).")
    assert len(w.signer.asked) == 1 and w.chain.jobs() == []
    # other terms on the second job: each gets its own decision, and the one that cannot be paid stays in escrow
    w = bounty(tmp_path)
    left = w.chain.fund(7, 5_000_000, {**BOUGHT, "checks": [{"app": 15368, "name": "lint"}]}, source=key("wallet"), faucet=False)
    w.chain.bind(MONA)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    parts = sorted(only(w, 12)[len("Knos: "):].split("\n\n"), key=str.lower)
    assert parts[0].lower().startswith(f"not paid. this pull request does not take the bounty on issue #7 (5.00 {MONEY.lower()}) as it stands;")
    assert "\n- `lint`: did not run on this commit\n" in parts[0]
    assert parts[1].lower().startswith(f"paid. @mona received 19.50 {MONEY.lower()} for issue #7: the bounty of 20.00 less")
    assert len(w.signer.asked) == 1 and [a for a, _j in w.chain.jobs()] == [str(left)]
    # two proofs, and the chain refuses the first: the second is still signed, carried and paid; the job fails so the run shows it
    w = bounty(tmp_path)
    w.chain.fund(7, 5_000_000, {**BOUGHT, "checks": []}, source=key("wallet"), faucet=False)
    w.chain.bind(MONA)
    w.relay.refusals = [{"ok": False, "kind": "pay", "why": "the cluster dropped the transaction"}]
    assert flow.settle(w.run(w.hub.merge(12))) == 1
    said = only(w, 12)
    assert "met its terms for @mona and GitHub signed the token, but Solana did not take it: the cluster dropped the transaction. " in said
    assert "aid. @mona received " in said and len(w.signer.asked) == 2 and len(w.chain.jobs(7)) == 1
    # and whatever breaks while one job is read or proven is that job's alone
    w = bounty(tmp_path)
    w.chain.fund(7, 5_000_000, {**BOUGHT, "checks": []}, source=key("wallet"), faucet=False)
    w.chain.bind(MONA)
    real, calls = flow._prove, []
    monkeypatch.setattr(flow, "_prove", lambda *a: [][0] if not calls.append(1) and len(calls) == 1 else real(*a))
    assert flow.settle(w.run(w.hub.merge(12))) == 1
    said = only(w, 12)
    assert "\n- its signed token could not be made (IndexError: list index out of range)\nNothing was paid. Comment `/knos settle` to try again." in said
    assert "aid. @mona received " in said and len(w.chain.jobs(7)) == 1


def test_a_crowd_of_jobs_from_strangers_wallets_neither_hides_nor_holds_up_the_bounty(tmp_path):
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    for i in range(30):        # anyone can fund a job on any issue from a wallet, each with terms of its own
        w.chain.fund(7, 30_000_000 + i, {**BOUGHT, "checks": [{"app": i + 1, "name": "never"}]}, source=key(f"stranger {i}"), faucet=False, kind=0)
    read = []
    real = w.chain.log_of
    w.chain.log_of = lambda address, marker, check=None: read.append(str(address)) or real(address, marker, check)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    parts = plain(w.hub.knos(12)[0], 9000).split("\n\n")
    # what this repository's own comment funded comes first and is paid; one run looks at twelve, and says how many it left
    assert parts[0] == PAID.replace("34 s", "30 s") and len(parts) == 13 and len(set(read)) == 12 and len(w.signer.asked) == 1
    assert all(x.startswith("Not paid. This pull request does not take the bounty on issue #7 (30.0000") for x in parts[1:12])
    assert parts[12] == ("19 more jobs wait on what this pull request closes and were not looked at: one run looks at 12, those funded "
                         "by this repository's own comments first, then the largest.")
    # `/knos status` on the issue lists as many, and says so
    w = bounty(tmp_path)
    for i in range(30):
        w.chain.fund(7, 30_000_000 + i, {**BOUGHT, "checks": []}, source=key(f"stranger {i}"), faucet=False, kind=0)
    assert flow.command(w.run(w.hub.commented(7, EVE, "/knos status"))) == 0
    parts = plain(w.hub.knos(7)[0], 9000).split("\n\n")
    assert parts[0].startswith(f"Knos: 20.00 {MONEY} is in escrow for issue #7 until ") and len(parts) == 13
    assert parts[12] == "19 more jobs on this issue are not listed: the smallest, each funded straight from a wallet."
    # and of the Balances any wallet can open for an owner, a bounded number is read: those already used first
    w = world(tmp_path)
    for i in range(40):
        w.chain.balance(f"empty {i}", 0)
    used = w.chain.balance("in use", 60_000_000, spent=5_000_000)
    looked, real = [], w.chain.account
    w.chain.account = lambda address: looked.append(str(address)) or real(address)
    assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 40 checks: none"))) == 0
    assert only(w, 7).startswith(f"Knos: 40.00 {MONEY} from the balance `{used}` is in escrow") and len(looked) <= flow.MAX_BALANCES + 2


def accept_of(files: dict) -> str:
    """The hash of an acceptance bundle, as knos.judge.checks_hash defines it."""
    return hashlib.sha256("".join(f"{name}\0{hashlib.sha256(text).hexdigest()}\n" for name, text in sorted(files.items())).encode()).hexdigest()


CHECKS = {"blackbox.sh": BLACKBOX}                 # a black-box bundle: the only kind whose checks alone pay
IMPORTING = {"test_slug.py": b"from slug import slug\n\n\ndef test_slug():\n    assert slug('a b') == 'a-b'\n"}
BY_TESTS = {**BOUGHT, "mode": "tests", "accept": accept_of(CHECKS)}


def judged(tmp_path, arrange=lambda w: None, **kw) -> tuple[World, str]:
    """Issue #7 funded with acceptance checks that are on the default branch, pull request #12 open with the funded
    checks passed, and its author's wallet bound: where things stand when the sandboxed judge has passed."""
    w = bounty(tmp_path, BY_TESTS, **kw)
    w.hub.bundles[7] = dict(CHECKS)
    w.chain.bind(MONA)
    arrange(w)
    return w, w.hub.pulls[12]["head"]["sha"]


def test_a_bounty_paid_by_acceptance_checks_is_signed_by_the_job_that_follows_the_judge(tmp_path, capsys):
    w, head = judged(tmp_path)
    merge_job = w.chain.fund(7, 5_000_000, BOUGHT, source=key("wallet"), faucet=False)     # paid on the merge: not this job's to sign
    assert flow.settle(w.run(w.hub.ran(12), GITHUB_SHA=sha("main")), tests=True, pull=12, head=head) == 0
    assert only(w, 12) == PAID.replace("34 s after the merge", "30 s after its acceptance checks passed")
    # mode 1, for the commit the judge passed; the pull request is still open, and the merge-mode job waits for the merge
    assert w.signer.asked == [pay.pay_audience(REPO_ID, 7, MONA["id"], head, pay.terms_hash(terms.canonical(BY_TESTS)), pay.TESTS)]
    assert w.hub.pulls[12]["state"] == "open" and [a for a, _j in w.chain.jobs()] == [str(merge_job)]
    assert f"repos/o/r/contents/.knos/acceptance?ref={sha('main')}" in w.hub.asked         # the commit the judge had as its base
    # everything else is read again as at a merge: an address when no wallet is bound, a maintainer's reject, the reservation
    w, head = judged(tmp_path, lambda w: (w.chain.accounts.pop(str(pay.bind_pda(MONA["id"]))), w.hub.say(12, MONA, f"/knos address {ADDRESS}")))
    assert flow.settle(w.run(w.hub.ran(12)), tests=True, pull=12, head=head) == 0
    assert f"It went to `{ADDRESS}`, the address in @mona's `/knos address` comment" in only(w, 12) and w.signer.asked[0].endswith(f":1:{ADDRESS}")
    w, head = judged(tmp_path, lambda w: w.hub.say(12, HUBOT, "/knos reject"))
    assert flow.settle(w.run(w.hub.ran(12)), tests=True, pull=12, head=head) == 0 and w.signer.asked == []
    assert "\n- @hubot rejected this pull request for the bounty\n" in only(w, 12)
    # a pull request that names two such issues: the one the judge ran (--issue) is the one signed for
    w, head = judged(tmp_path)
    w.hub.pulls[12]["body"] = "Fixes #7 and fixes #9"
    w.hub.issue(9)
    w.hub.bundles[9] = dict(CHECKS)
    w.chain.fund(9, 5_000_000, BY_TESTS)
    assert flow.settle(w.run(w.hub.ran(12)), tests=True, pull=12, head=head, issue=9) == 0
    assert [a.split(":")[3] for a in w.signer.asked] == ["9"] and [j.issue for _a, j in w.chain.jobs()] == [7]


def test_the_job_after_the_judge_signs_nothing_it_has_not_read_again_itself(tmp_path, capsys):
    def attest(arrange=lambda w: None, code=0, head=None, **env) -> tuple[World, list]:
        w, at = judged(tmp_path, arrange)
        capsys.readouterr()
        assert flow.settle(w.run(w.hub.ran(12), **env), tests=True, pull=12, head=head or at) == code
        assert w.signer.asked == [] and len(w.chain.jobs(7)) == 1                          # nothing signed, nothing moved
        return w, w.hub.knos(12)
    # the pull request has a newer commit than the one judged; it was closed without a merge: nothing to say on it
    w, said = attest(head=sha("judged-earlier"))
    assert said == [] and (f"Knos settle: pull request #12 is at commit `{sha('head-12')[:7]}` now, and its acceptance checks passed at "
                           f"`{sha('judged-earlier')[:7]}`, so nothing was signed. They run again for the new commit.") in capsys.readouterr().out
    w, said = attest(lambda w: w.hub.pulls[12].update(state="closed"))
    assert said == [] and "Knos settle: pull request #12 was closed without being merged, so nothing was signed." in capsys.readouterr().out
    # the acceptance checks on the default branch are no longer the ones the money was put on
    w, said = attest(lambda w: w.hub.bundles[7].update({"test_slug.py": b"def test_slug():\n    assert True\n"}))
    assert plain(said[0]) == (
        f"Knos: not paid. This pull request does not take the bounty on issue #7 (20.00 {MONEY}) as it stands; its checks are read at its "
        f"last commit (`{sha('head-12')[:7]}`).\n- `build`: passed\n- `test`: passed\n- the acceptance checks in .knos/acceptance/7/ on the "
        "default branch are not the ones this bounty was funded with\nA maintainer can pay this work anyway with `/knos tip <amount>` once "
        "it is merged. The money stays in escrow until 2026-10-05 14:13 UTC, then goes back to where it came from.")
    w, said = attest(lambda w: w.hub.bundles.clear())
    assert "\n- the acceptance checks in .knos/acceptance/7/ on the default branch are not the ones this bounty was funded with\n" in said[0]
    # the funded checks, unchanged, but not black-box (a job funded before that was asked, or a proof.toml that now
    # sends the bundle to another runner): its checks alone do not pay it, and no proof is signed
    def importing(w):
        job = w.chain.jobs(7)[0]
        w.chain.accounts.pop(str(job[0]))
        w.chain.fund(7, 20_000_000, {**BY_TESTS, "accept": accept_of(IMPORTING)}, at=job[1].not_before)
        w.hub.bundles[7] = dict(IMPORTING)
    w, said = attest(importing)
    assert plain(said[0]) == (
        f"Knos: not paid. This pull request does not take the bounty on issue #7 (20.00 {MONEY}) as it stands; its checks are read at its "
        f"last commit (`{sha('head-12')[:7]}`).\n- `build`: passed\n- `test`: passed\n- the acceptance checks in .knos/acceptance/7/ are "
        "not black-box (they load the pull request's code into the process that judges it), and a bounty is paid without a merge only by "
        "black-box checks\nA maintainer can pay this work anyway with `/knos tip <amount>` once it is merged. The money stays in escrow "
        "until 2026-10-05 14:13 UTC, then goes back to where it came from.")
    w, said = attest(lambda w: w.hub.contents.update({".knos/proof.toml": 'runner = "python"\n'}))
    assert ("\n- the acceptance checks in .knos/acceptance/7/ are not black-box (they share a process with the pull request's code "
            "(runner `python`)), and a bounty is paid without a merge only by black-box checks\n") in said[0]
    w, said = attest(lambda w: setattr(w.hub, "down", ("/contents/.knos/proof.toml",)), 1)
    assert "\n- the acceptance checks (.knos/acceptance/7/ on the default branch) could not be read from GitHub\n" in said[0]
    # GitHub not answering for them is not "they changed": nothing is decided, and the job fails
    w, said = attest(lambda w: setattr(w.hub, "down", ("/contents/.knos",)), 1)
    assert plain(said[0]).endswith("\n- the acceptance checks (.knos/acceptance/7/ on the default branch) could not be read from GitHub\n"
                                   "Nothing was paid. Run the `knos check` workflow again on this pull request to try again.")
    # the funded checks are held to as at a merge: one that failed at that commit, one still running after the wait
    w, said = attest(lambda w: w.hub.checks.update({w.hub.pulls[12]["head"]["sha"]: [check("build"), check("test", "failure")]}))
    assert ("\n- `test`: failed\nIf a check that did not pass is run again on that commit and passes, run the `knos check` workflow again "
            "on this pull request. A maintainer can pay") in plain(said[0])
    w, said = attest(lambda w: w.hub.checks.update({w.hub.pulls[12]["head"]["sha"]: [check("build"), check("test", None, status="queued")]}))
    assert plain(said[0]).endswith("\n- `test`: has not finished\nRun the `knos check` workflow again on this pull request when it has.")
    assert w.clock.slept.count(15) == 8
    # no bounty of that kind (it was paid, or it is paid on the merge); no pull request named; one GitHub does not know
    w = bounty(tmp_path)
    assert flow.settle(w.run(w.hub.ran(12)), tests=True, pull=12, head=w.hub.pulls[12]["head"]["sha"]) == 0 and w.hub.knos(12) == []
    assert ("Knos settle: no bounty paid by acceptance checks is open for an issue pull request #12 closes, so there was nothing to "
            "sign.") in capsys.readouterr().out
    assert flow.settle(w.run(w.hub.ran(12)), tests=True, head="a" * 40) == 1
    assert "Knos settle: --tests needs the pull request the judge passed (--pull) and its head commit (--head)." in capsys.readouterr().out
    assert flow.settle(w.run(w.hub.ran(12)), tests=True, pull=99, head="a" * 40) == 1
    assert "Knos settle: GitHub did not answer for pull request #99, so nothing was signed." in capsys.readouterr().out
    assert w.signer.asked == [] and w.hub.wrote == []


# ---- knos review -----------------------------------------------------------------------------------------------------

HEAD = sha("head-12")[:7]
REVIEW = f"""{flow.MARK}
Knos: this pull request takes the bounty on issue #7 (20.00 {MONEY}) when it is merged, as things stand.
- `build`: passed
- `test`: passed
It would pay @mona (the pull request's author). @mona gave no address: the bounty is held for them until they bind a wallet to their GitHub account. To be paid at the merge instead, they comment `/knos address <address>` on this pull request before it.

This is how things stood at commit `{HEAD}`. `/knos status` on this pull request says how they stand now."""


def test_the_review_is_one_comment_on_the_pull_request_edited_in_place_on_later_runs(tmp_path):
    w = bounty(tmp_path)
    assert flow.review(w.run(w.hub.ran(12))) == 0
    assert only(w, 12, ) == REVIEW
    first = w.hub.comments[12][0]["id"]
    assert w.signer.asked == [] and len(w.chain.jobs(7)) == 1                              # the same decision, and no token
    # the author gives an address, a check fails, and the description claims what GitHub's record contradicts
    w.hub.say(12, MONA, f"/knos address {ADDRESS}")
    w.hub.say(12, EVE, f"{flow.MARK}\nKnos: this is not Knos.")                           # a person's comment is never the one edited
    w.hub.pulls[12]["body"] = "Fixes #7. All tests pass."
    w.hub.checks[w.hub.pulls[12]["head"]["sha"]] = [check("build", None, status="queued"), check("test", "failure")]
    assert flow.review(w.run(w.hub.ran(12))) == 0
    assert [c["id"] for c in w.hub.comments[12] if c["user"] == BOT] == [first] and w.hub.wrote[-1] == f"repos/o/r/issues/comments/{first}"
    assert only(w, 12) == f"""{flow.MARK}
Knos: this pull request does not take the bounty on issue #7 (20.00 {MONEY}) as it stands.
- `build`: has not finished
- `test`: failed
It would pay @mona (the pull request's author) at `{ADDRESS}`, the address in their `/knos address` comment.
A check that failed needs a new commit that passes it.

This is held against the pull request, bounty or not:
- the description says tests pass, but these checks failed at the head commit: test

This is how things stood at commit `{HEAD}`. `/knos status` on this pull request says how they stand now."""
    assert w.hub.comments[12][2]["body"].endswith("this is not Knos.")
    # `/knos status` on the pull request says the same, as it stands now (it is how the check is read without the check workflow)
    assert flow.command(w.run(w.hub.commented(12, MONA, "/knos status"))) == 0
    assert plain(w.hub.knos(12)[-1]) == only_text(w.hub.knos(12)[0])
    # the pull request moved on to a newer commit: the old run's review is not written over the new state
    old = w.hub.ran(12)
    w.hub.pulls[12]["head"]["sha"] = sha("newer")
    before = w.hub.comments[12][0]["body"]
    assert flow.review(w.run(old)) == 0 and w.hub.comments[12][0]["body"] == before
    assert flow.review(w.run({"workflow_run": {"event": "push", "head_sha": sha("main")}, "repository": w.hub.repo})) == 0


def only_text(review: str) -> str:
    """A review comment without its marker and the line that says which commit it was written at."""
    return "\n".join(review.split("\n")[1:]).rsplit("\n\n", 1)[0]


def test_the_review_says_who_would_be_paid_and_what_a_description_meant(tmp_path):
    # an agent's pull request: nobody yet, and what to type; a wallet already bound; an issue someone else holds
    w = bounty(tmp_path, author=DEVIN, body="Fixes #7\n\nRequested by: @mona")
    assert flow.review(w.run(w.hub.ran(12))) == 0
    said = only(w, 12)
    assert said.startswith(f"{flow.MARK}\nKnos: this pull request does not take the bounty on issue #7 (20.00 {MONEY}) as it stands.\n")
    assert ("\n- devin-ai-integration[bot] is a bot account, and nothing GitHub authenticates names the person who ran it\nA maintainer "
            "comments `/knos pay @mona` on this pull request.\n") in said
    w.hub.say(12, HUBOT, "/knos pay @mona")
    w.chain.bind(MONA)
    assert flow.review(w.run(w.hub.ran(12))) == 0
    assert (f"\nIt would pay @mona (maintainer @hubot named them with `/knos pay`) at `{WALLET}`, the wallet bound to their GitHub "
            "account. (Its text names @mona, which is a hint and decides nothing.)\n") in only(w, 12)
    w = bounty(tmp_path)
    w.hub.issues[7]["assignees"] = [EVE]
    w.hub.events[7] = [{"event": "assigned", "assignee": EVE, "assigner": BOT, "created_at": stamp(w.clock())}]
    assert flow.review(w.run(w.hub.ran(12))) == 0
    assert ("\n- issue #7 is assigned to @eve until 2026-09-28 15:13 UTC; only an assignee's pull request is paid for it\nA maintainer can "
            "change the issue's assignee; a `/knos take` lapses on the date shown.\n") in only(w, 12)
    # a description that names a funded issue without closing it: the author is told what to write
    w = bounty(tmp_path, body="Part of #7, see also #99.")
    assert flow.review(w.run(w.hub.ran(12))) == 0
    assert only(w, 12) == (f"{flow.MARK}\nKnos: This mentions funded issue #7 but does not close it. If this pull request is for that "
                           f"bounty, write `Fixes #7` in its description.\n\nThis is how things stood at commit `{HEAD}`. `/knos status` "
                           "on this pull request says how they stand now.")
    # it writes `Fixes #7`; a pull request that takes no bounty and has nothing against it is not written on at all
    w.hub.pulls[12]["body"] = "Fixes #7."
    assert flow.review(w.run(w.hub.ran(12))) == 0 and only(w, 12).startswith(f"{flow.MARK}\nKnos: this pull request takes the bounty on issue #7")
    w.hub.pull(13, EVE, "Refactor the parser.")
    assert flow.review(w.run(w.hub.ran(13))) == 0 and w.hub.knos(13) == []
    # a comment from an earlier run is brought up to date when the bounty is gone
    w.chain.accounts.clear()
    assert flow.review(w.run(w.hub.ran(12))) == 0
    assert only(w, 12).startswith(f"{flow.MARK}\nKnos: this pull request takes no bounty now: it closes no funded issue, and nothing is held against it.")


def test_a_forks_pull_request_is_found_by_its_head_and_a_review_that_cannot_be_written_fails_the_job(tmp_path, capsys):
    w = bounty(tmp_path)
    w.hub.pull(12, MONA, "Fixes #7", fork="mona")                                          # the run names no pull request for a fork
    w.hub.checks[w.hub.pulls[12]["head"]["sha"]] = [check("test"), check("build")]
    w.hub.pull(13, EVE, "Fixes #7", head=w.hub.pulls[12]["head"]["sha"], fork="eve")       # the same commit, in someone else's fork
    assert flow.review(w.run(w.hub.ran(12))) == 0
    assert only(w, 12).startswith(f"{flow.MARK}\nKnos: this pull request takes the bounty on issue #7") and w.hub.knos(13) == []
    assert any(p.startswith("repos/o/r/pulls?state=open&head=mona%3Afix-12") for p in w.hub.asked)
    w.hub.readonly = True
    w.hub.comments[12].clear()
    capsys.readouterr()
    assert flow.review(w.run(w.hub.ran(12))) == 1
    assert "GitHub did not take this comment on #12 (HTTP Error 403: Resource not accessible by integration):" in capsys.readouterr().out


def test_what_the_review_learned_is_kept_in_the_knos_memory_issue_and_held_against_the_next_pull_request(tmp_path):
    w = World(tmp_path)
    w.hub.contents["CONTRIBUTING.md"] = "# Rules\n\n- Do not leave print() debug statements in code.\n"
    w.hub.pull(12, DEVIN, "Adds mul.")
    w.hub.files[12] = [{"filename": "calc.py", "patch": "@@ -1,2 +1,4 @@\n def add(a, b):\n     return a + b\n+def mul(a, b):\n+    print(a, b)"}]
    assert flow.review(w.run(w.hub.ran(12))) == 0
    assert only(w, 12) == (
        f"{flow.MARK}\nKnos: this is held against the pull request, bounty or not:\n- calc.py:4: 'print(a, b)' breaks CONTRIBUTING.md:3 "
        f"('- Do not leave print() debug statements in code.'): a debug print\n\nThis is how things stood at commit `{HEAD}`. `/knos "
        "status` on this pull request says how they stand now.")
    n, lessons = memory.read(REPO, w.hub)                                                  # one issue, opened by the workflow's own token
    assert w.hub.issues[n]["title"] == "Knos memory" and sorted(x["category"] for x in lessons) == ["proof_rule", "proof_rule", "tamper"]
    assert "in run 77" in w.hub.comments[n][0]["body"]
    # a later run, on a fresh runner, for another pull request by the same agent: the rule is required of it, CONTRIBUTING or not
    del w.hub.contents["CONTRIBUTING.md"]
    w.hub.pull(20, DEVIN, "Adds div.")
    w.hub.files[20] = [{"filename": "calc.py", "patch": "@@ -1,2 +1,4 @@\n def add(a, b):\n     return a + b\n+def div(a, b):\n+    print(a, b)"}]
    assert flow.check(w.run({"action": "opened", "pull_request": w.hub.pulls[20], "repository": w.hub.repo})) == 1
    assert flow.review(w.run(w.hub.ran(20))) == 0
    assert "- calc.py:4: 'print(a, b)' breaks history ('tamper:rule:no_debug required by history'): a debug print" in only(w, 20)
    assert [len(memory.lessons_in(c["body"])) for c in w.hub.comments[n]] == [3, 1]        # only what is new is posted: this catch
    # without the memory the same pull request passes: the issue is what remembers between runs
    w.hub.issues[n]["state"] = "closed"
    assert flow.check(w.run({"action": "opened", "pull_request": w.hub.pulls[20], "repository": w.hub.repo})) == 0


def test_a_bounty_in_tests_mode_hands_the_sandboxed_judge_what_it_needs(tmp_path):
    w, head = judged(tmp_path)
    run = w.run(w.hub.ran(12), GITHUB_OUTPUT=str(tmp_path / "out.txt"))
    assert flow.review(run) == 0
    assert only(w, 12).startswith(f"{flow.MARK}\nKnos: this pull request takes the bounty on issue #7 (20.00 {MONEY}) when its acceptance "
                                  "checks pass, as things stand.\n- `build`: passed\n- `test`: passed\nIt would pay @mona")
    # for the workflow's next jobs, through $GITHUB_OUTPUT: which issue, which pull request at which commit, and the
    # terms on one line, byte for byte what was funded (the judge job writes them to a file for `knos proof judge --terms`)
    raw = terms.canonical(BY_TESTS).decode()
    assert run.outputs == {"tests": "7", "issue": "7", "pull": "12", "head": head, "terms": raw} and terms.parse(run.outputs["terms"]) == BY_TESTS
    assert (tmp_path / "out.txt").read_text(encoding="utf-8").splitlines() == ["tests=7", "issue=7", "pull=12", f"head={head}", f"terms={raw}"]
    assert w.signer.asked == [] and len(w.chain.jobs(7)) == 1                              # the review signs nothing
    # a bounty paid on the merge names no judge; nor does one whose terms could not be read
    w = bounty(tmp_path)
    run = w.run(w.hub.ran(12))
    assert flow.review(run) == 0 and run.outputs == {}
    w, head = judged(tmp_path, lambda w: w.chain.logs.clear())
    run = w.run(w.hub.ran(12))
    assert flow.review(run) == 0 and run.outputs == {}


# ---- knos check ------------------------------------------------------------------------------------------------------

PASSED = "**Passed**: no false claim and no broken rule."
TAKES = PASSED + " Whether this pull request takes a bounty never fails this check."
FAILED = "**Failed**: a claim in the description is false, or a rule of this repository is broken (listed above)."


def checked(w: World, n: int = 12, **env) -> tuple[int, str]:
    """Run `knos check` on pull request `n` as its pull_request event; (exit status, the job's summary)."""
    summary = w.tmp / "summary.md"
    summary.unlink(missing_ok=True)
    code = flow.check(w.run({"action": "synchronize", "pull_request": w.hub.pulls[n], "repository": w.hub.repo}, GITHUB_STEP_SUMMARY=str(summary), **env))
    return code, summary.read_text(encoding="utf-8")


def test_the_check_on_a_fork_reads_everything_and_writes_nothing(tmp_path):
    w = bounty(tmp_path)
    w.hub.pull(12, MONA, "Fixes #7", fork="mona")
    w.hub.checks[w.hub.pulls[12]["head"]["sha"]] = [check("test"), check("build")]
    w.hub.readonly = True                                                                  # a fork's token: any write is a 403
    before = dict(w.chain.accounts)
    code, summary = checked(w)
    assert code == 0 and summary == f"""### Knos check

This pull request takes the bounty on issue #7 (20.00 {MONEY}) when it is merged, as things stand.
- `build`: passed
- `test`: passed

{TAKES}

"""
    assert w.hub.wrote == [] and w.signer.asked == [] and w.chain.accounts == before and w.hub.knos(12) == []
    assert not any("collaborators" in p or "/issues/12/comments" in p for p in w.hub.asked)   # who is paid is the review's to say
    # a pull request for an issue that is not funded, with nothing wrong: that is never a failure
    w.hub.pull(13, EVE, "Refactor the parser. Fixes #3", fork="eve")
    assert checked(w, 13) == (0, f"### Knos check\n\nThis pull request closes no funded issue, and nothing is held against it.\n\n{PASSED}\n\n")
    assert flow.check(w.run({"action": "created", "issue": w.hub.issues[7]})) == 0         # not a pull request's event: nothing to check


def test_the_check_fails_only_for_a_false_claim_or_a_broken_rule(tmp_path, monkeypatch):
    def world_with(runs, body="Fixes #7", files=None, bought=BOUGHT) -> World:
        w = bounty(tmp_path, bought, body=body)
        w.hub.checks[w.hub.pulls[12]["head"]["sha"]] = runs
        if files:
            w.hub.files[12] = files
        w.hub.readonly = True
        return w
    # what keeps a pull request from a bounty is said and never fails the check: a required check that failed or was
    # skipped (it is red on the pull request already), a file the terms do not allow
    for run_, row in ((check("test", "failure"), "- `test`: failed"), (check("test", "skipped"), "- `test`: was skipped, which does not count as passing")):
        code, summary = checked(world_with([check("build"), run_]))
        assert code == 0 and row in summary and summary.endswith(TAKES + "\n\n")
        assert "This pull request does not take the bounty on issue #7" in summary
    code, summary = checked(world_with([check("build"), check("test")], files=[{"filename": ".knos/acceptance/7/test_x.py"}]))
    assert code == 0 and "- changes `.knos/acceptance/7/test_x.py`, which this bounty does not allow (`.knos/**`)" in summary
    assert "Take the files it may not change out of the pull request." in summary
    # nor does what is not known yet: a check that has not run, one still running after the wait, GitHub or Solana unreadable
    code, summary = checked(world_with([check("build")]))
    assert code == 0 and "- `test`: did not run on this commit" in summary and summary.endswith(TAKES + "\n\n")
    w = world_with([check("build"), check("test", None, status="in_progress")])
    code, summary = checked(w)
    assert code == 0 and "- `test`: has not finished" in summary and w.clock.slept.count(15) == 40      # ten minutes, so the review sees the end
    w = world_with([check("build"), check("test")])
    w.hub.down = ("/check-runs",)
    code, summary = checked(w)
    assert code == 0 and "- `test`: could not be read from GitHub" in summary and "not known yet: something could not be read" in summary
    w = world_with([check("build"), check("test")])
    w.chain.down = True
    code, summary = checked(w)
    assert code == 0 and "Solana could not be read for issue #7, so whether anything is in escrow there is not known." in summary
    # a false claim fails it: the description says what a finished check contradicts, whatever the bounty requires
    w = world_with([check("build"), check("test"), check("lint", "failure")], body="Fixes #7. CI is green.")
    code, summary = checked(w)
    assert code == 1 and "This pull request takes the bounty on issue #7" in summary                    # the bounty did not buy `lint`
    assert "This is held against the pull request, bounty or not:\n- the description says CI is green, but these checks failed at the head commit: lint" in summary
    assert summary.endswith(FAILED + "\n\n")
    # a broken rule of the repository fails it, funded or not
    w = world_with([check("build"), check("test")], files=[{"filename": "a.py", "patch": "@@ -1,1 +1,2 @@\n x = 1\n+print(x)"}])
    w.hub.contents["CONTRIBUTING.md"] = "# Rules\n\n- Do not leave print() debug statements in code.\n"
    code, summary = checked(w)
    assert code == 1 and "- a.py:2: 'print(x)' breaks CONTRIBUTING.md:3" in summary and summary.endswith(FAILED + "\n\n")
    # a claim made while the other checks still run is waited for, and one that cannot be checked is not held against it
    w = world_with([check("build"), check("test"), check("slow", None, status="queued")], body="Fixes #7. All tests pass.")
    real = w.clock.sleep

    def sleep(seconds):
        real(seconds)
        if w.clock.slept.count(15) == 3:
            w.hub.checks[w.hub.pulls[12]["head"]["sha"]][2] = check("slow", "failure")
    w.clock.sleep = sleep
    code, summary = checked(w)
    assert code == 1 and w.clock.slept.count(15) == 3 and "but these checks failed at the head commit: slow" in summary
    w = bounty(tmp_path, body="Fixes #7. All tests pass.")
    w.hub.checks[w.hub.pulls[12]["head"]["sha"]] = []
    code, summary = checked(w)
    assert code == 0 and "The description claims tests pass; GitHub has no check runs for this commit." in summary
    # Knos's own failure is never the pull request's
    w = world_with([check("build"), check("test")])
    monkeypatch.setattr(flow, "_record", lambda *a, **k: [][0])
    code, summary = checked(w)
    assert code == 0 and summary.startswith("Knos check: stopped before it was finished (") and "Nothing is held against this pull request." in summary


def test_the_check_tells_a_description_that_mentions_a_funded_issue_without_closing_it(tmp_path):
    w = bounty(tmp_path, body="Works towards #7 and o/r#9; unrelated to #5 and https://github.com/o/r/issues/11.")
    w.hub.issue(9)
    w.chain.fund(9, 5_000_000, BOUGHT)
    w.hub.readonly = True
    code, summary = checked(w)
    assert code == 0 and summary == (
        "### Knos check\n\nThis mentions funded issues #7, #9 but does not close them. If this pull request is for those bounties, write "
        f"`Fixes #7` in its description.\n\n{TAKES}\n\n")


# ---- what the commands share -------------------------------------------------------------------------------------------

def test_mint_asks_github_for_this_runs_token_with_one_audience(monkeypatch):
    import urllib.request
    seen = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        seen.append((req.full_url, dict(req.header_items())))
        return Answer(b'{"value": "a.b.c", "count": 1}' if "good" in req.full_url else b"<html>" if "html" in req.full_url else b'{"value": 7}')
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    env = {"ACTIONS_ID_TOKEN_REQUEST_URL": "https://good.actions.githubusercontent.com/t?api-version=2.0", "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "s3cret"}
    audience = pay.fund_audience(7, 20_000_000, 0, bytes(32), FAUCET)
    assert flow.mint(audience, env) == "a.b.c"
    url, headers = seen[-1]
    assert url == f"https://good.actions.githubusercontent.com/t?api-version=2.0&audience=knos2%3Afund%3A7%3A20000000%3A0%3A{'00' * 32}%3A1209600%3A{FAUCET}"
    assert headers["Authorization"] == "bearer s3cret"
    for bad in ("https://html.example/t", "https://other.example/t"):                      # not JSON; JSON without a token
        with pytest.raises(OSError, match="GitHub's answer held no token"):
            flow.mint(audience, {**env, "ACTIONS_ID_TOKEN_REQUEST_URL": bad})
    assert seen[-1][0].startswith("https://other.example/t?audience=knos2%3Afund")
    # a job without `id-token: write` (every fork's pull_request run) says so, and asks nobody
    asked = len(seen)
    with pytest.raises(OSError, match="id-token: write"):
        flow.mint(audience, {})
    assert len(seen) == asked
    assert flow.Run(REPO, {}, env=env).mint(audience) == "a.b.c"                           # a Run without a signer of its own uses this


# ---- the five states: one comment, posted at "received" and edited as the payment moves ---------------------------------------

def _watched(w: World, events: list | None = None) -> list[tuple[str, str, float]]:
    """Every write of a comment on #12 from here on, in order: (POST or PATCH, the comment's words, the clock). Each is
    also noted in `events`, by its first two words, among whatever else the test notes there."""
    seen, github = [], w.hub.__call__

    class Watching(type(w.hub)):
        def __call__(self, path, data=None, method=None):
            if data is not None and ("/issues/12/comments" in path or method == "PATCH") and not str(data.get("body", "")).startswith("knos-"):
                seen.append((method or "POST", data["body"], w.clock()))
                if events is not None:
                    events.append(" ".join(data["body"].split()[:2]))
            return github(path, data, method)
    w.hub.__class__ = Watching
    return seen


def test_a_settlement_is_one_comment_posted_at_received_and_edited_through_the_five_states(tmp_path):
    """The merge is answered before anything is decided, "accepted" is said before the token goes to the chain, and
    the same comment ends as the payment with the time of each state. A fake GitHub, a fake chain, a fake clock."""
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    order: list = []
    writes, submit, sign = _watched(w, order), w.relay.submit, w.signer.__call__
    w.relay.submit = lambda *a, **k: (order.append("the relay sends"), submit(*a, **k))[1]         # the first call that sends anything to the chain

    class Signing(type(w.signer)):
        def __call__(self, audience):
            order.append("GitHub signs")
            return sign(audience)
    w.signer.__class__ = Signing
    w.chain.finalized = lambda sig, within: (order.append(("finalized", sig, within)), w.clock.sleep(13))[0] is None       # the cluster finalizes 13 s later
    merged = w.hub.merge(12)
    w.clock.sleep(4)                                                    # GitHub took 4 s to start the runner: nobody controls that
    assert flow.settle(w.run(merged)) == 0
    # ONE comment of Knos's on the pull request: one POST, then edits of that comment and nothing else
    assert [m for m, _b, _t in writes] == ["POST", "PATCH", "PATCH", "PATCH"] and len(w.hub.knos(12)) == 1
    received, accepted, paid, final = (b for _m, b, _t in writes)
    assert received.startswith("Knos: received. Pull request #12 is being checked against what was funded for it.")
    assert accepted.startswith(f"Knos: accepted, settling. Everything the bounty on issue #7 (20.00 {MONEY}) asks for holds at this pull request's "
                               "last commit and GitHub signed this run. The payment to @mona is on its way to Solana")
    assert only(w, 12) == PAID and paid.startswith("Knos: paid. @mona received 19.50")
    for words in (received, accepted):                                  # neither reads as a payment to a program that waits for one (the canary, the site)
        assert plain(words.split("\n\n" + flow.STATUS)[0]) and not any(mark in words for mark in ("paid.", "held for", "not paid", "nothing to pay", "stopped"))
    # "received" before anything is signed; "accepted" once GitHub signed and BEFORE the first call that sends to the
    # chain; the payment when it confirmed; finality last, in the same comment
    assert order == ["Knos: received.", "GitHub signs", "Knos: accepted,", "the relay sends", "Knos: paid.", ("finalized", "sig2", flow.FINAL_WAIT), "Knos: paid."]
    assert [b.count("accepted ") for b in (received, accepted)] == [0, 1] and "submitted" not in accepted and "confirmed" not in accepted
    # each state with its time: received when the job began (4 s after the merge), accepted at once, submitted when the
    # relay sent, confirmed 30 s later when the payment landed, finalized 13 s after that
    t = T0 + 3600
    assert w.hub.states(12) == {"since": t, "received": t + 4, "accepted": t + 4, "submitted": t + 4, "confirmed": t + 34, "finalized": t + 47}
    assert "tx=sig2" in final
    line = final.split(flow.STATUS)[1]
    assert ("<sub>received 15:13:24 UTC (+4 s) · accepted 15:13:24 UTC (+4 s) · submitted 15:13:24 UTC (+4 s) · confirmed 15:13:54 UTC (+34 s) · "
            "finalized 15:14:07 UTC (+47 s); seconds are counted from the merge.</sub>") in line
    assert "finalized" not in paid and "confirmed 15:13:54 UTC" in paid                 # the payment is said as soon as it confirmed; finality is added after
    # the relay's own log line travels in the comment, with the four times the public worker's line carries
    logged = re.search(r"^knos-relay proof o/r#12 [0-9a-f]{16} ok sig=sig1,sig2 queued_at=(\S+) seen_at=(\S+) sent_at=(\S+) confirmed_at=(\S+) note=", final, re.M)
    assert logged and [float(x) for x in logged.groups()] == [t + 4, t + 4, t + 4, t + 34]
    assert len(final) < 2500                                            # far under GitHub's 65,536 characters, whatever the round


def test_the_states_follow_the_public_workers_line_and_a_refusal_ends_in_the_same_comment(tmp_path):
    # no relay key: the token is posted under the comment, and the worker's line says when it sent and when it confirmed
    w = bounty(tmp_path, relay_key=False)
    w.chain.bind(MONA)
    wait = w.worker.wait_for

    def line(tid, *a, **k):         # the worker's line as 0.3.16 writes it: its four times, on its own clock
        said = wait(tid, *a, **k)
        return said.replace(" note=", f" queued_at={w.clock() - 39:.1f} seen_at={w.clock() - 2:.1f} sent_at={w.clock() - 1:.1f} confirmed_at={w.clock():.1f} note=")
    w.worker.wait_for = line
    writes = _watched(w)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    t = T0 + 3600
    assert [m for m, _b, _t in writes] == ["POST", "PATCH", "PATCH"] and only(w, 12).startswith("Knos: paid. @mona received 19.50")
    assert w.hub.states(12) == {"since": t, "received": t, "accepted": t, "submitted": t + 38, "confirmed": t + 39}       # this chain has no word on finality: no state is claimed
    assert [c["body"][:11] for c in w.hub.comments[12] if c["user"] == BOT] == ["Knos: paid.", "knos-proof:"]             # the token under the one comment
    # a pull request that does not take the bounty: received, then the refusal, in one comment, and no state it did not reach
    w = bounty(tmp_path)
    head = w.hub.pulls[12]["head"]["sha"]
    w.hub.checks[head] = [check("test", "failure"), check("build")]
    writes = _watched(w)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    assert [m for m, _b, _t in writes] == ["POST", "PATCH"] and only(w, 12) == REFUSED and set(w.hub.states(12)) == {"since", "received"}
    assert w.signer.asked == [] and w.relay.submitted == []
    # GitHub will not let the job edit: the last words are a comment of their own, as before, and nothing is lost
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    github = w.hub.__call__

    class NoEdits(type(w.hub)):
        def __call__(self, path, data=None, method=None):
            if method == "PATCH":
                raise OSError("403 Resource not accessible by integration")
            return github(path, data, method)
    w.hub.__class__ = NoEdits
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    assert [plain(x)[:14] for x in w.hub.knos(12)] == ["Knos: received", "Knos: paid. @m"]
    # a push that merged a pull request with nothing in escrow says nothing at all, as before
    w = world(tmp_path)
    w.hub.pull(12, MONA, "Fixes #7")
    assert flow.settle(w.run(w.hub.merge(12))) == 0 and w.hub.knos(12) == []


def test_deliver_gives_one_shape_whoever_relays(tmp_path):
    def detail(r: dict) -> dict:
        return {k: v for k, v in r.items() if k not in ("sigs", "seconds", "note", "why", "times", "line")}
    raw = terms.canonical(BOUGHT)
    results = {}
    for relay_key in (True, False):
        w = world(tmp_path, relay_key=relay_key)
        run = w.run({})
        fund = flow.deliver("fund", w.signer(pay.fund_audience(7, 20_000_000, 0, pay.terms_hash(raw), FAUCET)), 7, raw, run=run, since=T0 - 5)
        w.chain.bind(MONA)
        paid = flow.deliver("proof", w.signer(pay.pay_audience(REPO_ID, 7, MONA["id"], "a" * 40, pay.terms_hash(raw), 0)), 12, run=run)
        again = flow.deliver("proof", w.signer(pay.pay_audience(REPO_ID, 7, MONA["id"], "a" * 40, pay.terms_hash(raw), 0)), 12, run=run)
        results[relay_key] = (fund, paid, again)
        # what every caller gets, whoever relayed: ok, why, sigs, note, seconds
        for r in (fund, paid, again):
            assert {"ok", "why", "sigs", "note", "seconds", "kind"} <= set(r) and isinstance(r["sigs"], list) and isinstance(r["seconds"], int)
        assert fund["ok"] and fund["why"] == "" and fund["seconds"] == (35 if relay_key else 44) and paid["ok"] and len(paid["sigs"]) == 2
        assert paid["seconds"] == (30 if relay_key else 39)                                # with no `since`: how long the carrying took
        assert again == {"ok": False, "kind": "pay", "why": "no open job on this issue accepted the token", "sigs": [], "note": "",
                         "seconds": again["seconds"]}
    (fund, paid, _), (fund2, paid2, _) = results[True], results[False]
    assert fund["note"] == f"job {JOB} holds 20.00 for #7" and paid["note"] == "1 paid, 0 held for #7"
    assert fund2["note"] == paid2["note"] == "relayed by the worker"                       # the worker's own words, without its t= field
    assert fund2.pop("deadline") == fund.pop("deadline") + 9 == int(T0) + 14 * 86_400 + 39    # the worker's pass came 9 seconds later
    assert detail(fund) == detail(fund2) == {"ok": True, "kind": "fund", "job": str(JOB), "repo_id": REPO_ID, "issue": 7, "amount": 20_000_000,
                                             "mode": 0, "faucet": True, "balance": str(FAUCET)}
    assert detail(paid) == detail(paid2) == {"ok": True, "kind": "pay", "repo_id": REPO_ID, "issue": 7, "payee_id": MONA["id"], "head": "a" * 40,
                                             "paid": [{"job": str(JOB), "amount": 20_000_000, "fee": 500_000, "mint": str(pay.faucet_mint()),
                                                       "to": WALLET, "held_until": None}]}
    # a relay that breaks, a line that is not the worker's, a token GitHub will not let be posted: an answer, never an exception
    w = world(tmp_path)
    w.relay.submit = lambda *a, **k: 1 / 0
    assert flow.deliver("fund", "x.y.z", 7, raw, run=w.run({}))["why"] == "ZeroDivisionError: division by zero"
    w = world(tmp_path, relay_key=False)
    w.worker.wait_for = lambda tid, *a, **k: f"some other line about {tid}"
    got = flow.deliver("fund", "x.y.z", 7, raw, run=w.run({}))
    assert not got["ok"] and got["why"].startswith("the relay's log line was not understood: some other line about ")
    w.hub.readonly = True
    assert "HTTP Error 403" in flow.deliver("fund", "x.y.z", 7, raw, run=w.run({}))["why"]
    # an outcome the chain already showed (`already`: nothing had to be sent) is an ok answer, with no transaction to name
    w = world(tmp_path)
    w.relay.refusals = [{"ok": True, "kind": "pay", "already": True, "sigs": [], "repo_id": REPO_ID, "issue": 7, "payee_id": 4242, "head": "a" * 40, "paid": []}]
    got = flow.deliver("proof", "x.y.z", 12, run=w.run({}))
    assert got["ok"] and got["already"] and got["sigs"] == [] and got["why"] == ""
    # the worker's line, as its log writes it
    assert flow._verdict("knos-relay proof o/r#12 abc ok sig=s1,s2 note=paid 19.50 to mona (another relayer carried it first) t=41", "pay", "abc") == \
        {"ok": True, "kind": "pay", "sigs": ["s1", "s2"], "note": "paid 19.50 to mona (another relayer carried it first)"}
    assert flow._verdict("knos-relay fund o/r#7 abc ok sig=none note=nothing to do", "fund", "abc")["sigs"] == []
    assert flow._verdict("knos-relay fund o/r#7 abc fail the balance does not hold that much", "fund", "abc") == \
        {"ok": False, "kind": "fund", "why": "the balance does not hold that much"}


def test_the_real_doors_have_the_shapes_the_fakes_stand_in_for():
    """knos.flow reaches the chain, the relay and the worker through names another worktree builds. What exists here
    is held to the shape the fakes have; what does not exist yet is held to it as soon as it does."""
    import importlib
    import inspect

    from knos import chain
    from knos.proof import ghrelay

    def names(f) -> list[str]:
        return [n for n in inspect.signature(f).parameters if n != "self"]
    assert names(chain.Ledger.account) == ["address"] and names(chain.Ledger.now) == []
    assert names(chain.Ledger.program_accounts)[:3] == ["program", "size", "memcmp"]
    assert callable(chain.ledger) and callable(chain.key)
    world = World(None)
    assert ghrelay.token_id("a.b.c") == world.worker.token_id("a.b.c") and ghrelay.MARK == flow.WORD
    if hasattr(chain.Ledger, "log_of"):      # (address, marker), and a check of the line where the ledger offers one
        assert names(chain.Ledger.log_of)[:2] == ["address", "marker"] and names(chain.Ledger.log_of)[2:] in ([], ["check"], ["check", "by"])
        assert names(world.chain.log_of) == ["address", "marker", "check"]
    if hasattr(ghrelay, "wait_for"):
        assert names(ghrelay.wait_for) == ["token_id", "log_repo", "timeout", "every", "get"]
        assert inspect.signature(ghrelay.wait_for).parameters["every"].default == 3.0
    try:
        relay = importlib.import_module("knos.settle.v2.relay")
    except ImportError:
        return
    assert names(relay.submit) == ["ledger", "payer", "jwt", "terms", "jwks", "now"] == names(world.relay.submit)


def test_github_is_reached_through_one_function_that_rewrites_only_two_things(monkeypatch):
    import urllib.request
    seen = []

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        seen.append((req.get_method(), req.full_url, req.data, dict(req.header_items())))
        return Answer(b'{"ok": true}')
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert judge.github("repos/o/r/commits/abc/pulls?per_page=100") == {"ok": True}
    assert seen[-1][0] == "GET" and seen[-1][3]["X-github-api-version"] == "2022-11-28"
    assert judge.github("repos/o/r/issues/comments/55", {"body": "x"}, "PATCH") == {"ok": True}
    assert seen[-1][:2] == ("PATCH", "https://api.github.com/repos/o/r/issues/comments/55") and json.loads(seen[-1][2]) == {"body": "x"}
    assert judge.github("repos/o/r/issues/7/assignees", {"assignees": ["mona"]}, "DELETE") == {"ok": True}
    assert seen[-1][0] == "DELETE" and json.loads(seen[-1][2]) == {"assignees": ["mona"]}
    sent = len(seen)
    for method, path in (("DELETE", "repos/o/r/issues/7"), ("DELETE", "repos/o/r/issues/comments/55"), ("DELETE", "repos/o/r"),
                         ("DELETE", "repos/o/r/git/refs/heads/main"), ("PATCH", "repos/o/r/issues/7"), ("PATCH", "repos/o/r"),
                         ("PATCH", "repos/o/r/issues/comments/55/../../7"), ("PUT", "repos/o/r/contents/x"), ("delete", "repos/o/r/issues/7/assignees")):
        with pytest.raises(ValueError, match="Knos does not send"):
            judge.github(path, {"x": 1}, method)
    assert len(seen) == sent                                                               # refused before anything was sent
    # a Run hands the method on only when there is one, so a fake that takes (path, data) still serves
    calls = []
    run = flow.Run(REPO, {}, github=lambda *a: calls.append(a))
    run.github("a"), run.github("b", {"x": 1}), run.github("c", {"x": 1}, "PATCH")
    assert calls == [("a", None), ("b", {"x": 1}), ("c", {"x": 1}, "PATCH")]


def test_the_four_commands_run_from_the_command_line(tmp_path, monkeypatch, capsys):
    import time
    w = bounty(tmp_path, now=time.time())                                                  # the command line reads the real clock
    w.chain.bind(MONA)
    relay = types.ModuleType("knos.settle.v2.relay")                                       # another worktree's module: only `submit` is asked of it
    relay.submit = w.relay.submit
    monkeypatch.setitem(sys.modules, "knos.settle.v2.relay", relay)
    monkeypatch.setattr("knos.settle.v2.relay", relay, raising=False)
    monkeypatch.setattr("knos.judge.github", w.hub)
    monkeypatch.setattr("knos.chain.ledger", lambda: w.chain)
    monkeypatch.setattr("knos.chain.key", lambda: "the relay key")
    monkeypatch.setattr("knos.flow.mint", lambda audience, env=None: w.signer(audience))
    monkeypatch.setenv("KNOS_RELAY_KEY", "[1]")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    monkeypatch.delenv("KNOS_CLUSTER", raising=False)

    def knos(name: str, event: dict, *more: str) -> int:
        (tmp_path / "event.json").write_text(json.dumps(event), encoding="utf-8")
        return main([name, "--event", str(tmp_path / "event.json"), "--repo", REPO, *more])
    assert knos("check", {"action": "opened", "pull_request": w.hub.pulls[12], "repository": w.hub.repo}) == 0
    assert "### Knos check\n\nThis pull request takes the bounty on issue #7" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert knos("review", w.hub.ran(12)) == 0 and w.hub.knos(12)[0].startswith(flow.MARK)
    assert knos("settle", w.hub.merge(12)) == 0 and w.hub.knos(12)[-1].startswith("Knos: paid. @mona received 19.50 ")
    assert knos("command", w.hub.commented(12, EVE, "/knos settle")) == 0
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "settle=12\n"
    assert knos("command", w.hub.commented(7, HUBOT, "/knos fund 20 checks: none")) == 0 and len(w.chain.jobs(7)) == 1
    # the job after the sandboxed judge: knos settle --tests --pull N --head SHA
    w.hub.issue(9)
    w.hub.bundles[9] = dict(CHECKS)
    w.chain.fund(9, 5_000_000, BY_TESTS)
    head = w.hub.pull(13, MONA, "Fixes #9")["head"]["sha"]
    w.hub.checks[head] = [check("test"), check("build")]
    assert knos("settle", w.hub.ran(13), "--tests", "--pull", "13", "--head", head) == 0
    assert w.hub.knos(13)[-1].startswith("Knos: paid. @mona received 4.875 ") and w.signer.asked[-1].split(":")[7] == "1"
    capsys.readouterr()
    assert knos("settle", w.hub.ran(13), "--pull", "13") == 1                              # the judge's options without --tests
    assert capsys.readouterr().out.strip() == "--pull, --head and --issue go with --tests: the job that follows the sandboxed judge."
    # what is not an event, and what is not a repository, is said in one line
    assert main(["command", "--event", str(tmp_path / "nothing.json"), "--repo", REPO]) == 1
    assert "nothing.json is not the event GitHub handed the workflow" in capsys.readouterr().out
    assert main(["settle", "--event", str(tmp_path / "event.json"), "--repo", "just-a-name"]) == 1
    assert capsys.readouterr().out.strip() == "Name the repository as owner/name."
    assert main(["review", "--repo", REPO]) == 2                                           # no event at all: typer's own usage line


def test_an_appeal_with_no_rejection_on_record_opens_nothing_and_says_so(tmp_path):
    """`/knos appeal <reason>` (knos.appeal): the verdict a pull request has is what the judge's memory holds of its
    settlement. With none there is nothing to appeal; without a reason the command is not read."""
    w = bounty(tmp_path, author=DEVIN, body="Fixes #7")
    run = w.run(w.hub.commented(12, DEVIN, "/knos appeal the regression test I added passes"))
    assert flow.command(run) == 0 and run.outputs == {}
    said = w.hub.knos(12)[-1]
    assert said.startswith("Knos: no appeal was opened.") and said.endswith("(`appeal.unjudged`)")
    assert "accepted" not in said        # nothing on record is not an accepted verdict (what knos-playground#4 was told)
    run = w.run(w.hub.commented(12, DEVIN, "/knos appeal"))
    assert flow.command(run) == 0 and "say why after it" in w.hub.knos(12)[-1]
