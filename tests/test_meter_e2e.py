"""The meter's batch mode, end to end on LiteSVM: a ledger file in a repository, the command the pinned workflow runs
(`knos attest --kind batch|claim`, knos.ledger.attest_batch), the audience GitHub signs, the relay (RecordBatch,
ClaimBatch), the two Ledger accounts on chain, and the commands that read them back (`knos meter verify --rpc`,
`knos meter reconcile --rpc`). A buyer anchors 5,000 evaluations in two batches and leaves 3 out; the seller claims
5,003; the chain shows two counts 3 apart, the files say which 3, a changed line no longer verifies, and no token
counts twice."""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from _meter import BUYER, ORDER, POLICY, SELLER, Meter  # noqa: E402
from test_relay2 import JWKS, Net, token  # noqa: E402

from knos import chain, cli  # noqa: E402
from knos import ledger as L  # noqa: E402
from knos.settle.v2 import meter, relay  # noqa: E402

USDC = 1_000_000
DROPPED = (7, 2500, 5002)       # the seller's events the buyer leaves out
RPC = "http://litesvm.invalid"


def _ev(i: int) -> L.Evaluation:
    return L.Evaluation(BUYER, SELLER, ORDER.hex(), hashlib.sha1(f"commit {i}".encode()).hexdigest(), POLICY.hex(), 0, i % 5 != 0, 2 * USDC)


class Repo:
    """What `knos attest` has of a run: the repository's files through GitHub's API, the run's environment, the
    chain. `sign` stands where knos.flow._attest_sign is: it keeps the audience GitHub would be asked to sign."""
    def __init__(self, net, owner: int, files: dict):
        self.repo, self.ledger, self.files, self.said, self.aud = "o/ledgers", net, files, "", None
        self.env = {"GITHUB_REPOSITORY_OWNER_ID": str(owner), "GITHUB_RUN_ATTEMPT": "1"}

    def github(self, path: str, data=None):
        name = path.split("/contents/", 1)[1] if "/contents/" in path else None
        if name is None:                # a file over 1 MB comes as a blob
            return {"content": base64.b64encode(self.files[bytes.fromhex(path.rsplit("/", 1)[1]).decode()].read_bytes()).decode()}
        if name not in self.files:
            raise OSError("404")
        return {"type": "file", "sha": name.encode().hex(), "content": ""}

    def note(self, text: str) -> None:
        self.said = text

    def no(self, why: str, found: str = "") -> int:
        self.said = why
        return 1

    def sign(self, run, kind, aud, said, found, number, o, no) -> int:
        self.aud, self.said = aud, said
        return 0

    def ask(self, kind: str, order: str) -> str | None:
        self.aud = None
        self.rc = L.attest_batch(self, order, kind, self.no, self.sign)
        return self.aud


