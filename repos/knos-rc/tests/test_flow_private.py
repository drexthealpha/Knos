"""PRIVATE work orders, driven from an organisation's ATTESTOR repository (knos.flow, "the attestor").

Two repositories: acme/vault-core is private (tests/_flow.py's GitHub, under that name) and runs nothing; acme/knos-settle
is its attestor, PUBLIC here (`Public`, below): its job's own token reaches only itself, it reads the private one through
the read token (`reader`), mints there, and posts its tokens on its own "knos tokens" issue, where the public worker
(played by `Public.wait_for`, with knos.proof.ghrelay's own regexes, note and log line) finds them.

The last test is the reason for the rest: nothing of the private repository is in any public place."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error

import pytest
from _flow import HUBOT, MONA, WALLET, GitHub, World, check, claims, program_digits, program_u64, sha, stamp
from _hub import BOT, user
from _pay21 import BUILDS, Live
from knos import flow, policy
from knos.proof import ghrelay
from knos.settle.v2 import pay
from knos.settle.v2 import relay as real_relay

ATTESTOR, ATTESTOR_ID = "acme/knos-settle", 31_313_131
TARGET, TARGET_ID = "acme/vault-core", 918_273_645
ISSUE, PULL = 41_077, 41_123                # numbers no hash or address holds by chance
ACME = user("acme", 9000, "Organization")
# The chain answers Version 2 (knos_pay 2.2: 0.30%, at least 0.05), then 1 (2.1, which the public ids run until the
# upgrade: the 0.3.14 tiers): every test runs on both, and P(old, new) is what it pins for each.
LIVE = Live()
P = LIVE.pick


@pytest.fixture(scope="module", params=BUILDS, ids=Live.name, autouse=True)
def live(request):
    yield from LIVE.run(request.param, "")
SALT = hashlib.sha256(b"a salt of this test's own").digest()
POLICY = f"version: 1\nprivate: true\nattestor: {ATTESTOR}\ntargets: [{TARGET}]\nwho_may_fund: [hubot]\n"
FUND = "/knos fund 20 checks: unit-suite paths: src/secret_module/**"
# everything that names the private repository: its name, its id, the issue, the pull request, the branch, the check, the path
PRIVATE = (TARGET, "vault-core", str(TARGET_ID), str(ISSUE), str(PULL), f"fix-{PULL}", "unit-suite", "secret_module", "src/")


class Public:
    """acme/knos-settle on api.github.com as its own job's token sees it, and the public worker that reads its "knos
    tokens" issue: knos.judge.github's callable, and knos.proof.ghrelay's `token_id` and `wait_for`. Whatever is asked
    of it about another repository is a 404, and is remembered: the job's own token must never try."""

    def __init__(self, w: World, text: str = POLICY, name: str = ATTESTOR):
        self.w, self.name, self.policy, self.issues, self.comments, self.asked, self.log, self.silent = w, name, text, [], [], [], [], False

    def __call__(self, path: str, data: dict | None = None, method: str | None = None):
        self.asked.append(path)
        here = f"repos/{self.name}"
        bare = path.split("?")[0]
        if bare == here:
            return {"id": ATTESTOR_ID, "full_name": self.name, "default_branch": "main", "owner": dict(ACME)}
        if bare == f"{here}/contents/.knos/policy.yml" and self.policy is not None:
            return {"encoding": "base64", "content": base64.b64encode(self.policy.encode()).decode()}
        if bare == f"{here}/issues" and data is None:
            return list(self.issues)
        if bare == f"{here}/issues":
            self.issues.append({"number": len(self.issues) + 1, "title": data["title"], "body": data["body"], "state": "open"})
            return self.issues[-1]
        m = re.fullmatch(rf"{here}/issues/(\d+)/comments", bare)
        if m and data is not None and int(m.group(1)) in [i["number"] for i in self.issues]:
            self.comments.append({"id": len(self.comments) + 1, "issue": int(m.group(1)), "body": data["body"], "user": BOT,
                                  "created_at": stamp(self.w.clock()), "html_url": f"https://github.com/{self.name}/issues/{m.group(1)}#issuecomment-{len(self.comments) + 1}"})
            return self.comments[-1]
        raise urllib.error.HTTPError(f"https://api.github.com/{path}", 404, "Not Found", None, None)

    def token_id(self, jwt: str) -> str:
        return ghrelay.token_id(jwt)

    def wait_for(self, tid: str, log_repo: str, timeout: float, every: float = 3.0, get=None) -> str | None:
        """The public worker's pass: it finds the token comment as knos.proof.ghrelay does, holds the terms line to the
        audience as knos.settle.v2.relay does, relays, and writes its public log line."""
        if self.silent:
            self.w.clock.sleep(timeout)
            return None
        said = next(c for c in self.comments if any(ghrelay.token_id(jwt) == tid for _k, jwt in ghrelay.TOKEN.findall(c["body"])))
        [(marker, jwt)], beside = ghrelay.TOKEN.findall(said["body"]), ghrelay.TERMS.search(said["body"])
        assert ghrelay.MARK in said["body"]
        if marker == "fund":
            assert real_relay.carries_terms(claims(jwt)["aud"], beside.group(1)), "the relay would not take this `knos-terms:` line"
        self.w.clock.sleep(9)
        r = self.w.relay.submit(self.w.chain, None, jwt, beside.group(1).encode() if beside else None)
        line = ghrelay.log_line(ghrelay.RELAY_KIND.get(marker, marker), self.name, said["issue"], jwt, {**r, **({"note": ghrelay.note(r)} if r["ok"] else {})}, 39)
        self.log.append(line)
        return line


