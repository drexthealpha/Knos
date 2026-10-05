"""Verification with the chain gone. An order is funded from an organisation's Balance and paid on the LiteSVM harness
(knos_pay and knos_oidc as built), its evidence bundle is made from what that chain gives, the harness is thrown away,
and `verify_offline` (`knos bundle verify --no-chain`) checks the bundle with no cluster: what signatures prove, what
rests on the archived copy of the chain record, and what only a cluster could show. Then each archived piece is
changed in turn and the check names what fails."""
from __future__ import annotations

import base64
import gc
import hashlib
import io
import json
import tarfile

import pytest

pytest.importorskip("solders.litesvm")

from typer.testing import CliRunner  # noqa: E402

from _order import AUTHOR, MAINT, OWNER, REPO, USDC, OrderChain, issue  # noqa: E402
from _settle import NOW, modulus, signing_key  # noqa: E402

from knos import bundle, chain, receipt, records, terms  # noqa: E402
from knos.settle.v2 import oidc, pay  # noqa: E402

PR, DAY_LIMIT, TOTAL_LIMIT = 7, 500 * USDC, 5_000 * USDC
TERMS = terms.canonical({"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": list(terms.DENY), "mode": "merge", "paths": ["src/**"], "reserve": 0,
                         "v": 1})
GITHUB = "https://token.actions.githubusercontent.com"
FETCHED = NOW + 3600        # when the issuer's key list was retrieved: a fixed time, so the bundle's bytes are the same on every run


class Recorded(OrderChain):
    """The order harness, keeping every transaction it lands the way a cluster's getTransaction gives one: its logs,
    its instructions and accounts, its slot, block time and blockhash. `call` is that cluster's JSON-RPC."""

    def __init__(self):
        self.txs: dict[str, dict] = {}
        self.named: dict[str, list[str]] = {}
        super().__init__()

    def send(self, ixs, payer=None, signers=(), tag=None, mark=True):
        final = [self.marked(ix) for ix in ixs] if mark else list(ixs)
        recent, slot = str(self.svm.latest_blockhash()), int(self.svm.get_clock().slot)
        ok = super().send(final, payer, signers, tag, mark=False)
        if ok:
            sig = chain.b58(hashlib.sha512(f"offline-test-{len(self.txs)}".encode()).digest())
            keys = sorted({str((payer or self.payer).pubkey())} | {str(ix.program_id) for ix in final} | {str(a.pubkey) for ix in final for a in ix.accounts})
            self.txs[sig] = {"slot": slot, "blockTime": self.now(), "meta": {"err": None, "logMessages": list(self.logs)},
                             "transaction": {"message": {"recentBlockhash": recent, "accountKeys": keys, "instructions": [
                                 {"programIdIndex": keys.index(str(ix.program_id)), "data": chain.b58(bytes(ix.data)),
                                  "accounts": [keys.index(str(a.pubkey)) for a in ix.accounts]} for ix in final]}}}
            for k in keys:
                self.named.setdefault(k, []).append(sig)
        return ok

    def events(self) -> list[dict]:
        return [{**ev, "tx": sig} for sig, tx in self.txs.items() for ev in records.events_of(tx)]

    def call(self, method: str, params: list):
        if method == "getGenesisHash":
            return "a LiteSVM chain has no genesis a cluster knows"
        if method == "getTransaction":
            return self.txs.get(params[0])
        if method == "getSignaturesForAddress":
            return [{"signature": s, "err": None} for s in reversed(self.named.get(params[0], []))]
        if method == "getBlock":
            return {"blockhash": chain.b58(hashlib.sha256(f"block-{params[0]}".encode()).digest())}
        data = self.data(params[0] if not isinstance(params[0], str) else pay.Pubkey.from_string(params[0]))
        if data is None:
            return {"value": None}
        owner = self.svm.get_account(pay.Pubkey.from_string(params[0])).owner
        return {"value": {"data": [base64.b64encode(data).decode(), "base64"], "owner": str(owner)}}