def _meter(capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    rc = cli.main(["meter", *args])
    return rc, capsys.readouterr().out


def test_a_buyers_batches_and_a_sellers_claim_from_file_to_chain_and_back(tmp_path, capsys, monkeypatch):
    c = Meter()
    net = Net(c)
    monkeypatch.setattr(chain, "Ledger", lambda url: net)       # `--rpc <url>` reads this chain
    go = lambda jwt: relay.submit(net, c.payer, jwt, None, JWKS, now=c.now())  # noqa: E731
    month = meter.yyyymm(c.now())
    mint = c.new_mint()
    _wallet, credits = c.open(mint, BUYER, 500 * USDC)
    c.set_used(BUYER, 9_000)            # the buyer's other evaluations this month: 1,000 of the free 10,000 are left
    theirs = [_ev(i) for i in range(5003)]
    mine = [e for i, e in enumerate(theirs) if i not in DROPPED]
    gone = sorted(theirs[i].id.hex() for i in DROPPED)

    # -- each side keeps its own file: the buyer two batches (3,000 and 2,000), the seller one of 5,003
    buyer, seller = tmp_path / "buyer.jsonl", tmp_path / "seller.jsonl"
    for name, lines in (("b0", mine[:3000]), ("b1", mine[3000:]), ("s0", theirs)):
        (tmp_path / name).write_text("".join(e.audience() + "\n" for e in lines), encoding="utf-8")
    ym = f"{month // 100}-{month % 100:02d}"
    rc, said = _meter(capsys, "batch", str(tmp_path / "b0"), "--ledger", str(buyer), "--month", ym)
    assert rc == 0 and f"audience  knosm:batch:{BUYER}:{SELLER}:{month}:0:3000:" in said
    assert _meter(capsys, "batch", str(tmp_path / "b1"), "--ledger", str(buyer), "--month", ym)[0] == 0
    rc, said = _meter(capsys, "batch", str(tmp_path / "s0"), "--ledger", str(seller), "--month", ym, "--claim")
    assert rc == 0 and f"audience  knosm:claim:{BUYER}:{SELLER}:{month}:0:5003:" in said
    assert buyer.stat().st_size > 1_000_000         # larger than GitHub's contents API returns inline: read as a blob
    b0, b1 = (s.batch() for s in L.load(buyer))
    s0, = (s.batch() for s in L.load(seller))

    # -- the buyer's run: the pinned attest.yml in a repository of the buyer signs the next batch the chain has not got
    repo = Repo(net, BUYER, {"meter/acme.jsonl": buyer})
    assert repo.ask("claim", "meter/acme.jsonl") is None and repo.rc == 1 and "claim is the seller's own" in repo.said       # not the buyer's to claim
    assert repo.ask("batch", "meter/none.jsonl") is None and "could not be read" in repo.said
    assert Repo(net, SELLER, repo.files).ask("batch", "meter/acme.jsonl") is None                          # nor anyone else's to record
    aud0 = repo.ask("batch", "meter/acme.jsonl")
    assert aud0 == L.batch_audience(b0) == meter.batch_audience(BUYER, SELLER, month, 0, 3000, b0.accepted, b0.value, b0.root) and relay.kind_of(aud0) == "batch"
    assert repo.ask("batch", f"meter/acme.jsonl:{month}.1") == L.batch_audience(b1)                         # or the one it is told
    jwt0 = token(c, aud0, file="attest.yml", repository_owner_id=BUYER, run_attempt=1)
    # a re-run, another workflow file, and a run in someone else's repository are refused before anything is sent
    for over in (dict(run_attempt=2), dict(file="other.yml"), dict(repository_owner_id=SELLER)):
        r = go(token(c, aud0, **{"file": "attest.yml", "repository_owner_id": BUYER, "run_attempt": 1, **over}))
        assert not r["ok"] and r["kind"] == "batch", r
    r0 = go(jwt0)
    fee0 = 2000 * meter.FEE         # 9,000 used + 3,000: the 2,000 past the free 10,000 cost 0.05 each
    assert r0 == {"ok": True, "kind": "batch", "sigs": r0["sigs"], "buyer_id": BUYER, "seller_id": SELLER, "month": month, "seq": 0, "count": 3000,
                  "accepted": b0.accepted, "value": b0.value, "root": b0.root.hex(), "fee": fee0, "chain": meter.chain_hash(meter.ZERO, b0.root, 0, 3000, b0.accepted, b0.value).hex()}, r0
    assert c.held(credits) == 500 * USDC - fee0 and c.balance(meter.ata(meter.FEE_OWNER, mint)) == fee0
    # half anchored: the file is ahead of the chain, and verify says so
    rc, said = _meter(capsys, "verify", str(buyer), "--rpc", RPC)
    assert rc == 1 and "next_seq: the ledger gives 2, the chain has 1" in said
    aud1 = repo.ask("batch", "meter/acme.jsonl")
    assert aud1 == L.batch_audience(b1)             # the run after it takes the next one by itself
    jwt1 = token(c, aud1, file="prove.yml", repository_owner_id=BUYER, run_attempt=1)
    r1 = go(jwt1)
    assert r1["ok"] and (r1["seq"], r1["count"], r1["fee"]) == (1, 2000, 2000 * meter.FEE), r1
    assert repo.ask("batch", "meter/acme.jsonl") is None and repo.rc == 0 and "nothing to sign" in repo.said    # a timer's run with no new batch does not fail

    # -- the buyer's file is the chain's: every root, every total, the running hash
    rc, said = _meter(capsys, "verify", str(buyer), "--rpc", RPC)
    assert rc == 0 and "its totals and running hash are those of the buyer's account on chain" in said, said
    assert f"{month} on chain: the buyer's count 5000 evaluation(s) in 2 batch(es)" in said and "the seller's claim 0 evaluation(s) in 0 batch(es)" in said
    mine_on = meter.book(net, BUYER, SELLER, month)
    assert mine_on == meter.BatchLedger(False, month, BUYER, SELLER, 2, 5000, b0.accepted + b1.accepted, b0.value + b1.value, 2 * fee0, L.totals(L.load(buyer), month).chain)
    assert len(c.data(meter.ledger_pda(BUYER, SELLER, month))) == meter.LEDGER_LEN == 96

    # -- the seller's own run, any workflow in a repository the seller owns, no pin and no credits
    shop = Repo(net, SELLER, {"ledger.jsonl": seller})
    claim = shop.ask("claim", "ledger.jsonl")
    assert claim == L.batch_audience(s0, claim=True) and relay.kind_of(claim) == "claim"
    sjwt = token(c, claim, file="count.yml", wf_repo="vendor/books", wf_sha="c" * 40, repository_owner_id=SELLER, run_attempt=3)
    assert not go(token(c, claim, file="count.yml", wf_repo="vendor/books", repository_owner_id=BUYER))["ok"]       # the buyer cannot speak for the seller
    held = c.held(credits)
    rs = go(sjwt)
    assert rs["ok"] and (rs["kind"], rs["count"], rs["fee"]) == ("claim", 5003, 0) and c.held(credits) == held, rs
    rc, said = _meter(capsys, "verify", str(seller), "--rpc", RPC, "--claim")
    assert rc == 0 and "those of the seller's account on chain" in said, said
    assert _meter(capsys, "verify", str(seller), "--rpc", RPC)[0] == 1          # the seller's file is not the buyer's count

    # -- on chain: two counts for one month, 3 apart; the files say which 3
    theirs_on = meter.book(net, BUYER, SELLER, month, claim=True)
    assert theirs_on.claim and theirs_on.evaluations - mine_on.evaluations == 3 == len(DROPPED) and theirs_on.fees == 0
    rc, said = _meter(capsys, "reconcile", str(buyer), str(seller), "--rpc", RPC)
    assert rc == 1 and "The two ledgers differ." in said
    assert sorted(line.split()[1] for line in said.splitlines() if "only the seller has" in line) == gone
    assert "only the buyer has" not in said and "differs in" not in said and "more than once" not in said
    lost = [theirs[i] for i in DROPPED]
    assert (f"{month} on chain: the buyer's count 5000 evaluation(s) in 2 batch(es), {mine_on.accepted} accepted, value {mine_on.value} | the seller's claim "
            f"5003 evaluation(s) in 1 batch(es), {theirs_on.accepted} accepted, value {theirs_on.value}: they differ by 3 evaluation(s), "
            f"{sum(e.accepted for e in lost)} accepted, value {sum(e.value for e in lost)}") in said
    assert f"{month},5000,{mine_on.accepted},{mine_on.value},0,0,3,0" in said
    # and the seller shows each of them in the batch it anchored
    for e in lost:
        p = L.prove(L.load(seller), e.id)
        assert p.ok() and p.root == s0.root and p.size == 5003 and len(p.path) <= 13

    # -- a changed line: the file no longer gives the anchored root; and a ledger rewritten whole no longer gives the running hash
    text = buyer.read_text(encoding="utf-8")
    line = mine[1].line()               # an accepted one
    assert mine[1].accepted and line in text
    forged = tmp_path / "forged.jsonl"
    forged.write_text(text.replace(line, line.replace('{"accepted":1', '{"accepted":0'), 1), encoding="utf-8")
    rc, said = _meter(capsys, "verify", str(forged), "--rpc", RPC)
    assert rc == 1 and "does not hold" in said and "the header says" in said
    other = [e if n != 1 else L.Evaluation(e.buyer, e.seller, e.order, e.artifact, e.policy, e.milestone, False, e.rate) for n, e in enumerate(mine)]
    forged.write_text(L.dump([L.batch(other[:3000], 0, month), L.batch(other[3000:], 1, month)]), encoding="utf-8")
    assert _meter(capsys, "verify", str(forged))[0] == 0                         # it holds by itself
    rc, said = _meter(capsys, "verify", str(forged), "--rpc", RPC)
    assert rc == 1 and "these are not the batches that were anchored" in said and "accepted: the ledger gives" in said

    # -- no token counts twice: the relay sends nothing, and the program refuses it (125) whoever sends it
    before, sent = (mine_on, theirs_on, c.held(credits)), net.txs
    for jwt in (jwt0, jwt1, sjwt):
        r = go(jwt)
        assert not r["ok"] and r["why"] == meter.ERRORS[meter.E_SEQ], r
    assert net.txs == sent
    assert not c.batch(credits, aud0) and c.code == meter.E_SEQ and not c.batch(credits, aud1) and c.code == meter.E_SEQ
    assert not c.claim(claim) and c.code == meter.E_SEQ
    assert (meter.book(net, BUYER, SELLER, month), meter.book(net, BUYER, SELLER, month, claim=True), c.held(credits)) == before


def test_knos_attest_signs_a_batch_of_the_repositorys_ledger_and_the_example_workflow_calls_it(tmp_path):
    """`knos attest --kind batch` as attest.yml runs it (knos.flow.attest), with GitHub's signature standing in: the
    token it puts out is the one the relay records. And the file a buyer or a seller installs asks for exactly that."""
    from knos import flow
    c = Meter()
    net = Net(c)
    month = meter.yyyymm(c.now())
    c.open(c.new_mint(), BUYER)
    b = L.batch([_ev(i) for i in range(4)], 0, month)
    file = tmp_path / "knos-ledger.jsonl"
    file.write_text(L.dump([b]), encoding="utf-8")
    assert {"batch", "claim"} <= set(flow.KINDS)
    for kind, owner, claims in (("batch", BUYER, dict(file="attest.yml", run_attempt=1)), ("claim", SELLER, dict(file="attest.yml", run_attempt=1))):
        asked: list[str] = []
        run = flow.Run("o/ledgers", {}, github=Repo(net, owner, {"knos-ledger.jsonl": file}).github, ledger=net,
                       mint=lambda aud: asked.append(aud) or token(c, aud, repository_owner_id=owner, **claims),  # noqa: B023
                       env={"GITHUB_REPOSITORY_OWNER_ID": str(owner), "GITHUB_RUN_ATTEMPT": "1"})
        assert flow.attest(run, "knos-ledger.jsonl", kind) == 0
        assert run.outputs["audience"] == L.batch_audience(b, claim=kind == "claim")
        r = relay.submit(net, c.payer, run.outputs["token"], None, JWKS, now=c.now())
        assert r["ok"] and (r["kind"], r["count"], r["fee"]) == (kind, 4, 0), r
        assert flow.attest(run, "knos-ledger.jsonl", kind) == 0 and len(asked) == 1        # nothing new: nothing signed, and the run does not fail
    assert meter.book(net, BUYER, SELLER, month).chain == meter.book(net, BUYER, SELLER, month, claim=True).chain == L.totals(L.load(file), month).chain

    examples = Path(__file__).resolve().parents[1] / "examples"
    text, attest = (examples / "knos-meter-batch.yml").read_text(encoding="utf-8"), (examples / "knos-attest.yml").read_text(encoding="utf-8")
    pin = re.search(r"uses: (\S+/attest\.yml@\w+)", attest).group(1)
    assert text.count(f"uses: {pin}") == 2 and "actions/checkout" not in text      # a batch is the pinned attest.yml, by timer or by hand, and nothing is checked out
    assert "run: knos meter close --sign close.json --as \"$AS\" --token token.jwt" in text            # the month's close, signed for one side by hand (tests/test_workflows2.py)
    assert "kind: ${{ vars.KNOS_METER_KIND || 'batch' }}" in text and "options: [batch, claim]" in text and "pull: 0" in text
    assert "schedule:" in text and "workflow_dispatch:" in text and "secrets" not in text.split("\nname:", 1)[1]