def world(tmp_path, held: int = 100_000_000, listed: bool = True) -> tuple[World, Public]:
    """The private repository with issue #41077 and a check its branch requires; the organisation's Balance, which lists
    the attestor repository and hubot as a spender; and the attestor."""
    w = World(tmp_path, relay_key=False)
    w.version = LIVE.v
    w.hub = GitHub(w.clock, TARGET, TARGET_ID)
    w.hub.repo["owner"] = dict(ACME)
    w.hub.required = [{"context": "unit-suite", "integration_id": 15368}]
    w.hub.checks[w.hub.head] = [check("unit-suite")]
    w.hub.issue(ISSUE, "The vault leaks a handle.")
    w.balance = w.chain.balance("acme", held, spenders=[HUBOT["id"]], owner=ACME["id"])
    if listed:
        x = bytearray(pay.BALX_LEN)
        x[0], x[24:32] = 1, ATTESTOR_ID.to_bytes(8, "little")
        w.chain.accounts[str(pay.balx_pda(w.balance))] = bytes(x)
    return w, Public(w)


def run(w: World, pub: Public, event: dict, here: str = ATTESTOR, starter: dict = HUBOT, **env) -> flow.Run:
    """One job of the attestor's workflow: its own token reaches `pub` alone, the read token reaches the private
    repository alone, and GitHub signs for a run in the attestor repository that `starter` started."""
    w.runs += 1
    w.signer.repo_id, w.signer.actor = ATTESTOR_ID, starter["id"]
    w.signer.more = {"repository": here, "repository_owner_id": str(ACME["id"]), "event_name": "schedule" if "schedule" in event else "workflow_dispatch"}

    def reader(repo: str):
        assert repo == TARGET, repo
        return w.hub
    return flow.Run(here, event, github=pub, ledger=w.chain, relay=w.relay, ghrelay=pub, mint=w.signer, key=lambda: "the relay key",
                    env={"GITHUB_RUN_ID": "77", "GITHUB_ACTOR_ID": str(starter["id"]), "GITHUB_ACTOR": starter["login"],
                         "GITHUB_STEP_SUMMARY": str(w.tmp / "summary.md"), **env},
                    clock=w.clock, sleep=w.clock.sleep, scratch=w.tmp / f"runner-{w.runs}", version=lambda: LIVE.v, screen=w._screen,
                    spent=lambda owner_id: w.month_spent, reader=reader, salt=lambda: SALT)


def by_hand(**inputs) -> dict:
    return {"inputs": {"repository": TARGET, "issue": "", "pull": "", **{k: str(v) for k, v in inputs.items()}}}