def host(path: str):
    """GitHub's API for the order's repository at the accepted commit."""
    if path == f"repositories/{REPO}":
        return {"full_name": "octo/widgets"}
    if "/check-runs" in path:
        return {"total_count": 1, "check_runs": [{"id": 2, "name": "test", "status": "completed", "conclusion": "success", "app": {"id": 15368},
                                                  "details_url": "https://x/runs/1/job/2"}]}
    if "/status" in path:
        return {"statuses": []}
    if f"/pulls/{PR}/files" in path:
        return [{"filename": "src/a.py"}]
    raise OSError(path)


def jwks(*keys) -> bytes:
    """The key list an issuer serves: the test key under the id its tokens name, and any others."""
    return json.dumps({"keys": [{"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid, "n": bundle._b64(n.to_bytes((n.bit_length() + 7) // 8, "big")), "e": "AQAB"}
                                for kid, n in keys]}).encode()


TEST_KEY = ("k", modulus(signing_key()))
OTHER_KEY = ("rotated-in", modulus(signing_key(4096)))


_published = bundle.published_keys      # the function itself: a test below puts a stand-in in its place


def published(*keys, at: int = FETCHED):
    return lambda issuer: _published(issuer, fetch=lambda url: jwks(*keys), now=lambda: at)


@pytest.fixture(scope="module")
def made():
    """(the receipt, the bundle's files, the bundle) of an order built and paid on the harness. The harness is gone when
    this returns: nothing below can ask it anything."""
    c = Recorded()
    assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, DAY_LIMIT, TOTAL_LIMIT, [REPO])], c.owner), c.err
    order = c.fund_balance(issue(), terms=TERMS)        # the maintainer's signed comment spends the owner's Balance
    wallet = c.fund().pubkey()
    c.warp(60)
    assert c.pay(order, [(AUTHOR, 10_000, wallet)], pr=PR, actor_id=MAINT), c.err
    r, files = bundle.gather(c.call, c.events(), str(order), host, published(TEST_KEY, OTHER_KEY))
    blob = bundle.make(files, r["order"])
    again = bundle.gather(c.call, c.events(), r["transaction"]["signature"], host, published(OTHER_KEY, TEST_KEY))      # the other party builds its own
    assert bundle.make(again[1], again[0]["order"]) == blob
    assert bundle.verify(blob, c.call)[1][-2:] == ["the chain's record of the paying transaction shows these wallets paid these amounts, this fee and this tip",
                                                   "assurance: none is claimed. In merge mode a maintainer's merge is the acceptance, and no judge ran the pull request's code."]
    paid = c.balance(pay.ata(wallet, c.usdc))
    del c
    gc.collect()
    return r, files, blob, paid


def repack(files: dict, r: dict, **changed) -> bytes:
    """The bundle with some files changed and its manifest rebuilt: what someone who edits a bundle hands over."""
    return bundle.make({**files, **{name.replace("_", "."): data for name, data in changed.items()}}, r["order"])


def doc(files: dict, name: str) -> dict:
    return json.loads(files[name])


def test_the_receipt_built_on_the_harness_records_the_funding_and_the_judge(made):
    r, files, _blob, paid = made
    assert receipt.check(r) is None and r["version"] == 3 and r["cluster"] == "localnet" and int(r["amounts"]["paid"]) == paid == 20 * USDC
    part = r["commercial_authorisation"]
    assert part["funder"] == {"github_id": MAINT, "login": "mona", "wallet": None}          # the id the chain logged, the login its funding token carried
    assert part["source"]["kind"] == "balance" and part["source"]["owner_id"] == OWNER and part["role"] == "spender"
    assert part["limit"] == {"cap_per_order": "0", "daily": str(DAY_LIMIT), "total": str(TOTAL_LIMIT), "repositories": [REPO]}        # from the side account's own line
    assert part["deliverable"] == {"order": r["order"], "milestone": 0} and part["billed_before"] is False and part["funded"]
    seen = r["evaluator_observed"]
    assert seen["evaluators"] == [{"kind": "repository", "repository_id": REPO, "owner_id": OWNER, "actor_id": MAINT, "runner": "github-hosted",
                                   "independent_of_buyer": False, "independent_of_seller": True}]
    assert seen["same_controller"] is False and seen["independence"] == receipt.ONE_JUDGE
    arch = doc(files, "chain.json")
    assert arch["type"] == bundle.CHAIN_ARCHIVE and arch["payment"]["signature"] == r["transaction"]["signature"] and arch["payment"]["slot"] == r["transaction"]["slot"]
    assert arch["payment"]["blockhash"] and arch["funding"]["signature"] == part["funded"] and arch["verified"]["signature"] == r["issuer_authenticated"]["verified"]["transaction"]
    assert any(f"knos3:paid order={r['order']}" in line for line in arch["payment"]["transaction"]["meta"]["logMessages"])
    keys = doc(files, "keys.json")
    assert keys["retrieved_at"] == FETCHED and keys["url"] == bundle.KEY_LISTS[GITHUB] and [k["kid"] for k in keys["keys"]] == ["k", "rotated-in"]
    with tarfile.open(fileobj=io.BytesIO(made[2])) as tar:          # a bundle with the archives says version 2 in its manifest
        assert json.loads(tar.extractfile("MANIFEST.json").read())["version"] == 2


