"""The evidence bundle and the receipt mirror: a bundle is built from a (stand-in) chain and host, two builds of one
order are the same bytes, the verdict is derived again from the bundle alone, any changed file fails, and a receipt
is read from a mirror when the chain no longer has it."""
from __future__ import annotations

import base64
import io
import json
import tarfile

import pytest
from solders.pubkey import Pubkey
from typer.testing import CliRunner

from _settle import NOW, github_claims, modulus, sign_jwt, signing_key
from knos import bundle, chain, receipt, terms
from knos.settle.v2 import oidc
from knos.settle.v2 import pay as pay2

PAY, OIDC = str(pay2.PAY_ID), str(oidc.OIDC_ID)
REPO, ISSUE, PR, HEAD, SELLER = 987654321, 77, 12, "a" * 40, 5550123
TERMS = terms.canonical({"accept": "", "checks": [{"app": -1, "name": "build"}, {"app": 15368, "name": "test"}], "deny": list(terms.DENY), "mode": "merge",
                         "paths": ["src/**"], "reserve": 0, "v": 1})


def _addr(i: int) -> str:
    return str(Pubkey.from_bytes(bytes([i]) * 32))


def _sig(i: int) -> str:
    return chain.b58(bytes([i]) * 64)


ORDER, WALLET, RELAYER, MINT, FUNDER = _addr(11), _addr(12), _addr(13), _addr(14), _addr(15)


def _tx(at: int, slot: int, logs=(), ixs=()) -> dict:
    keys = sorted({PAY, OIDC, RELAYER} | {a for _, _, accounts in ixs for a in accounts})
    return {"slot": slot, "blockTime": at, "meta": {"err": None, "logMessages": [f"Program {PAY} invoke [1]", *(f"Program log: {line}" for line in logs),
                                                                                f"Program {PAY} success"]},
            "transaction": {"message": {"accountKeys": keys, "instructions": [{"programIdIndex": keys.index(p), "data": chain.b58(d),
                                                                               "accounts": [keys.index(a) for a in accounts]} for p, d, accounts in ixs]}}}