SCHEDULE = {"schedule": "*/15 * * * *"}


def funded(tmp_path, **more) -> tuple[World, Public, str]:
    """A `/knos fund` comment on the private issue, answered by the attestor's run by hand: the order's address."""
    w, pub = world(tmp_path, **more)
    w.hub.say(ISSUE, HUBOT, FUND)
    w.clock.sleep(60)
    assert flow.command(run(w, pub, by_hand(issue=ISSUE))) == 0
    [(address, _o)] = w.chain.orders()
    return w, pub, address


def merged(w: World, conclusion: str = "success") -> dict:
    """Pull request #41123 by mona, which closes the issue, merged an hour after the funding."""
    w.clock.sleep(3600)
    p = w.hub.pull(PULL, MONA, f"Fixes #{ISSUE}")
    w.hub.files[PULL] = [{"filename": "src/secret_module/vault.py", "patch": "@@ -1,1 +1,2 @@\n def a():\n+    return 1"}]
    w.hub.checks[p["head"]["sha"]] = [check("unit-suite", conclusion)]
    w.hub.merge(PULL)
    w.clock.sleep(120)
    return p


def test_a_private_order_is_funded_from_the_attestor_and_its_salt_and_terms_stay_on_the_private_issue(tmp_path):
    w, pub, address = funded(tmp_path)
    o = pay.read_order(w.chain.accounts[address])
    record, reply = (c["body"] for c in w.hub.comments[ISSUE][1:])
    kept = json.loads(flow.RECORD.search(record).group(1))
    raw = base64.b64decode(kept["terms"])
    scope, hashed = pay.scope_of(TARGET_ID, ISSUE, SALT), flow.hidden_terms(SALT, raw)
    # on chain: an amount, a Balance, a judge, two hashes. No repository, no issue, no terms, and no neutral run pays it
    assert (o.repo_id, o.issue, o.amount, o.fee, o.judge_repo_id, o.owner_id, o.funder_id) == (0, 0, 20_000_000, P(500_000, 60_000), ATTESTOR_ID, ACME["id"], HUBOT["id"])
    assert o.flags & pay.F_PRIVATE and not o.flags & pay.F_NEUTRAL and (bytes(o.scope), bytes(o.terms)) == (scope, hashed)
    assert address == str(pay.order_pda(scope, w.balance, 0)) and address not in w.chain.logs and w.chain.held(w.balance) == P(79_500_000, 79_940_000)
    # what GitHub signed: issue 0, and the hash of the scope and the terms hash where a public order has its terms hash
    options = pay.opts(pay.F_PRIVATE, reserve_days=7, judge_repo_id=ATTESTOR_ID, salted=True)
    assert w.signer.asked == [pay.order_fund_audience(0, 20_000_000, pay.MERGE, pay.private_fund_terms(scope, hashed), w.balance, 14 * 86_400, 0, options)]
    # off chain, where only people with access read: the salt and the terms, written before anything was signed
    assert (kept["answers"], kept["order"], kept["salt"]) == (w.hub.comments[ISSUE][0]["id"], address, SALT.hex())
    assert json.loads(raw)["checks"][0]["name"] == "unit-suite" and json.loads(raw)["paths"] == ["src/secret_module/**"]
    assert json.loads(raw)["policy"] == policy.digest(policy.load(POLICY))
    assert reply.startswith(flow.ANSWER.format(kept["answers"]) + f"\nKnos: 20.00 test USDC from the balance `{w.balance}` is in escrow for issue "
                            f"#{ISSUE} as a private work order ([order on Solana](https://explorer.solana.com/address/{address}?cluster=devnet)), ")
    assert f"The funder pays Knos's fee of {P('0.50', '0.06')} on top" in reply and "`unit-suite` (the checks you named)" in reply
    assert reply.endswith(f"It is a private order: Solana shows its amount and, once it is paid, who was paid and the commit that was accepted, and never "
                          f"this repository, this issue or these terms. {ATTESTOR}'s workflow pays it after the merge, on its schedule or started by "
                          "hand with this repository and the pull request's number.")
    # in public: one comment on the attestor's "knos tokens" issue, with the line the relay expects (128 hex: scope, terms hash)
    [said] = pub.comments
    assert [i["title"] for i in pub.issues] == ["knos tokens"] and said["body"].startswith(f"knos-fund: {w.relay.submitted[0][0]}\nknos-terms: {(scope + hashed).hex()}\n")
    assert pub.log[0].startswith(f"knos-relay fund {ATTESTOR}#1 ") and "is in escrow as a private work order" in pub.log[0]
    # the schedule finds the same comment and leaves it: it was answered. A new comment is a new order, with a salt of its own
    assert flow.command(run(w, pub, SCHEDULE)) == 0 and len(w.chain.orders()) == 1 and len(w.hub.comments[ISSUE]) == 3 and len(w.signer.asked) == 1
    assert "answered 0 funding comments, funded 0 private orders" in (w.tmp / "summary.md").read_text(encoding="utf-8")