def test_with_the_chain_gone_the_bundle_says_what_signatures_prove_what_is_an_archived_copy_and_what_needs_a_cluster(made):
    r, files, blob, _ = made
    got, out, said = bundle.verify_offline(blob)                    # no cluster, no network
    assert got == r and set(out) == {"signatures", "archive", "unchecked"}
    signed, copy, unchecked = out["signatures"], out["archive"], out["unchecked"]
    assert signed == ["the token carries the RS256 signature of the included key",
                      f"that key is the one knos_oidc holds at {r['issuer_authenticated']['verified']['key']} (the address is derived from the key)",
                      "the token names this order, this commit, these terms and these payees",
                      "terms.json is the terms fixed at funding (its sha256 is the terms hash)",
                      "the verdict itself is the issuer's signature: the pinned workflow asks for this token only after it accepted, for this order and artifact"]
    arch = doc(files, "chain.json")
    assert copy[0] == "every file is the one the manifest lists (8 files)" and copy[1].startswith("the verdict follows again: 1 named checks passed")
    assert copy[2] == (f"the signing key (id k) is in the list of keys {GITHUB} published at {bundle.KEY_LISTS[GITHUB]}, as archived in keys.json when it was "
                       f"retrieved on {bundle._utc(FETCHED)} (archived copy: the issuer was not asked or could not be reached)")
    assert copy[3] == (f"the archived copy of the paying transaction {r['transaction']['signature']} (slot {r['transaction']['slot']}, blockhash "
                       f"{arch['payment']['blockhash']}, fetched from localnet) logged these wallets paid these amounts, this fee and this tip")
    assert copy[4] == "the archived copy of the verifier's key account held this key, not revoked, when it was fetched"
    assert copy[5].startswith(f"the archived funding transaction {arch['funding']['signature']} (slot {arch['funding']['slot']}) logged this funder and this source")
    assert "the limit, the funder's role and billed_before are the receipt's word" in copy[5] and len(copy) == 6
    assert unchecked == list(bundle.NO_CLUSTER) and "signed by nobody" in unchecked[0] and "single-use marker" in unchecked[2]
    assert said == ["assurance: none is claimed. In merge mode a maintainer's merge is the acceptance, and no judge ran the pull request's code."]
    lines = bundle.offline_lines(out, said)
    at = [lines.index(bundle.HEADS[k]) for k in ("signatures", "archive", "unchecked")]
    assert at == sorted(at) and lines[-1].startswith("assurance: ")