class Chain:
    """One funded order, topped up, then paid by a token a test key signed: the transactions a cluster would hold."""

    def __init__(self, bought: bytes = TERMS, mode: int = pay2.MERGE):
        key = signing_key()
        self.n = modulus(key)
        self.key = str(oidc.key_pda(oidc.GITHUB, self.n))
        aud = pay2.order_pay_audience(Pubkey.from_string(ORDER), HEAD, bytes.fromhex(terms.terms_hash(bought)), mode, PR, [(SELLER, 10_000, None)])
        self.token = sign_jwt(key, github_claims(aud=aud, repository_id=str(REPO)))
        tid = oidc.token_id(self.token)
        payer = Pubkey.from_string(RELAYER)
        self.token_account = str(oidc.token_pda(payer, tid))
        writes = [(OIDC, bytes(ix.data), [RELAYER, self.token_account]) for ix in oidc.write_ixs(payer, tid, self.token)]
        self.txs = {
            _sig(1): _tx(NOW - 900, 400, [f"knos3:funded order={ORDER} repo={REPO} issue={ISSUE} seq=0 amount=15000000 fee=375000 mode={mode} by=0 source={FUNDER} "
                                         f"flags=0 deadline={NOW + 86400}", "knos3:terms " + bought.decode()]),
            _sig(2): _tx(NOW - 600, 405, [f"knos3:topup order={ORDER} add=5000000 amount=20000000 fee=500000"]),
            **{_sig(10 + i): _tx(NOW + 1, 408 + i, ixs=[w]) for i, w in enumerate(writes)},
            _sig(30): _tx(NOW + 5, 411, ixs=[(OIDC, b"\x01" + tid + b"\x10", [RELAYER, self.token_account, self.key])]),
            _sig(40): _tx(NOW + 20, 412, [f"knos3:paid order={ORDER} pr={PR} payee={SELLER} amount=20000000 to={WALLET}",
                                         f"knos3:settled order={ORDER} paid=20000000 of=20000000 fee=200000 tip=300000 judge=0"],
                          ixs=[(PAY, b"\x11", [RELAYER, self.token_account, self.key, ORDER, _addr(21), _addr(22), _addr(23), _addr(24), _addr(25), MINT])])}
        self.of_token = [s for s, t in self.txs.items() if any(self.token_account in t["transaction"]["message"]["accountKeys"] and
                                                              t["transaction"]["message"]["accountKeys"][ix["programIdIndex"]] == OIDC
                                                              for ix in t["transaction"]["message"]["instructions"])]
        header = bytearray(oidc.K_HDR)
        header[0], header[2] = 1, 64
        self.accounts = {MINT: (bytes(44) + b"\x06" + bytes(37), "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
                         self.key: (bytes(header) + self.n.to_bytes(256, "big") + bytes(256), OIDC)}
        self.reset = False

    def events(self) -> list[dict]:
        from knos import records
        if self.reset:
            return []
        return [{**ev, "tx": sig} for sig in (_sig(1), _sig(2), _sig(40)) for ev in records.events_of(self.txs[sig])]

    def call(self, method: str, params: list):
        if method == "getGenesisHash":
            return "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
        if self.reset:
            return [] if method == "getSignaturesForAddress" else None if method == "getTransaction" else {"value": None}
        if method == "getTransaction":
            return self.txs.get(params[0])
        if method == "getSignaturesForAddress":
            return [{"signature": s, "err": None} for s in reversed(self.of_token)] if params[0] == self.token_account else []
        data, owner = self.accounts[params[0]]
        return {"value": {"data": [base64.b64encode(data).decode(), "base64"], "owner": owner}}


def host(shuffle: bool = False, build: str = "success", files=("src/a.py",)):
    """GitHub's API for the order's repository; `shuffle` gives the same facts in another order with other volatile fields."""
    runs = [{"id": 1, "name": "build", "status": "completed", "conclusion": build, "app": {"id": 15368, "slug": "github-actions"}, "details_url": "https://x/runs/1/job/1"},
            {"id": 2, "name": "test", "status": "completed", "conclusion": "success", "app": {"id": 15368}, "details_url": "https://x/runs/1/job/2"},
            {"id": 3, "name": "lint", "status": "completed", "conclusion": "failure", "app": {"id": 15368}, "details_url": "https://x/runs/1/job/3"}]
    if shuffle:
        runs = [{**r, "url": "https://api.github.com/other", "pull_requests": []} for r in reversed(runs)]

    def get(path: str):
        if path == f"repositories/{REPO}":
            return {"full_name": "octo/widgets"}
        if "/check-runs" in path:
            return {"total_count": len(runs), "check_runs": runs}
        if "/status" in path:
            return {"statuses": []}
        if f"/pulls/{PR}/files" in path:
            return [{"filename": f} for f in files]
        raise OSError(path)
    return get


@pytest.fixture(scope="module")
def net() -> Chain:
    return Chain()


@pytest.fixture(scope="module")
def built(net):
    r, files = bundle.gather(net.call, net.events(), ORDER, host())
    return r, files, bundle.make(files, r["order"])


def test_two_builds_of_one_order_are_the_same_bytes_and_the_verdict_follows_from_the_bundle_alone(net, built):
    r, files, blob = built
    again, files2 = bundle.gather(net.call, net.events(), _sig(40), host(shuffle=True))       # the other party, by the transaction, GitHub answering otherwise
    assert bundle.make(files2, again["order"]) == blob and again == r
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        members = tar.getmembers()
    assert [m.name for m in members] == sorted(["MANIFEST.json", "chain.json", *bundle.FILES]) and {(m.mtime, m.mode, m.uid, m.gid) for m in members} == {(0, 0o644, 0, 0)}
    got, done = bundle.verify(blob)                                # no network: `call` is not given
    assert got == r and receipt.check(r) is None and r["version"] == 4       # a receipt is written as version 4 wherever one is made
    assert receipt.authorises_payment(r) and r["ids"] == receipt.ids_of(r, r["commercial_authorisation"]["deliverable"]["milestone"])
    three = receipt.as3(r)
    assert three["version"] == 3 and receipt.check(three) is None and receipt.build4(three) == r   # and holds the version 3 one it was built from
    assert files["token.jwt"].decode().strip() == net.token and files["terms.json"] == TERMS
    assert json.loads(files["judge.json"])["inputs_sha256"] == bundle._sha(files["checks.json"])
    assert any("verdict follows again" in line for line in done) and "the chain was not asked" in done[-3]
    assert done[-2].startswith("assurance: none is claimed. In merge mode a maintainer's merge is the acceptance") and done[-1] == bundle.LIMIT
    online = bundle.verify(blob, net.call)[1]                      # with --rpc: the key's account and the paying transaction on chain
    assert "not revoked" in online[-3] and online[-2].startswith("the chain's record of the paying transaction shows these wallets") and bundle.LIMIT not in online
    # the receipt: four parts in order, the amendment with its transaction, the verifying transaction
    assert r["amendments"] == [{"kind": "topup", "transaction": _sig(2), "time": NOW - 600, "detail": {"add": "5000000", "amount": "20000000", "fee": "500000"}}]
    assert r["issuer_authenticated"]["verified"] == {"program": OIDC, "key": net.key, "transaction": _sig(30)}
    assert [c["name"] for c in r["evaluator_observed"]["checks"]] == ["build", "test"] and r["policy"]["allowed_paths"] == ["src/**"]
    text = "\n".join(receipt.render(r))
    at = [text.index(f"{i}. {receipt.HEADINGS[p]}") for i, p in enumerate(receipt.PARTS, 1)]
    assert at == sorted(at) and _sig(2) in text and "upgradeable only through a multisig with a public 48-hour delay" in text


def test_changing_any_file_fails_verify(built):
    r, files, blob = built
    # a byte of each file changed in place: the manifest no longer matches
    for name in bundle.FILES:
        at = blob.index(files[name]) + len(files[name]) // 2
        bad = blob[:at] + bytes([blob[at] ^ 1]) + blob[at + 1:]
        with pytest.raises(ValueError, match="manifest|not a bundle|cannot be read"):
            bundle.verify(bad)
    # each file changed and the manifest made again for it: what the file says no longer follows
    checks = json.loads(files["checks.json"])
    failed = {**checks, "check_runs": [{**c, "conclusion": "failure"} if c["name"] == "build" else c for c in checks["check_runs"]]}
    outside = {**checks, "changed_files": ["src/a.py", ".github/workflows/ci.yml"]}
    other = json.loads(files["receipt.json"])
    other["payees"][0]["to"] = FUNDER
    richer = json.loads(files["receipt.json"])
    richer["evaluator_observed"]["artifact"]["commit"] = "b" * 40
    richer["ids"] = receipt.ids_of(richer, richer["commercial_authorisation"]["deliverable"]["milestone"])     # with the ids its new fields give
    head, body, sig = files["token.jwt"].decode().strip().split(".")
    forged = sign_jwt(signing_key(4096), json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))))
    for name, data, why in (("checks.json", bundle._json(failed), "judge.json does not name"),
                            ("terms.json", files["terms.json"].replace(b"src/**", b"lib/**"), "terms.json is not what was hashed"),
                            ("token.jwt", forged.encode() + b"\n", "signature is not the included key's"),
                            ("key.json", bundle._json({**json.loads(files["key.json"]), "n": bundle._b64(modulus(signing_key(4096)).to_bytes(512, "big"))}), "signature is not"),
                            ("judge.json", bundle._json({**json.loads(files["judge.json"]), "version": "d" * 40}), "judge.json does not name"),
                            ("receipt.json", bundle._json(richer), "not signed for this order, commit"),
                            ("receipt.json", bundle._json(other), None)):
        if why is None:         # the wallet is not in the token (the payee bound it): the bundle holds, and the digest is no longer the mirror's or the chain's
            assert receipt.digest(bundle.verify(bundle.make({**files, name: data}, r["order"]))[0]) != receipt.digest(r)
            continue
        with pytest.raises(ValueError, match=why):
            bundle.verify(bundle.make({**files, name: data}, r["order"]))
    # the checks changed together with the judge's digest of them: the verdict itself no longer follows
    for doc, why in ((failed, "required check `build` failed"), (outside, "does not allow")):
        data = bundle._json(doc)
        judge = bundle._json({**json.loads(files["judge.json"]), "inputs_sha256": bundle._sha(data)})
        with pytest.raises(ValueError, match="verdict does not follow.*" + why):
            bundle.verify(bundle.make({**files, "checks.json": data, "judge.json": judge}, r["order"]))
    # a file more, a file less, a repacked tar
    with pytest.raises(ValueError, match="exactly"):
        bundle.make({**files, "extra.txt": b"x"}, r["order"])
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar, tarfile.open(fileobj=io.BytesIO(blob)) as src:
        for m in src.getmembers():
            data = src.extractfile(m).read()
            m.mtime = 1
            tar.addfile(m, io.BytesIO(data))
    with pytest.raises(ValueError, match="repacked"):
        bundle.verify(out.getvalue())
    with pytest.raises(ValueError, match="not a bundle"):
        bundle.verify(b"not a tar")