def test_what_stops_a_normal_funding_stops_a_private_one_and_is_said_on_the_private_issue(tmp_path):
    w, pub = world(tmp_path, held=400_000_000, listed=False)
    w.hub.can["mona"] = "write"
    asks = lambda who_, body: w.hub.say(ISSUE, who_, body)  # noqa: E731

    def answer(code: int = 0) -> str:
        w.clock.sleep(60)
        before = len(w.hub.comments[ISSUE])
        assert flow.command(run(w, pub, SCHEDULE)) == code
        return "\n".join(c["body"] for c in w.hub.comments[ISSUE][before:])
    # the policy (the attestor's file) says who may fund; GitHub says who can write; the order's bounds are the escrow's
    asks(MONA, "/knos fund 20")
    assert ".knos/policy.yml line 5: only hubot may fund; mona (4242) is not one of them." in answer()
    asks(HUBOT, "/knos fund 2")
    assert "A work order holds from 5 to 100000, and this one asks for 2." in answer()
    asks(HUBOT, "/knos fund twenty")
    assert flow.ANSWER.format(w.hub.comments[ISSUE][-1]["id"]) in (got := answer()) and "/knos fund <amount>" in got
    # the organisation's Balance must list the attestor repository: without that, any repository of the owner could spend it
    asks(HUBOT, "/knos fund 20")
    got = answer()
    assert f"The balance `{w.balance}` does not list {ATTESTOR} (repository id {ATTESTOR_ID}) among the repositories that may spend it" in got
    # and whoever started the attestor's run must be one of its spenders: GitHub signs that id, not the commenter's
    # (150 is more than the devnet faucet gives, which is test money for whoever a repository's workflow lets through)
    w.clock.sleep(60)
    asks(HUBOT, "/knos fund 150")
    assert flow.command(run(w, pub, SCHEDULE, starter=MONA)) == 0
    assert f"lists whoever started that repository's run as a spender: here @mona (GitHub id {MONA['id']})" in w.hub.comments[ISSUE][-1]["body"]
    assert w.chain.orders() == [] and w.signer.asked == [] and pub.comments == [] and len(w.hub.comments[ISSUE]) == 10
    # an edited comment commands nothing, as everywhere; and a read token that cannot comment is this job's failure, in counts
    w.hub.say(ISSUE, HUBOT, "/knos fund 20", edited=True)
    assert answer() == ""
    w.hub.say(ISSUE, HUBOT, "/knos fund 20")
    w.hub.readonly = True
    assert answer(1) == "" and w.chain.orders() == [] and w.signer.asked == []
    assert "1 could not be read or written" in (w.tmp / "summary.md").read_text(encoding="utf-8")


