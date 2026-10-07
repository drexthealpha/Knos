"""The test USDC faucet (src/knos/faucet.py): its rules, its journal, and the transfer itself in the simulator."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from knos import faucet, playground
from knos.proof import history

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_791_000_000                      # a fixed moment: 2026-10-03 UTC
A1, A2 = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
OLD = "2020-01-01T00:00:00Z"


def user(uid=7, **over):
    return {"id": uid, "login": f"dev{uid}", "type": "User", "created_at": OLD, "public_repos": 3, "public_gists": 0, **over}


class Fake:
    """A cluster that lands a transfer when told to: every signature, what was submitted, what landed."""
    def __init__(self, holds=1_000_000_000, land=True):
        self.have, self.land, self.n, self.block = holds, land, 0, 100
        self.sent, self.landed, self.failed, self.binds = [], set(), set(), {}

    def holds(self):
        return self.have

    def sign(self, to, amount):
        self.n += 1
        return faucet.Signed(f"sig{self.n}", self.block + 150, (to, amount))

    def submit(self, signed):
        self.sent.append(signed.sig)
        if self.land:
            self.landed.add(signed.sig)
            self.have -= signed.raw[1]

    def status(self, sig):
        return "landed" if sig in self.landed else "failed" if sig in self.failed else "unknown"

    def height(self):
        return self.block

    def bound(self, account):
        return self.binds.get(account)


@pytest.fixture
def store(tmp_path):
    return history.SibylStore.local(tmp_path / "journal", "knos-faucet")


def ask(n=1, account=7, to=A1):
    return faucet.Ask(f"github:{n}", account, to)


def test_a_first_request_sends_the_fixed_amount_once_and_every_reply_says_it_has_no_value(store):
    chain = Fake()
    out = faucet.grant(store, chain, ask(), user(), NOW)
    assert out.state == "sent" and chain.sent == ["sig1"] and "20.00 test USDC sent" in out.reply
    again = faucet.grant(store, chain, ask(), user(), NOW + 5)              # the same comment, delivered twice
    assert again.state == "sent" and chain.sent == ["sig1"] and again.row["sig"] == "sig1"
    for o in (out, again, faucet.no("x")):
        assert "no monetary value" in o.reply
    assert [r["state"] for r in faucet.rows(store)] == ["sent"]


def test_one_grant_per_account_and_per_address_in_seven_days(store):
    chain = Fake()
    assert faucet.grant(store, chain, ask(), user(), NOW).state == "sent"
    same_account = faucet.grant(store, chain, ask(2, to=A2), user(), NOW + 86_400)
    same_address = faucet.grant(store, chain, ask(3, account=8), user(8), NOW + 86_400)
    assert same_account.state == same_address.state == "refused" and chain.sent == ["sig1"]
    assert "This account had test USDC" in same_account.reply and "This address had test USDC" in same_address.reply
    assert faucet.grant(store, chain, ask(4, to=A2), user(), NOW + faucet.PERIOD).state == "sent"       # the eighth day


def test_the_daily_cap_holds_for_everyone_together(store, monkeypatch):
    chain, keys = Fake(), _addresses(11)
    for i in range(10):
        assert faucet.grant(store, chain, ask(i, account=100 + i, to=keys[i]), user(100 + i), NOW + i).state == "sent"
    over = faucet.grant(store, chain, ask(10, account=110, to=keys[10]), user(110), NOW + 60)
    assert over.state == "refused" and "for today" in over.reply and len(chain.sent) == 10
    assert sum(r["units"] for r in faucet.rows(store)) == faucet.DAY_CAP
    assert faucet.grant(store, chain, ask(11, account=110, to=keys[10]), user(110), NOW + 86_400).state == "sent"


def _addresses(n):
    from solders.keypair import Keypair
    return [str(Keypair.from_seed(bytes([i + 1]) * 32).pubkey()) for i in range(n)]


@pytest.mark.parametrize("who, word", [
    (user(type="Bot"), "not to a bot"), (user(type="Organization"), "not to a bot"),
    (user(created_at="2026-09-20T00:00:00Z"), "at least 30 days old"),
    (user(public_repos=0), "at least one public repository or gist"), (None, "did not say who"), (user(9), "another account")])
def test_the_anti_drain_rule_reads_one_public_answer_about_the_account(store, who, word):
    chain = Fake()
    out = faucet.grant(store, chain, ask(), who, NOW)
    assert out.state == "refused" and word in out.reply and chain.sent == [] and faucet.rows(store) == []


def test_an_empty_faucet_and_a_bad_address_send_nothing(store):
    assert "empty" in faucet.grant(store, Fake(holds=19_999_999), ask(), user(), NOW).reply
    assert "not a Solana address" in faucet.grant(store, Fake(), ask(to="0x" + "ab" * 20), user(), NOW).reply
    assert faucet.rows(store) == []


def test_a_retry_never_sends_twice_while_the_first_transfer_can_still_land(store):
    chain, seen = Fake(land=False), []
    first = faucet.grant(store, chain, ask(), user(), NOW, noted=lambda row: seen.append((dict(row), list(chain.sent))))
    assert first.state == "pending" and chain.sent == ["sig1"]
    assert seen[0][0]["sig"] == "sig1" and seen[0][1] == []                # journaled, and told, BEFORE it was sent
    for n in (1, 2):                                                       # the same comment again; then a new comment
        again = faucet.grant(store, chain, ask(n, to=A2 if n == 2 else A1), user(), NOW + 30)
        assert again.state == "pending" and chain.sent == ["sig1"] and chain.n == 1
    chain.landed.add("sig1")                                               # it lands late
    late = faucet.grant(store, chain, ask(2, to=A2), user(), NOW + 60)
    assert late.state == "sent" and late.row["to"] == A1 and late.row["sig"] == "sig1" and chain.sent == ["sig1"]


def test_a_transfer_that_can_no_longer_land_is_replaced_by_exactly_one(store):
    chain = Fake(land=False)
    faucet.grant(store, chain, ask(), user(), NOW)
    chain.block += 151                                                     # past last_valid: sig1 is dead for good
    chain.land = True
    out = faucet.grant(store, chain, ask(), user(), NOW + 120)
    assert out.state == "sent" and chain.sent == ["sig1", "sig2"] and chain.landed == {"sig2"} and chain.have == 1_000_000_000 - faucet.AMOUNT
    assert [(r["state"], r["sig"]) for r in faucet.rows(store)] == [("sent", "sig2")]


def test_a_failed_transfer_is_void_and_counts_against_no_limit(store):
    chain = Fake(land=False)
    faucet.grant(store, chain, ask(), user(), NOW)
    chain.failed.add("sig1")
    assert faucet.grant(store, chain, ask(), user(), NOW + 10).state == "refused"
    chain.land = True
    assert faucet.grant(store, chain, ask(2), user(), NOW + 20).state == "sent"


def test_a_crash_between_signing_and_sending_loses_nothing_and_doubles_nothing(store):
    class Dies(Fake):
        def submit(self, signed):
            raise OSError("the connection dropped")
    chain = Dies()
    assert faucet.grant(store, chain, ask(), user(), NOW).state == "pending"
    ok = Fake(); ok.n = 1
    assert faucet.grant(store, ok, ask(), user(), NOW + 5).state == "pending" and ok.sent == []      # sig1 may have left
    ok.block += 151
    assert faucet.grant(store, ok, ask(), user(), NOW + 120).state == "sent" and ok.sent == ["sig2"]


# ---- the issue: a fake forge -----------------------------------------------------------------------------------------
class Forge:
    def __init__(self, users):
        self.users, self.comments, self.n = users, [], 900

    def get(self, path):
        if path.startswith("users/"):
            return self.users[path.split("/")[1]]
        assert "/issues/12/comments?since=" in path
        return list(self.comments) if path.endswith("page=1") else []

    def post(self, text):
        self.n += 1
        self.comments.append({"id": self.n, "user": {"login": faucet.BOT}, "body": text})
        return self.n

    def edit(self, cid, text):
        next(c for c in self.comments if c["id"] == cid)["body"] = text


def event(body, cid=1, uid=7, labels=("faucet",), repo=playground.REPO, owner=playground.OWNER_ID):
    return {"action": "created", "repository": {"full_name": repo, "owner": {"id": owner}},
            "issue": {"number": 12, "labels": [{"name": n} for n in labels]},
            "comment": {"id": cid, "body": body, "user": {"login": f"dev{uid}", "id": uid}}}


def test_a_comment_is_answered_once_and_a_new_runner_reads_the_journal_back_from_the_issue(tmp_path):
    forge, chain = Forge({"dev7": user(), "dev8": user(8)}), Fake()
    def run(ev, name):        # every run is a new runner: an empty store
        return faucet.answer(ev, forge.get, history.SibylStore.local(tmp_path / name, "knos-faucet"), chain, NOW, forge.post, forge.edit)
    out = run(event(f"thanks!\n/knos faucet {A1}"), "a")
    assert out.state == "sent" and len(forge.comments) == 1 and "sent to" in forge.comments[0]["body"]
    assert faucet.MARK in forge.comments[0]["body"]
    again = run(event(f"/knos faucet {A2}", cid=2), "b")                     # another runner, another comment, the same account
    assert again.state == "refused" and chain.sent == ["sig1"] and "One grant per 7 days" in forge.comments[1]["body"]
    assert run(event(f"/knos faucet {A1}", cid=3, uid=8), "c").state == "refused"      # the address had its grant too


def test_two_runs_that_overlap_send_once_the_pre_posted_signature_is_the_lock(tmp_path):
    """Two runners answer two comments of one account at the same moment. Each reads the journal, signs, POSTS its
    signature, then reads the issue again before anything leaves: the run whose reply is the later one finds the
    earlier one and sends nothing."""
    forge, chain = Forge({"dev7": user(), "dev8": user(8)}), Fake()

    def run(ev, name, get=None):
        return faucet.answer(ev, get or forge.get, history.SibylStore.local(tmp_path / name, "knos-faucet"), chain, NOW, forge.post, forge.edit)
    # B read the journal while it was empty; A then ran from start to end; B goes on with what it read
    began: list = []

    def stale(path):
        if "/comments?" in path and not began:          # B's first read of the journal: nothing yet
            began.append(1)
            return []
        if path.startswith("users/") and len(began) == 1:
            began.append(2)
            assert run(event(f"/knos faucet {A1}", cid=1), "a").state == "sent"      # A, whole, while B waits for GitHub
        return forge.get(path)
    out = run(event(f"/knos faucet {A2}", cid=2), "b", stale)
    assert out.state == "refused" and "is being sent already" in out.reply and chain.sent == ["sig1"] and chain.have == 1_000_000_000 - faucet.AMOUNT
    assert [faucet.MARK in c["body"] for c in forge.comments] == [True, False]      # A's reply carries the grant; B's pending line was taken back
    assert faucet.NOTE in forge.comments[1]["body"] and "sig2" not in forge.comments[1]["body"]
    # the same race for one ADDRESS asked for by two accounts
    forge, chain, began = Forge({"dev7": user(), "dev8": user(8)}), Fake(), []

    def stale8(path):
        if "/comments?" in path and not began:
            began.append(1)
            return []
        if path.startswith("users/") and len(began) == 1:
            began.append(2)
            assert run(event(f"/knos faucet {A1}", cid=11), "c").state == "sent"
        return forge.get(path)
    assert run(event(f"/knos faucet {A1}", cid=12, uid=8), "d", stale8).state == "refused" and chain.sent == ["sig1"]
    # both posted before either looked: the EARLIER reply sends (a later one does not stop it), so exactly one of two does
    forge, chain = Forge({"dev7": user()}), Fake()
    later = {"request": "github:22", "forge": "github", "account": 7, "to": A2, "units": faucet.AMOUNT, "state": "pending", "sig": "other", "last_valid": 250, "at": NOW}
    post = forge.post

    def post_then_the_other(text):
        mine = post(text)
        if len(forge.comments) == 1:
            post(f"Knos: on its way.\n\n{faucet.marker(later)}")       # the other run's reply lands right after this one's
        return mine
    forge.post = post_then_the_other
    first = faucet.answer(event(f"/knos faucet {A1}", cid=21), forge.get, history.SibylStore.local(tmp_path / "e", "knos-faucet"), chain, NOW, forge.post, forge.edit)
    assert first.state == "sent" and chain.sent == ["sig1"]
    # GitHub does not answer the second look: nothing leaves, and the reply says so
    forge, chain, looks = Forge({"dev7": user()}), Fake(), []

    def down(path):
        if "/comments?" in path:
            looks.append(path)
            if len(looks) > 1:
                raise OSError("502")
        return forge.get(path)
    out = run(event(f"/knos faucet {A1}", cid=31), "f", down)
    assert out.state == "refused" and "could not see whether this request is being sent already" in out.reply and chain.sent == []
    assert faucet.MARK not in forge.comments[0]["body"]
    assert run(event(f"/knos faucet {A1}", cid=32), "g").state == "sent" and chain.sent == ["sig2"]      # asked again, it is sent, once


def test_a_marker_written_by_anyone_but_the_workflow_is_not_the_journal(store):
    row = {"request": "github:5", "account": 7, "to": A1, "units": faucet.AMOUNT, "state": "sent", "sig": "s", "last_valid": 1, "at": NOW}
    forged = {"user": {"login": "dev7"}, "body": faucet.marker(row)}
    wrong = {"user": {"login": faucet.BOT}, "body": faucet.marker({**row, "units": 5})}
    assert faucet.restore(store, [forged, wrong]) == 0 and faucet.rows(store) == []
    assert faucet.restore(store, [{"user": {"login": faucet.BOT}, "body": "x\n" + faucet.marker(row)}]) == 1
    assert faucet.restore(store, [{"user": {"login": faucet.BOT}, "body": faucet.marker({**row, "state": "pending"})}]) == 0     # sent stays sent


def test_only_the_playgrounds_faucet_issue_is_answered_and_the_word_passkey_means_the_bound_address(store):
    forge, chain = Forge({"dev7": user()}), Fake()
    for ev in (event(f"/knos faucet {A1}", labels=()), event(f"/knos faucet {A1}", repo="someone/knos-playground"),
               event(f"/knos faucet {A1}", owner=1), event("hello")):
        assert faucet.answer(ev, forge.get, store, chain, NOW, forge.post, forge.edit) is None
    assert forge.comments == [] and chain.sent == []
    none = faucet.answer(event("/knos faucet passkey"), forge.get, store, chain, NOW, forge.post, forge.edit)
    assert none.state == "refused" and "bound no address" in none.reply
    bad = faucet.answer(event("/knos faucet [click](http://x)", cid=2), forge.get, store, chain, NOW, forge.post, forge.edit)
    assert bad.state == "refused" and "click" not in bad.reply
    chain.binds[7] = A2
    out = faucet.answer(event("/knos faucet PASSKEY", cid=3), forge.get, store, chain, NOW, forge.post, forge.edit)
    assert out.state == "sent" and out.row["to"] == A2


def test_the_comment_grammar_hands_the_line_over_and_the_repositorys_own_workflow_leaves_the_answer_to_the_faucet(tmp_path):
    """knos.commands (which the relay reads) knows the line and judges nothing of it; knos.faucet's words for it are the
    same text. On the playground's faucet issue the workflow's own command job says nothing, so a request has one
    reply; anywhere else it says where the faucet is."""
    from _flow import World

    from knos import commands, flow
    assert commands.FORMS["faucet"] == faucet.FORM and commands.FAUCET_LABEL == faucet.LABEL and commands.FAUCET_WHERE == faucet.WHERE
    for body in (f"/knos faucet {A1}", "/knos faucet passkey", "/knos faucet", "/knos faucet nonsense", f"thanks\n /KNOS  Faucet   {A2}  "):
        got = commands.parse(body)
        assert isinstance(got, commands.Faucet) and got.to == (faucet.read(body) or got.to) and (faucet.read(body) is not None)
    assert faucet.NOTE.rstrip(".") in commands.FAUCET_ELSEWHERE.replace("test USDC, which has", "Test USDC has") and faucet.WHERE in commands.FAUCET_ELSEWHERE
    assert f"`{faucet.FORM}`" in commands.reply("unknown", word="fawcet")                # `/knos help` lists it
    w = World(tmp_path)

    def said(ev) -> list[str]:
        before = len(w.hub.posted)
        assert flow.command(w.run(ev)) == 0
        return [d["body"] for _p, d in w.hub.posted[before:]]
    ask = {"action": "created", "issue": {"number": 12, "labels": [{"name": "faucet"}]}, "comment": {"id": 5, "body": f"/knos faucet {A1}", "user": {"login": "dev7", "id": 7}}}
    here = {**ask, "repository": {"full_name": playground.REPO, "owner": {"id": playground.OWNER_ID}}}
    assert said(here) == []                                                              # the faucet's own job answers there
    for elsewhere in ({**ask, "repository": {"full_name": "o/r", "owner": {"id": 1}}},                                   # another repository, whatever its labels
                      {**here, "issue": {"number": 12, "labels": []}},                                                   # the playground, another issue
                      {**here, "repository": {"full_name": playground.REPO, "owner": {"id": 1}}}):                       # the name under another owner
        assert said(elsewhere) == [commands.FAUCET_ELSEWHERE]
    assert said({**here, "action": "edited"}) == []                                      # an edit asks nothing again


def test_reading_the_line():
    assert faucet.read(f"/knos faucet {A1}") == A1 and faucet.read("  /knos  faucet  passkey ") == "passkey"
    assert faucet.read("/knos faucet") == "" and faucet.read(f"/knos faucet {A1} now") is None and faucet.read("/knos fund 5") is None


# ---- the transfer itself, in the simulator ---------------------------------------------------------------------------
def test_the_faucet_key_signs_holds_no_sol_and_the_transfer_moves_exactly_twenty(monkeypatch):
    pytest.importorskip("solders.litesvm")
    from solders.keypair import Keypair
    from _pay2 import Chain                               # as every test imports it: `tests._pay2` resolves only when run from the root
    from knos.settle.v2 import pay
    c = Chain()
    mint = c.new_mint()
    key, payer = Keypair.from_seed(b"\x21" * 32), c.payer
    source = c.token_account(key.pubkey(), mint)
    c.mint_to(mint, source, 50_000_000)
    dev = faucet.DevnetChain(None, key, payer, mint)
    to = pay.auth_pda()                                   # an address off the curve, as a passkey wallet is
    assert c.send(dev.ixs(str(to), faucet.AMOUNT), payer, [key], mark=False), c.err
    assert c.balance(pay.ata(to, mint)) == faucet.AMOUNT and c.balance(source) == 30_000_000
    assert c.svm.get_account(key.pubkey()) is None        # the faucet key never held a lamport
    with pytest.raises(Exception, match="not enough signers"):      # without the faucet key's signature there is no transaction
        c.send(dev.ixs(str(to), faucet.AMOUNT), payer, [payer], mark=False)
    thief = faucet.DevnetChain(None, Keypair.from_seed(b"\x22" * 32), payer, mint)
    thief.source = source                                 # another key naming the faucet's account as its own
    assert not c.send(thief.ixs(str(to), faucet.AMOUNT), payer, [thief.faucet], mark=False) and c.balance(source) == 30_000_000
    with pytest.raises(ValueError, match="a key of its own"):
        faucet.DevnetChain(None, payer, payer, mint)


def test_the_command_is_registered_by_its_own_module_and_the_document_states_the_same_rules():
    src = (ROOT / "src" / "knos" / "faucet.py").read_text(encoding="utf-8")
    assert "\nimport typer" not in src and "from typer" not in src
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    app, lines = typer.Typer(), []
    faucet.register(app, lines)

    @app.command("other")
    def _other() -> None:
        pass
    assert lines and lines[0][0] == "faucet"
    got = CliRunner().invoke(app, ["faucet", "request", A1])
    assert got.exit_code == 0 and f"/knos faucet {A1}" in got.output and "no monetary value" in got.output
    assert CliRunner().invoke(app, ["faucet", "request", "nope"]).exit_code == 2
    doc = (ROOT / "docs" / "FAUCET.md").read_text(encoding="utf-8")
    for fact in ("20 test USDC", "7 days", "200 test USDC", "30 days", "no monetary value", "KNOS_FAUCET_KEY", "faucet tokens", "/knos fund 5"):
        assert fact in doc, fact
    assert json.loads(faucet.marker({"request": "r", "x": 1})[len(faucet.MARK):-4]) == {"request": "r"}