def test_no_bundle_is_made_when_the_verdict_does_not_follow_or_the_chain_is_gone(net):
    r, files = bundle.gather(net.call, net.events(), ORDER, host(build="failure"))
    with pytest.raises(ValueError, match="verdict does not follow"):
        bundle.verify(bundle.make(files, r["order"]))
    with pytest.raises(bundle.Unavailable):
        bundle.gather(net.call, net.events(), _addr(99), host())
    gone = Chain()
    gone.reset = True
    with pytest.raises(bundle.Unavailable):
        bundle.gather(gone.call, gone.events(), ORDER, host())


def test_the_payment_of_an_issues_bounty_is_named_for_what_it_is_and_no_bundle_is_made_of_it():
    """The first real run (0.3.15) on the public program ids, where every payment is an issue's bounty (knos2 lines):
    `knos bundle make` of knos-e2e issue 211's paying transaction said the history showed no payment of it."""
    paid_tx, keys = _sig(70), [RELAYER, _addr(71), PAY]
    events = [{"event": "funded", "v": 2, "at": NOW, "tx": _sig(69), "signer": RELAYER, "keys": keys, "repo": REPO, "issue": 211, "amount": 5_000_000,
               "mode": 0, "by": SELLER, "source": FUNDER, "faucet": 1},
              {"event": "paid", "v": 2, "at": NOW + 59, "tx": paid_tx, "signer": RELAYER, "keys": keys, "repo": REPO, "issue": 211, "payee": SELLER,
               "amount": 4_875_000, "fee": 125_000, "to": WALLET}]
    with pytest.raises(ValueError, match=rf"{paid_tx} is the payment of an issue's bounty \(repository id {REPO}, issue 211\), not of a work order"):
        bundle.gather(None, events, paid_tx, None)
    with pytest.raises(bundle.Unavailable, match="shows no payment"):     # what the history does not hold is still not there
        bundle.gather(None, events, _sig(72), None)