def test_a_merge_whose_check_failed_is_refused_and_the_same_merge_is_paid_once_the_check_passes(tmp_path):
    w, pub, address = funded(tmp_path)
    w.chain.bind(MONA)
    p = merged(w, "failure")
    head = p["head"]["sha"]
    # the schedule finds the merged pull request, and the terms' evidence is checked as any settlement checks it
    assert flow.settle(run(w, pub, SCHEDULE)) == 0
    [said] = w.hub.knos(PULL)
    assert said.startswith(f"Knos: not paid. This pull request does not take the work order on issue #{ISSUE} (20.00 test USDC) as it stands; its checks "
                           f"are read at its last commit (`{head[:7]}`).\n- `unit-suite`: failed\n")
    assert f"run the knos workflow of {ATTESTOR} by hand with this repository and this pull request's number, or wait for its next scheduled run" in said
    assert "/knos tip" not in said and "/knos settle" not in said and len(w.signer.asked) == 1 and len(w.chain.orders()) == 1 and len(pub.comments) == 1
    # the check is run again on that commit and passes; the attestor is started by hand for that pull request
    w.hub.checks[head] = [check("unit-suite")]
    assert flow.settle(run(w, pub, by_hand(pull=PULL))) == 0
    kept = json.loads(flow.RECORD.search(w.hub.comments[ISSUE][1]["body"]).group(1))
    o_terms = flow.hidden_terms(SALT, base64.b64decode(kept["terms"]))
    # the pay token (judge c: a run in the order's judge repository): the order, THE HEAD COMMIT, the terms hash, and the pull
    # request under a number made of the salt, never its own
    assert w.signer.asked[1] == pay.order_pay_audience(pay.Pubkey.from_string(address), head, o_terms, pay.MERGE, flow.hidden_pull(SALT, PULL), [(MONA["id"], 10_000, None)])
    assert claims(w.relay.submitted[1][0])["repository_id"] == str(ATTESTOR_ID) and "prove.yml@" in claims(w.relay.submitted[1][0])["job_workflow_ref"]
    assert w.chain.orders() == [] and w.relay.answered[1]["paid"] == [{"id": MONA["id"], "payee_id": MONA["id"], "to": WALLET, "held_until": None, "amount": 20_000_000}]
    paid = w.hub.knos(PULL)[-1]
    assert paid.startswith(f"Knos: paid. @mona received 20.00 test USDC for issue #{ISSUE}, in full: its funder paid Knos's fee of {P('0.50', '0.06')} on top. It went to "
                           f"`{WALLET}`, the wallet bound to @mona's GitHub account (")
    assert pub.comments[1]["body"].startswith("knos-proof: ") and "knos-terms" not in pub.comments[1]["body"]
    assert pub.log[1].startswith(f"knos-relay pay {ATTESTOR}#1 ") and f"20.00 was paid to {WALLET} (GitHub user id {MONA['id']}) for order {address}." in pub.log[1]
    # nothing is paid twice: the next scheduled run finds no order behind the record, and says nothing
    assert flow.settle(run(w, pub, SCHEDULE)) == 0 and len(w.hub.knos(PULL)) == 2 and len(w.signer.asked) == 2


def test_a_record_anyone_wrote_on_the_issue_pays_nothing_the_chain_is_held_to_it(tmp_path):
    """Whoever can comment on the private issue can write a record. It names an order; the order has to hash to it."""
    w, pub, address = funded(tmp_path)
    w.chain.bind(MONA)
    real = w.hub.comments[ISSUE][1]
    kept = json.loads(flow.RECORD.search(real["body"]).group(1))
    easy = base64.b64encode(b'{"checks":[],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}').decode()
    real["body"] = "(deleted)"
    w.hub.say(ISSUE, MONA, "<!-- knos-private-order " + json.dumps({**kept, "terms": easy}, separators=(",", ":")) + " -->")
    merged(w, "failure")
    assert flow.settle(run(w, pub, by_hand(pull=PULL))) == 0
    assert w.hub.knos(PULL)[-1].startswith(f"Knos: nothing to pay: no bounty is open on the issue this pull request closes (#{ISSUE})")
    assert len(w.signer.asked) == 1 and [a for a, _o in w.chain.orders()] == [address]