def test_the_issuer_s_live_key_list_is_used_when_the_network_is_there_and_a_rotated_key_falls_back_to_the_archive(made):
    r, files, blob, _ = made
    live = bundle.verify_offline(blob, published(TEST_KEY, at=FETCHED + 86_400))[1]          # the issuer still serves the key
    assert f"the signing key (id k) is in the list of keys {GITHUB} serves now at {bundle.KEY_LISTS[GITHUB]}" in live["signatures"]
    assert any("as archived in keys.json" in line and "archived copy:" not in line for line in live["archive"])
    rotated = bundle.verify_offline(blob, published(OTHER_KEY))[1]                              # old keys rotate out
    assert not any("serves now" in line for line in rotated["signatures"])
    at = rotated["archive"].index(f"{GITHUB} no longer serves the signing key (id k): an issuer's keys rotate out. The archived list is used instead")
    assert "as archived in keys.json when it was retrieved on" in rotated["archive"][at + 1]
    assert bundle.verify_offline(blob, lambda issuer: None)[1] == bundle.verify_offline(blob)[1]          # the network is not there: the archive, labelled
    # the live list names the key's id with another key: that is a failure, not a rotation
    with pytest.raises(ValueError, match="serves now names the key id k with another key"):
        bundle.verify_offline(blob, published(("k", OTHER_KEY[1])))
    # a bundle made after the key rotated out archives a list without it: said, with what is left
    late = repack(files, r, keys_json=bundle._json(published(OTHER_KEY)(GITHUB)))
    out = bundle.verify_offline(late, published(OTHER_KEY))[1]
    assert any("it is not in the list archived on" in line and "the verifier's key account, in the archived chain record" in line for line in out["unchecked"])
    # a bundle of before the archives (no chain.json, no keys.json) still verifies: every chain statement is unchecked
    bare = bundle.make({k: v for k, v in files.items() if k not in bundle.ARCHIVES}, r["order"])
    out = bundle.verify_offline(bare)[1]
    assert any("this bundle archives no list of its keys" in line for line in out["unchecked"]) and any("holds no archived copy of the chain record" in line for line in out["unchecked"])
    assert _published(GITHUB, fetch=lambda url: (_ for _ in ()).throw(OSError("no network"))) is None and _published("https://example.org") is None


def _receipt(files: dict, edit) -> bytes:
    r = doc(files, "receipt.json")
    edit(r)
    return bundle._json(r)


def _chain(files: dict, edit) -> bytes:
    arch = doc(files, "chain.json")
    edit(arch)
    return bundle._json(arch)