def test_the_mirror_is_deterministic_keeps_what_the_chain_lost_and_verify_reads_it(net, built, tmp_path, monkeypatch):
    from knos import cli
    r = built[0]
    got, left = bundle.receipts_of(net.call, net.events())
    assert got == [r] and left == []
    other = json.loads(json.dumps(r))
    other["order"], other["scope"], other["repository"] = _addr(31), pay2.scope_of(REPO, 78).hex(), {"id": REPO, "issue": 78}
    other["transaction"]["signature"], other["commercial_authorisation"]["deliverable"]["order"] = _sig(41), _addr(31)
    other["ids"] = receipt.ids_of(other, other["commercial_authorisation"]["deliverable"]["milestone"])
    a, b = tmp_path / "a", tmp_path / "b"
    receipt.mirror_write([r, other], a)
    receipt.mirror_write([other], b)
    receipt.mirror_write([r], b)             # in two runs and another order: the folder is the same, byte for byte
    receipt.mirror_write([], b)              # and a run that finds nothing on chain (a reset) keeps what is there
    assert sorted(f.name for f in a.iterdir()) == sorted(["index.json", f"{ORDER}.json", f"{_addr(31)}.json"])
    assert all((a / f.name).read_bytes() == f.read_bytes() for f in b.iterdir())
    index = json.loads((a / "index.json").read_text())
    assert index["orders"][ORDER] == [{"sha256": receipt.digest(r), "transaction": _sig(40), "time": NOW + 20, "cluster": "devnet"}]
    assert receipt.mirror_find(str(a), ORDER) == [r] == receipt.mirror_find(str(a), _sig(40)) and receipt.mirror_find(str(a), _addr(98)) == []
    served = receipt.mirror_find("https://example.org/receipts/", ORDER, get=lambda url: (a / url.rsplit("/", 1)[1]).read_bytes())
    assert served == [r]
    # the commands: from the chain while it has the record, from the mirror once it does not
    state = Chain()
    monkeypatch.setattr(bundle, "_caller", lambda rpc: ("http://test", state.call))
    monkeypatch.setattr(bundle, "_history", lambda url, limit: state.events())
    monkeypatch.setenv("KNOS_NO_SAS", "1")
    run = CliRunner()
    done = run.invoke(cli.app, ["receipt", "mirror", "--out", str(tmp_path / "c")])
    assert done.exit_code == 0 and "1 receipts of 1 orders" in done.output, done.output
    assert (tmp_path / "c" / f"{ORDER}.json").read_bytes() == (b / f"{ORDER}.json").read_bytes()
    live = run.invoke(cli.app, ["receipt", "verify", ORDER, "--mirror", str(a)])
    assert live.exit_code == 0 and "from the chain, and the mirror holds the same receipt" in live.output and receipt.FROM_MIRROR not in live.output
    state.reset = True
    again = run.invoke(cli.app, ["receipt", "mirror", "--out", str(tmp_path / "c")])
    assert again.exit_code == 0 and "1 receipts of 1 orders (0 from the chain now)" in again.output
    lost = run.invoke(cli.app, ["receipt", "verify", ORDER, "--mirror", str(tmp_path / "c")])
    assert lost.exit_code == 0 and receipt.FROM_MIRROR == "from mirror, chain record unavailable" and receipt.FROM_MIRROR in lost.output
    assert f"1. {receipt.HEADINGS['issuer_authenticated']}" in lost.output and receipt.digest(r) in lost.output
    none = run.invoke(cli.app, ["receipt", "verify", ORDER])
    assert none.exit_code == 1 and "Give --mirror" in none.output
    # a mirror whose file was changed is refused, not believed
    doc = json.loads((a / f"{ORDER}.json").read_text())
    doc["receipts"][0]["payees"][0]["to"] = FUNDER
    (a / f"{ORDER}.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="not the one its index lists"):
        receipt.mirror_find(str(a), ORDER)
    bad = run.invoke(cli.app, ["receipt", "verify", ORDER, "--mirror", str(a)])
    assert bad.exit_code == 1 and "not the one its index lists" in bad.output


def test_the_bundle_commands_write_and_check_a_file(net, built, tmp_path, monkeypatch):
    from knos import cli, judge
    monkeypatch.setattr(bundle, "_caller", lambda rpc: ("http://test", net.call))
    monkeypatch.setattr(bundle, "_history", lambda url, limit: net.events())
    monkeypatch.setattr(judge, "github", host())
    monkeypatch.setattr(bundle, "published_keys", lambda issuer: None)      # no network in a test: tests/test_receipt_offline.py archives a key list
    run, path = CliRunner(), tmp_path / "order.tar"
    made = run.invoke(cli.app, ["bundle", "make", ORDER, "--out", str(path)])
    assert made.exit_code == 0 and path.read_bytes() == built[2], made.output
    ok = run.invoke(cli.app, ["bundle", "verify", str(path)])
    assert ok.exit_code == 0 and "verified. bundle sha256:" + bundle._sha(built[2]) in ok.output
    assert all(f"{i}. {receipt.HEADINGS[p]}" in ok.output for i, p in enumerate(receipt.PARTS, 1))
    path.write_bytes(built[2].replace(b"src/a.py", b"src/b.py"))
    bad = run.invoke(cli.app, ["bundle", "verify", str(path)])
    assert bad.exit_code == 1 and "not verified" in bad.output and "verified. bundle" not in bad.output


# ---- the wallet paid: in no signed token, so it is checked against the chain's record or a mirror, and said when it is not ----
def _repacked(files: dict, r: dict) -> bytes:
    """What someone who edits the receipt and rebuilds the manifest hands over."""
    return bundle.make({**files, "receipt.json": bundle._json(r)}, r["order"])


def test_a_receipt_that_names_another_wallet_passes_offline_with_the_limit_said_and_fails_against_the_chain_or_a_mirror(net, built, tmp_path):
    r, files, _ = built
    thief = {**r, "payees": [{**r["payees"][0], "to": _addr(99)}]}
    assert receipt.check(thief) is None
    forged = _repacked(files, thief)
    got, done = bundle.verify(forged)                               # offline: nothing signed names the wallet, and the last line says so
    assert got["payees"][0]["to"] == _addr(99) and done[-1] == bundle.LIMIT and "still passes offline" in bundle.LIMIT
    with pytest.raises(ValueError, match="wallets or amounts in the receipt are not the ones the chain's record"):
        bundle.verify(forged, net.call)
    less = {**r, "amounts": {**r["amounts"], "fee": "1"}}
    with pytest.raises(ValueError, match="amounts in the receipt are not the ones the chain's record"):
        bundle.verify(_repacked(files, less), net.call)
    receipt.mirror_write([r], tmp_path)
    with pytest.raises(ValueError, match="does not hold this receipt for the paying transaction"):
        bundle.verify(forged, mirror=str(tmp_path))
    done = bundle.verify(built[2], mirror=str(tmp_path))[1]
    assert f"the mirror at {tmp_path} holds the same receipt" in done[-2] and bundle.LIMIT not in done
    gone = Chain()
    gone.txs.pop(_sig(40))                                           # the cluster was reset: the comparison is refused, never skipped
    with pytest.raises(ValueError, match="no longer has the paying transaction"):
        bundle.verify(built[2], gone.call)


def test_a_bundle_made_on_another_deployment_is_refused_as_that_and_not_as_a_changed_receipt(net, built, monkeypatch):
    # 0.3.17, track F: a real bundle made on the staging ids, verified without KNOS_PROGRAM_IDS, was refused with "the receipt was
    # changed" although no byte of it was. The escrow it names is not the one this knos reads: that is what is said now.
    from knos import records
    r, _files, blob = built
    assert bundle.verify(blob, net.call)[0]["program"] == PAY
    monkeypatch.setattr(records, "PROGRAMS", {_addr(98): 2})        # this knos reads another deployment's escrow
    with pytest.raises(ValueError, match="the receipt names the escrow program .* made on another deployment") as why:
        bundle.verify(blob, net.call)
    assert "was changed" not in str(why.value) and r["program"] in str(why.value) and "KNOS_PROGRAM_IDS" in str(why.value)


# ---- the judge's verdict in the bundle: one layout for `knos bundle verify` and `knos judge rerun` -----------------------------
IMAGE = "ghcr.io/acme/judge@sha256:" + "ab" * 32
ACCEPT = "5d" * 32
TESTS = terms.canonical({"accept": ACCEPT, "checks": [{"app": 15368, "name": "test"}], "deny": list(terms.DENY), "image": IMAGE, "mode": "tests", "paths": [],
                         "reserve": 0, "v": 1})


def _verdict(**over) -> dict:
    v = {"passed": True, "checks_hash": ACCEPT, "reasons": [], "assurance": "hermetic", "assurance_means": terms.ASSURANCE["hermetic"],
         "evidence": {"issue": "77", "runner": "blackbox", "artifact": {"base": "1" * 64, "pr": "2" * 64},
                      "image": {"ref": IMAGE, "digest": "sha256:" + "ab" * 32, "limits": {"memory": "512m"}}}}
    return {**v, **over}


def test_a_bundle_carries_the_judges_verdict_and_verify_prints_its_assurance(tmp_path, monkeypatch):
    from knos import cli, judge
    net = Chain(TESTS, pay2.TESTS)
    r, files = bundle.gather(net.call, net.events(), ORDER, host())
    plain = bundle.verify(bundle.make(files, r["order"]))[1]        # tests mode with no verdict: the bundle does not say how the checks ran
    assert plain[-2].startswith("assurance: not said by this bundle. It holds no verdict.json") and f"the terms name the image `{IMAGE}`" in plain[-2]
    with_verdict = {**files, "verdict.json": bundle._json(_verdict())}
    blob = bundle.make(with_verdict, r["order"])
    assert blob == bundle.make(dict(reversed(list(with_verdict.items()))), r["order"]) and set(bundle.read(blob)) == {*bundle.FILES, "chain.json", "verdict.json"}
    done = bundle.verify(blob)[1]
    assert done[0] == "every file is the one the manifest lists (8 files)"
    assert done[-2] == f"assurance: hermetic, in `{IMAGE}`. {terms.ASSURANCE['hermetic']}" and "signed by nobody" in done[-3] and "base 1111111111111111" in done[-3]
    # a verdict on other checks, in another image, with an image the terms do not name, or one that did not pass, is not this order's
    for bad, why in ((_verdict(checks_hash="6e" * 32), "other acceptance checks than the ones hashed at funding"),
                     (_verdict(evidence={**_verdict()["evidence"], "image": {"ref": IMAGE[:-1] + "c", "digest": "sha256:" + "cc" * 32}}), "does not name the image the terms name"),
                     (_verdict(assurance="black-box"), "does not name the image the terms name"),
                     (_verdict(passed=False), "is not a passed verdict"),
                     (_verdict(evidence={"issue": "77"}), "is not a passed verdict")):
        with pytest.raises(ValueError, match=why):
            bundle.verify(bundle.make({**files, "verdict.json": bundle._json(bad)}, r["order"]))
    with pytest.raises(ValueError, match="is not a passed verdict in canonical form"):
        bundle.verify(bundle.make({**files, "verdict.json": json.dumps(_verdict(), indent=1).encode()}, r["order"]))
    merge = Chain()                                                  # a merge-mode order has no judge's verdict to carry
    r2, files2 = bundle.gather(merge.call, merge.events(), ORDER, host())
    with pytest.raises(ValueError, match="other acceptance checks"):
        bundle.verify(bundle.make({**files2, "verdict.json": bundle._json(_verdict())}, r2["order"]))
    with pytest.raises(ValueError, match="a bundle holds exactly"):
        bundle.make({**files, "source.tar": b"x"}, r["order"])
    # the commands: make --verdict keeps the judge's file, verify prints the assurance line and the limit, rerun reads the same tar
    monkeypatch.setattr(bundle, "_caller", lambda rpc: ("http://test", net.call))
    monkeypatch.setattr(bundle, "_history", lambda url, limit: net.events())
    monkeypatch.setattr(judge, "github", host())
    monkeypatch.setattr(bundle, "published_keys", lambda issuer: None)      # no network in a test
    run, path, file = CliRunner(), tmp_path / "order.tar", tmp_path / "verdict.json"
    file.write_text(json.dumps(_verdict(), indent=1), encoding="utf-8")
    made = run.invoke(cli.app, ["bundle", "make", ORDER, "--out", str(path), "--verdict", str(file)])
    assert made.exit_code == 0 and path.read_bytes() == blob, made.output
    ok = run.invoke(cli.app, ["bundle", "verify", str(path)])
    assert ok.exit_code == 0 and f"\nassurance: hermetic, in `{IMAGE}`. " in ok.output and "\nlimit: the wallets paid and the amounts are the receipt's word here." in ok.output
    online = run.invoke(cli.app, ["bundle", "verify", str(path), "--rpc", "http://test"])
    assert online.exit_code == 0 and "limit:" not in online.output and "checked: the chain's record of the paying transaction" in online.output
    assert judge.load_verdict(path) == (_verdict(), None)
    asked = []
    monkeypatch.setattr(judge, "rerun", lambda first, base, pr, cfg, sandbox: asked.append((first, base, pr)) or {"agree": True, "differences": [], "again": first})
    again = run.invoke(cli.app, ["judge", "rerun", str(path), "--base", str(tmp_path), "--pr", str(tmp_path)])
    assert again.exit_code == 0 and asked == [(_verdict(), tmp_path, tmp_path)] and "agree: passed both times" in again.output, again.output
    # the bundle holds no source: without the two checkouts, rerun says which commit to fetch
    bare = run.invoke(cli.app, ["judge", "rerun", str(path)])
    assert bare.exit_code != 0 and f"check out commit {HEAD} (pull request #{PR}) for --pr" in str(bare.exception)
    no_verdict = tmp_path / "merge.tar"
    no_verdict.write_bytes(bundle.make(files2, r2["order"]))
    none = run.invoke(cli.app, ["judge", "rerun", str(no_verdict), "--base", str(tmp_path), "--pr", str(tmp_path)])
    assert none.exit_code != 0 and "this bundle holds no verdict.json" in str(none.exception)