def test_only_the_named_attestor_attests_and_only_for_the_repositories_its_policy_lists(tmp_path, capsys):
    w, pub = world(tmp_path)
    w.hub.say(ISSUE, HUBOT, FUND)
    summary = w.tmp / "summary.md"

    def refused(job, r: flow.Run) -> str:
        summary.write_text("", encoding="utf-8")
        assert job(r) == 1 and w.signer.asked == [] and w.chain.orders() == [] and len(w.hub.comments[ISSUE]) == 1 and w.hub.posted == []
        return summary.read_text(encoding="utf-8")
    # a run in another repository of the organisation, whose policy names the real attestor: refused, whatever it is told
    other = Public(w, name="acme/other")
    for job in (flow.command, flow.settle):
        r = run(w, other, by_hand(issue=ISSUE), here="acme/other")
        r.attestor = True
        assert f".knos/policy.yml line 3: the attestor is {ATTESTOR}, and this run is in acme/other. A private order is funded and paid only from the attestor repository." in refused(job, r)
    # a repository with no policy, or one that names no attestor, is none
    for text in (None, "private: true\n", "cap_per_order: 50\n"):
        said = refused(flow.command, run(w, Public(w, text), SCHEDULE))
        assert f"nothing was funded. .knos/policy.yml of {ATTESTOR} names no attestor" in said
    # a target the policy does not list: refused before anything is read with the read token, and its name is not repeated in the log
    for job in (flow.command, flow.settle):
        said = refused(job, run(w, pub, {"inputs": {"repository": "acme/elsewhere", "issue": "3"}}))
        assert ".knos/policy.yml line 4: targets does not list that repository, so this attestor does nothing for it." in said and "elsewhere" not in said
    r = run(w, pub, SCHEDULE)
    r.attestor, r.only = True, "acme/elsewhere"
    assert "targets does not list that repository" in refused(flow.command, r) and w.hub.asked == []
    # an issue or a pull request is one repository's; and without the secret that reads the targets nothing is tried
    several = Public(w, POLICY.replace(f"[{TARGET}]", f"[{TARGET}, acme/second]"))
    assert "An `issue` or a `pull` is one repository's: name it as `repository` too." in refused(flow.command, run(w, several, {"inputs": {"issue": str(ISSUE)}}))
    blind = run(w, pub, SCHEDULE)
    blind._reader = None
    assert "This job has no KNOS_READ_TOKEN" in refused(flow.settle, blind)
    # a re-run is no first attempt, and a cluster without work orders has no private ones
    assert "This is a re-run" in refused(flow.command, run(w, pub, SCHEDULE, GITHUB_RUN_ATTEMPT="2"))
    old = run(w, pub, SCHEDULE)
    old._version = lambda: 0
    assert "knos_pay 2.1 is not live here" in refused(flow.settle, old)
    # the command line says the same: --target goes with --attestor
    summary.write_text("{}", encoding="utf-8")
    assert flow.main(["command", "--event", str(summary), "--repo", ATTESTOR, "--target", TARGET]) == 1
    assert "--target goes with --attestor and names one repository as owner/name" in capsys.readouterr().out
    # and in a repository that runs Knos itself, a policy that says private funds nothing by a comment: the token would name it
    plain = World(tmp_path / "plain")
    plain.version = 1
    plain.hub.issue(7, "Slugify keeps punctuation.")
    plain.hub.contents[".knos/policy.yml"] = f"private: true\nattestor: {ATTESTOR}\ntargets: [o/r]\n"
    assert flow.command(plain.run(plain.hub.commented(7, HUBOT, "/knos fund 20"))) == 0
    assert (f"a private order is not funded by this repository's own workflow: the token it signs would name this repository and this issue in public. "
            f"Instead, its attestor, {ATTESTOR}, funds it") in plain.hub.knos(7)[-1] and plain.signer.asked == [] and plain.chain.orders() == []


def test_a_run_by_hand_that_names_nothing_is_the_attestors_only_where_the_policy_says_so(tmp_path):
    """The pinned workflows take no inputs, so the command tells an attestor's run from what started it. A run by hand
    with no pull request is the attestor's scan in an attestor, and what it always was anywhere else."""
    w, pub = world(tmp_path)
    w.hub.say(ISSUE, HUBOT, FUND)
    assert flow.command(run(w, pub, {"inputs": {}})) == 0 and len(w.chain.orders()) == 1
    plain = World(tmp_path / "plain")
    assert flow.settle(plain.run({"inputs": {}, "repository": plain.hub.repo})) == 1 and plain.signer.asked == []
    assert not flow._attestor(plain.run({"inputs": {"pull": "12"}, "repository": plain.hub.repo}))
    assert not flow._attestor(plain.run(plain.hub.push([sha("x")]))) and flow._attestor(plain.run(SCHEDULE))