def test_every_archived_piece_changed_in_turn_is_named(made):
    r, files, blob, _ = made
    assert set(files) == {*bundle.FILES, "chain.json", "keys.json"}
    # 1. a byte of any file changed, the manifest left as it was: the manifest names the file
    for name, data in sorted(files.items()):
        at = blob.index(data) + len(data) // 2
        bad = blob[:at] + bytes([blob[at] ^ 1]) + blob[at + 1:]
        with pytest.raises(ValueError, match=f"{name} is not the file the manifest lists"):
            bundle.verify_offline(bad)
    # 2. a file changed and the manifest rebuilt: the check that reads it names what no longer holds
    head, body, sig = files["token.jwt"].decode().strip().split(".")
    claims = json.loads(bundle._unb64(body))
    forged = ".".join([head, bundle._b64(json.dumps({**claims, "actor_id": "1"}, separators=(",", ":")).encode()), sig]).encode() + b"\n"
    other_n = bundle._b64(OTHER_KEY[1].to_bytes(512, "big"))
    wallet2, sig2 = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi", r["commercial_authorisation"]["funded"]

    def pays_another(x):
        x["payees"][0]["to"] = wallet2

    def funded_by_another(x):
        x["commercial_authorisation"]["funder"]["github_id"] = OWNER
        x["commercial_authorisation"]["role"] = "owner"

    def logs(old: str, new: str):
        def edit(arch):
            tx = arch["payment"]["transaction"]["meta"]
            assert any(old in line for line in tx["logMessages"])
            tx["logMessages"] = [line.replace(old, new) for line in tx["logMessages"]]
        return edit

    def slot(arch):
        arch["payment"]["slot"] += 1

    def key_account(arch):
        data = bytearray(base64.b64decode(arch["key_account"]["data"]))
        data[oidc.K_HDR + 5] ^= 1
        arch["key_account"]["data"] = base64.b64encode(bytes(data)).decode()

    def no_funding(arch):
        arch["funding"]["signature"] = sig2[:-2] + ("11" if not sig2.endswith("11") else "22")

    def keys_swapped() -> bytes:
        listed = doc(files, "keys.json")
        listed["keys"][0]["n"] = other_n
        return bundle._json(listed)

    failed_checks = bundle._json({**doc(files, "checks.json"), "changed_files": [".github/workflows/x.yml"]})
    cases = [
        ("token.jwt: another claim under the old signature", dict(token_jwt=forged), "the token's signature is not the included key's"),
        ("key.json: another key", dict(key_json=bundle._json({**doc(files, "key.json"), "n": other_n})), "the token's signature is not the included key's"),
        ("keys.json: the key's id with another key", dict(keys_json=keys_swapped()), "keys.json names the key id k with another key"),
        ("keys.json: not a key list", dict(keys_json=bundle._json({"type": "x"})), "keys.json is not the archived list"),
        ("terms.json: other terms", dict(terms_json=files["terms.json"].replace(b"src/**", b"**")), "terms.json is not what was hashed at funding"),
        ("receipt.json: another commit", dict(receipt_json=_receipt(files, lambda x: x["evaluator_observed"]["artifact"].update(commit="b" * 40))),
         "its audience says otherwise"),
        ("receipt.json: another wallet paid", dict(receipt_json=_receipt(files, pays_another)),
         "chain.json: the wallets or amounts in the receipt are not the ones the chain's record of the paying transaction shows"),
        ("receipt.json: another funder", dict(receipt_json=_receipt(files, funded_by_another)),
         "the funder or the source of the money in the receipt is not what the archived funding transaction logged"),
        ("checks.json: other check conclusions", dict(checks_json=failed_checks), "judge.json does not name this judge, its version and these checks"),
        ("checks.json and judge.json: a file outside the allowed paths",
         dict(checks_json=failed_checks, judge_json=bundle._json({**doc(files, "judge.json"), "inputs_sha256": hashlib.sha256(failed_checks).hexdigest()})),
         "the verdict does not follow from the bundle"),
        ("chain.json: another amount logged", dict(chain_json=_chain(files, logs("amount=20000000", "amount=20000001"))),
         "chain.json: the wallets or amounts in the receipt are not the ones"),
        ("chain.json: another fee logged", dict(chain_json=_chain(files, logs(f"fee={r['amounts']['fee']} ", "fee=1 "))), "chain.json: the amounts in the receipt are not the ones"),
        ("chain.json: another slot", dict(chain_json=_chain(files, slot)), "chain.json's paying transaction is not the one the receipt names"),
        ("chain.json: another key in the key account", dict(chain_json=_chain(files, key_account)), "chain.json: the chain's archived record of the key at"),
        ("chain.json: another funding transaction", dict(chain_json=_chain(files, no_funding)), "chain.json's funding transaction is not the one the receipt names"),
        ("chain.json: another cluster", dict(chain_json=_chain(files, lambda a: a.update(cluster="devnet"))), "chain.json was fetched from another cluster"),
        ("chain.json: not an archive", dict(chain_json=bundle._json({"type": "x"})), "chain.json is not an archived chain record"),
    ]
    for name, changed, why in cases:
        with pytest.raises(ValueError) as said:
            bundle.verify_offline(repack(files, r, **changed))
        assert why in str(said.value), (name, str(said.value))
    # 3. what no offline check can catch, and is said: the wallet rewritten in the receipt AND in the archive, the manifest rebuilt
    both = repack(files, r, receipt_json=_receipt(files, pays_another),
                  chain_json=_chain(files, logs(f"to={r['payees'][0]['to']}", f"to={wallet2}")))
    got, out, _ = bundle.verify_offline(both)
    assert got["payees"][0]["to"] == wallet2 and "Whoever rebuilds a bundle can rewrite the archive together with the receipt" in out["unchecked"][0]
    assert hashlib.sha256(both).hexdigest() != hashlib.sha256(blob).hexdigest()         # the other party's copy has another sha256
    # the blockhash is recorded as fetched and signed by nobody: changing it alone changes the bundle's sha256 and nothing else
    assert bundle.verify_offline(repack(files, r, chain_json=_chain(files, lambda a: a["payment"].update(blockhash="1" * 32))))[0] == r