@pytest.mark.parametrize("relay_key", [False, True], ids=["posted for the public relay", "relayed by the attestor's own key"])
def test_nothing_of_the_private_repository_is_in_any_public_place(tmp_path, capsys, relay_key):
    """The fund and pay audiences, the comments on the attestor's public issue, the relay's public log line, the
    attestor job's log and summary, and every request its own token made: none holds the private repository's name or
    id, the issue's or the pull request's number, the branch, the check's name or a path. ONE thing of the repository
    is public, and it is said here and in flow._order_audience: the pay audience carries the accepted commit's id."""
    env = {"KNOS_RELAY_KEY": "[1,2,3]"} if relay_key else {}
    w, pub = world(tmp_path)
    w.chain.bind(MONA)
    w.hub.say(ISSUE, HUBOT, FUND)
    assert flow.command(run(w, pub, SCHEDULE, **env)) == 0
    p = merged(w, "failure")
    assert flow.settle(run(w, pub, SCHEDULE, **env)) == 0                       # refused: its words stay on the private pull request
    w.hub.checks[p["head"]["sha"]] = [check("unit-suite")]
    assert flow.settle(run(w, pub, by_hand(pull=PULL), **env)) == 0 and w.chain.orders() == []
    fund, paid = w.signer.asked
    tokens = [jwt for jwt, _terms in w.relay.submitted]
    public = {
        "the fund audience": fund, "the pay audience": paid,
        "what GitHub signed": json.dumps([{k: v for k, v in claims(jwt).items()} for jwt in tokens]),
        "what travelled with the tokens": repr([terms for _jwt, terms in w.relay.submitted]),
        "the attestor's public issue": json.dumps([pub.issues, pub.comments]),
        "the relay's log lines": "\n".join(pub.log or [ghrelay.log_line(r["kind"], ATTESTOR, 1, jwt, {**r, "note": ghrelay.note(r)}, 39)
                                                       for jwt, r in zip(tokens, w.relay.answered)]),
        "what the relay answered": json.dumps(w.relay.answered),
        "the job's summary": (w.tmp / "summary.md").read_text(encoding="utf-8"),
        "the job's log": capsys.readouterr().out,
        "what the job's own token asked GitHub": "\n".join(pub.asked),
    }
    assert len(tokens) == 2 and (len(pub.comments), len(pub.log)) == ((0, 0) if relay_key else (2, 2))
    assert "funded 1 private order" in public["the job's summary"] and "signed 1 payment" in public["the job's summary"]
    for where, text in public.items():
        assert text, where
        for secret in PRIVATE:
            assert secret not in text, f"{where} names {secret!r}"
    # said plainly: the head commit's id is in the pay audience (and so in the token and the relay's answer). Nothing else is
    head = p["head"]["sha"]
    assert paid.split(":")[3] == head and head not in fund
    assert [part for part in paid.split(":") if part.isdigit()] == ["0", str(flow.hidden_pull(SALT, PULL))]
    # and the private side has all of it, for the people who may read it
    private = "\n".join(c["body"] for n in (ISSUE, PULL) for c in w.hub.comments[n])
    assert all(word in private for word in (f"#{ISSUE}", "unit-suite", head[:7], SALT.hex()))
    # the read token wrote nothing in the private repository but comments on that issue and that pull request
    assert {path for path, _data in w.hub.posted if path != "graphql"} == {f"repos/{TARGET}/issues/{ISSUE}/comments", f"repos/{TARGET}/issues/{PULL}/comments"}


def test_a_token_no_relayer_carried_in_time_is_said_on_the_private_issue_and_the_record_is_already_there(tmp_path):
    """The salt is written before GitHub signs, so an order that a relayer carries late can still be paid."""
    w, pub = world(tmp_path)
    pub.silent = True
    w.hub.say(ISSUE, HUBOT, FUND)
    assert flow.command(run(w, pub, by_hand(issue=ISSUE))) == 1 and w.chain.orders() == []
    record, reply = (c["body"] for c in w.hub.comments[ISSUE][1:])
    assert f"GitHub signed the request (it is posted in {ATTESTOR}) and no relayer carried it to Solana within 10 minutes" in reply
    assert f"if one carries it, the bounty is funded, and {ATTESTOR} pays it like any other. Otherwise post the comment again." in reply
    # the relayer comes late: the order is there, and the record on the issue is what pays it
    pub.silent = False
    [(jwt, beside)] = [(jwt, ghrelay.TERMS.search(c["body"]).group(1)) for c in pub.comments for _k, jwt in ghrelay.TOKEN.findall(c["body"])]
    assert w.relay.submit(w.chain, None, jwt, beside.encode())["ok"] and json.loads(flow.RECORD.search(record).group(1))["order"] == w.chain.orders()[0][0]
    w.chain.bind(MONA)
    merged(w)
    assert flow.settle(run(w, pub, SCHEDULE)) == 0 and w.chain.orders() == [] and w.hub.knos(PULL)[-1].startswith("Knos: paid. @mona received 20.00 test USDC")


def test_the_hidden_pull_number_is_one_knos_pay_parses_and_a_receipt_holds_whatever_the_salt():
    """A private order's pay audience names its pull request by `hidden_pull`; knos_pay reads that field with claims.rs
    parse_u64 (its digit limit is read from the Rust source, not copied here), and a receipt carries it as a JSON number,
    which holds only integers below 2^53 (docs/reference/RECEIPT.md). Eight bytes of hash made 19 private orders in 20 unpayable."""
    import random
    digits = program_digits()
    assert 15 <= digits <= 19                                        # the source was read, and it is still a u64 parser
    rng = random.Random(20261004)
    seen = set()
    for i in range(20_000):
        salt, number = rng.randbytes(32), rng.choice((1, 2, 41_123, 99_999, 2**31 - 1, rng.randrange(1, 2**63)))
        hidden = flow.hidden_pull(salt, number)
        assert program_u64(str(hidden)) == hidden and len(str(hidden)) <= digits and 0 <= hidden < 2**53, (salt.hex(), number, hidden)
        assert flow.hidden_pull(salt, number) == hidden              # the same every time: a standing order pays each pull request once
        seen.add(hidden)
    assert len(seen) > 19_900                                        # and it still tells pull requests apart
    # this file's own order: its 8-byte number had 20 digits, which the fake chain now refuses as the program does
    old = int.from_bytes(hashlib.sha256(SALT + b"knos3:pull" + PULL.to_bytes(8, "little")).digest()[:8], "little")
    assert len(str(old)) > digits and program_u64(str(old)) is None and program_u64(str(flow.hidden_pull(SALT, PULL))) is not None
    # it says nothing of the pull request's number: the salt decides it
    assert flow.hidden_pull(SALT, PULL) != flow.hidden_pull(bytes(32), PULL) and str(PULL) not in str(flow.hidden_pull(SALT, PULL))


def test_a_named_pull_request_whose_repository_github_does_not_answer_for_is_counted_not_commented_on(tmp_path):
    """The run names one pull request, GitHub answers for it and not for the repository itself: nothing can be settled
    without the repository's id and default branch, so the target is counted as not read, and the pull request gets
    no comment about an error inside Knos."""
    w, pub, _address = funded(tmp_path)
    w.chain.bind(MONA)
    merged(w)
    r = run(w, pub, by_hand(pull=PULL))
    asked = len(w.signer.asked)

    def reader(repo: str):
        def get(path, data=None, method=None):
            if path == f"repos/{TARGET}":
                raise OSError("no answer")
            return w.hub(path, data, method)
        return get
    r._reader = reader
    assert flow.settle(r) == 1
    assert w.hub.knos(PULL) == [] and len(w.signer.asked) == asked and len(w.chain.orders()) == 1
    assert "looked at 0 merged pull requests" in (w.tmp / "summary.md").read_text(encoding="utf-8")
    assert " 1 could not be read" in (w.tmp / "summary.md").read_text(encoding="utf-8")