def test_a_mirror_holds_the_receipt_against_a_rewritten_bundle_with_no_cluster(made, tmp_path):
    r, files, blob, _ = made
    receipt.mirror_write([r], tmp_path / "mirror")
    out = bundle.verify_offline(blob, mirror=str(tmp_path / "mirror"))[1]
    assert out["archive"][-1] == f"the mirror at {tmp_path / 'mirror'} holds the same receipt for the paying transaction"
    wallet2 = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"

    def pays_another(x):
        x["payees"][0]["to"] = wallet2
    arch = doc(files, "chain.json")
    meta = arch["payment"]["transaction"]["meta"]
    meta["logMessages"] = [line.replace(f"to={r['payees'][0]['to']}", f"to={wallet2}") for line in meta["logMessages"]]
    both = repack(files, r, receipt_json=_receipt(files, pays_another), chain_json=bundle._json(arch))
    assert bundle.verify_offline(both)[0]["payees"][0]["to"] == wallet2
    with pytest.raises(ValueError, match="does not hold this receipt for the paying transaction"):
        bundle.verify_offline(both, mirror=str(tmp_path / "mirror"))


def test_the_commands_verify_with_no_chain_and_ask_no_cluster(made, tmp_path, monkeypatch):
    from knos import cli
    r, _files, blob, _ = made
    path = tmp_path / "order.bundle.tar"
    path.write_bytes(blob)

    def no_cluster(rpc):
        raise AssertionError("--no-chain asked a cluster")
    monkeypatch.setattr(bundle, "_caller", no_cluster)
    monkeypatch.setattr(bundle, "published_keys", published(OTHER_KEY))         # the network is there, and the key has rotated out
    run = CliRunner()
    for args in (["bundle", "verify", str(path), "--no-chain"], ["receipt", "verify", str(path), "--no-chain"]):
        ok = run.invoke(cli.app, args)
        assert ok.exit_code == 0, ok.output
        text = ok.output
        at = [text.index(f"{i}. {receipt.HEADINGS[p]}") for i, p in enumerate(receipt.PARTS, 1)]
        at += [text.index(bundle.HEADS[k]) for k in ("signatures", "archive", "unchecked")]
        assert at == sorted(at) and len(at) == 8
        assert "no longer serves the signing key (id k): an issuer's keys rotate out. The archived list is used instead" in text
        assert f"blockhash {json.loads(_files['chain.json'])['payment']['blockhash']}" in text and "  - that a cluster holds the paying transaction at that slot" in text
        assert text.rstrip().endswith(f"verified with no cluster. bundle sha256:{hashlib.sha256(blob).hexdigest()}")
        assert "Funded by GitHub account 555000 (mona, as its funding token named it)" in text and "trusted: GitHub's signing key and runner" in text
    offline = run.invoke(cli.app, ["bundle", "verify", str(path), "--no-chain", "--no-network"])
    assert offline.exit_code == 0 and "(archived copy: the issuer was not asked or could not be reached)" in offline.output and "rotate out" not in offline.output
    path.write_bytes(blob[:-600] + b"x" + blob[-599:])
    bad = run.invoke(cli.app, ["bundle", "verify", str(path), "--no-chain", "--no-network"])
    assert bad.exit_code == 1 and bad.output.startswith("not verified: ")
    both = run.invoke(cli.app, ["bundle", "verify", str(path), "--no-chain", "--rpc", "http://x"])
    assert both.exit_code == 2 and "--no-chain asks no cluster" in both.output
    # the receipt alone, from a mirror, with no cluster
    receipt.mirror_write([r], tmp_path / "mirror")
    held = run.invoke(cli.app, ["receipt", "verify", r["order"], "--no-chain", "--mirror", str(tmp_path / "mirror")])
    assert held.exit_code == 0 and f"{receipt.FROM_MIRROR}: no cluster was asked." in held.output and receipt.digest(r) in held.output
    none = run.invoke(cli.app, ["receipt", "verify", r["order"], "--no-chain"])
    assert none.exit_code == 2 and "give a bundle file" in none.output
