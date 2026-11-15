"""Knos's referee panel as a FROST 2-of-3 threshold key (knos.threshold; the Zcash Foundation's frost-ed25519 3.0.0 via
tools/knos-frost). Round trip, every pair of hosts, refusal with one share, the distributed key generation, and the
aggregated signature releasing a 1-of-1 PANEL order (the group key) through the Ed25519 precompile on the knos_pay
0.3.34 test build in LiteSVM. Synthetic test units; keys and shares are made per test (never the devnet shares).
The module runs only where tools/knos-frost is built: the pytest job of CI does not build it, so there it skips
(.github/workflows/referee.yml builds knos-frost to sign, and runs no pytest)."""
from __future__ import annotations

import base64
import itertools
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.signature import Signature  # noqa: E402

from knos import threshold as T  # noqa: E402

try:
    T.binary()
except T.FrostError:
    pytest.skip("knos-frost is not built (cargo build --release --manifest-path tools/knos-frost/Cargo.toml)", allow_module_level=True)

from _order import USDC, OrderChain  # noqa: E402

from knos import ideas  # noqa: E402
from knos.ideas import commit as C, sources, wanted as W  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402
from knos.threshold import attest, check, dkg, participant, session  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "ideas" / "recorded-fixture.json"
BUILD = "knos_pay_v2_0334_test.so"
TRIAL = "NCT04718792"
ORC = "0000-0002-1825-0097"
MSG = bytes(range(32))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for k in ideas.ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no live call in tests")))
    monkeypatch.setenv(ideas.FIXTURES_ENV, str(FIXTURE))


def dealer_shares():
    d = T.run("dealer", {"max": 3, "min": 2})
    return d["shares"], d["public"], d["group_key"]


def sign_with(ids, shares, public, msg=MSG):
    rounds = {i: T.run("commit", {"key_package": shares[str(i)]}) for i in ids}
    sp = T.run("package", {"commitments": {str(i): r["commitments"] for i, r in rounds.items()}, "message": msg.hex()})["signing_package"]
    sh = {str(i): T.run("sign", {"key_package": shares[str(i)], "nonces": r["nonces"], "signing_package": sp, "message": msg.hex()})["share"]
          for i, r in rounds.items()}
    return T.run("aggregate", {"signing_package": sp, "shares": sh, "public": public})["signature"]


def test_frost_round_trip_any_pair_gives_one_standard_ed25519_signature():
    shares, public, gk = dealer_shares()
    key = Pubkey.from_bytes(bytes.fromhex(gk))
    for pair in itertools.combinations((1, 2, 3), 2):
        sig = sign_with(pair, shares, public)
        assert Signature.from_bytes(bytes.fromhex(sig)).verify(key, MSG), pair          # plain Ed25519 (ed25519-dalek)
        assert T.run("verify", {"group_key": gk, "message": MSG.hex(), "signature": sig})["ok"]
        assert not T.run("verify", {"group_key": gk, "message": (b"x" + MSG[1:]).hex(), "signature": sig})["ok"]


def test_one_share_alone_signs_nothing():
    shares, public, _ = dealer_shares()
    r = T.run("commit", {"key_package": shares["1"]})
    with pytest.raises(T.FrostError):
        sp = T.run("package", {"commitments": {"1": r["commitments"]}, "message": MSG.hex()})["signing_package"]
        sh = T.run("sign", {"key_package": shares["1"], "nonces": r["nonces"], "signing_package": sp, "message": MSG.hex()})["share"]
        T.run("aggregate", {"signing_package": sp, "shares": {"1": sh}, "public": public})
    # a signer refuses a package whose message is not the digest it checked
    r1, r2 = (T.run("commit", {"key_package": shares[i]}) for i in ("1", "2"))
    sp = T.run("package", {"commitments": {"1": r1["commitments"], "2": r2["commitments"]}, "message": MSG.hex()})["signing_package"]
    with pytest.raises(T.FrostError, match="not the verdict digest"):
        T.run("sign", {"key_package": shares["1"], "nonces": r1["nonces"], "signing_package": sp, "message": (b"\0" * 32).hex()})


def run_dkg(tmp: Path):
    relay, rid = dkg.DirRelay(tmp / "relay"), "t" + str(time.time_ns())
    out, errs = {}, []

    def one(i):
        try:
            out[i] = dkg.party(i, relay, rid, tmp / f"share-{T.HOSTS[i]}.json", timeout=120, poll=0.02)
        except Exception as e:  # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=one, args=(i,)) for i in (1, 2, 3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs
    group = dkg.group_record(relay, rid)
    shares = {i: T.load_share(tmp / f"share-{T.HOSTS[i]}.json") for i in (1, 2, 3)}
    return group, shares


def test_distributed_key_generation_three_parties_one_group_key_and_any_two_sign(tmp_path):
    group, shares = run_dkg(tmp_path)
    assert {s["group_key"] for s in shares.values()} == {group["group_key"]}
    assert len({json.dumps(s["key_package"]) for s in shares.values()}) == 3          # three different shares
    assert all((tmp_path / f"share-{T.HOSTS[i]}.json").stat().st_mode & 0o077 == 0 for i in (1, 2, 3))
    assert "transport_secret" not in json.dumps(group) and "signing_share" not in json.dumps(group)
    kp = {str(i): s["key_package"] for i, s in shares.items()}
    sig = sign_with((2, 3), kp, group["public"])
    assert Signature.from_bytes(bytes.fromhex(sig)).verify(Pubkey.from_string(group["group_key"]), MSG)


class Led:
    def __init__(self, c):
        self.c = c

    def account(self, a):
        return self.c.data(a)


def test_two_hosts_release_a_one_of_one_group_panel_order_through_the_ed25519_precompile(tmp_path):
    group, shares = run_dkg(tmp_path)
    gk = group["group_key"]
    c = OrderChain(pay_build=BUILD)
    claim = sources.get(TRIAL)
    p = W.plan(claim, units=10, price=4, stages=[("referee_pass", 10_000)], stage_work_s=[30 * 86_400])
    stage = p["stages"][0]
    buyer, tok = c.wallet(c.usdc, 100 * USDC)
    assert c.send([W.fund_panel_ix(p, stage, buyer.pubkey(), tok, c.usdc, 1, [bytes(Pubkey.from_string(gk))], unlisted_panel=True)], buyer), c.err
    order = W.panel_address(p, stage, buyer.pubkey())
    maker = Keypair().pubkey()
    payee = C.parse_payee(f"orcid:{ORC}@{maker}")
    doc = {"v": C.V, "kind": C.KIND, "claim": claim, "commitment_hash": p["commitment_hash"],
           "plan_args": {"units": 10, "price": 4, "stages": [["referee_pass", 10_000]], "stage_work_s": [30 * 86_400], "demand": None,
                         "maker_github_id": None},
           "judge": "panel", "panel": {"m": 1, "keys": [gk], "unlisted": True, "label": ""}, "payee": payee, "program": str(pay.PAY_ID),
           "orders": {stage: {"order": str(order), "oracle": "referee_pass", "amount": p[stage]["amount"]}}}
    page = f"<html>milestone report for {claim['id']}</html>".encode()
    fetcher = lambda url: page  # noqa: E731 - the maker's evidence page (synthetic)
    led = Led(c)
    req = check.request(doc, stage, "https://example.org/milestone")
    digest, ev = check.milestone_digest(req, gk, led, fetcher=fetcher)
    coord = session.Coordinator(group, tmp_path / "sessions")
    sid = coord.open(req, digest)["id"]
    client = participant.LocalClient(coord)
    # the PC (3) is offline: the app server (1) and GitHub Actions (2) complete the round
    got = {}
    ts = [threading.Thread(target=lambda i=i: got.__setitem__(i, participant.sign_session(shares[i], client, sid, led, fetcher=fetcher, poll=0.02)))
          for i in (1, 2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert {g["outcome"] for g in got.values()} == {"shared"}, got
    s = coord.get(sid)
    assert s["state"] == session.SIGNED and s["signers"] == [1, 2]
    # a late third host is not chosen and signs nothing
    assert participant.sign_session(shares[3], client, sid, led, fetcher=fetcher)["outcome"].startswith("not chosen")
    o = c.order(order)
    rec = check.verdict_record(doc, stage, ev, digest, s["signature"], gk, o.stamp)
    assert C._verify(rec)                                       # an ordinary verdict of the group key
    gkb = bytes(Pubkey.from_string(gk))
    ixs = W.stage_verdict_ixs(c.payer.pubkey(), order, o, 1, [gkb], ev, C.payees_of(payee), [(gkb, bytes.fromhex(s["signature"]))], unlisted_panel=True)
    assert c.send(ixs, mark=False), c.err
    d = c.data(pay.ata(maker, c.usdc))
    assert c.order(order) is None and int.from_bytes(d[64:72], "little") == p[stage]["amount"]


def test_hosts_refuse_what_they_did_not_check_and_unsigned_posts(tmp_path):
    group, shares = run_dkg(tmp_path)
    coord = session.Coordinator(group, tmp_path / "s")
    sid = coord.open({"kind": "other"}, MSG)["id"]
    out = participant.sign_session(shares[1], participant.LocalClient(coord), sid, Led(None))
    assert out["outcome"].startswith("refused")
    r = T.run("commit", {"key_package": shares[2]["key_package"]})
    with pytest.raises(PermissionError):
        coord.commit(sid, 2, r["commitments"], T.auth(shares[1], "commit", sid, r["commitments"]))   # 1's key, posing as 2
    coord.commit(sid, 2, r["commitments"], T.auth(shares[2], "commit", sid, r["commitments"]))
    assert coord.get(sid)["state"] == session.ROUND1 and coord.get(sid)["signing_package"] is None     # one share: no round 2


# -- Confidential Space attestation (TEST issuer key: Google signs the real tokens) -------------------------------------
def _rsa():
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = k.public_key().public_numbers()
    b = lambda i: base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()  # noqa: E731
    return k, {"keys": [{"kty": "RSA", "kid": "test-1", "n": b(n.n), "e": b(n.e), "alg": "RS256"}]}


def _token(k, claims):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    e = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()  # noqa: E731
    si = f"{e({'alg': 'RS256', 'kid': 'test-1', 'typ': 'JWT'})}.{e(claims)}"
    return si + "." + base64.urlsafe_b64encode(k.sign(si.encode(), padding.PKCS1v15(), hashes.SHA256())).rstrip(b"=").decode()


def test_confidential_space_token_claims_are_checked():
    from knos.proof import issuers
    k, keys = _rsa()
    digest, now = bytes(range(32)), int(time.time())
    good = issuers.cs_claims(digest, "knos3:referee:aud", now)
    pins = {"audience": "knos3:referee:aud", "image_digest": digest.hex(), "project_id": "knos-test", "keys": keys}
    assert attest.verify(_token(k, good), **pins)["submods"]["container"]["image_digest"] == "sha256:" + digest.hex()
    bad = {"image": {**good, "submods": {**good["submods"], "container": {**good["submods"]["container"], "image_digest": "sha256:" + "1" * 64}}},
           "project": {**good, "submods": {**good["submods"], "gce": {**good["submods"]["gce"], "project_id": "other"}}},
           "debug": {**good, "dbgstat": "enabled"}, "expired": {**good, "exp": now - 3600}, "aud": {**good, "aud": "other"},
           "iss": {**good, "iss": "https://example.org"}, "hw": {**good, "hwmodel": "GCP_SHIELDED_VM"}}
    for why, claims in bad.items():
        with pytest.raises(attest.AttestationError):
            attest.verify(_token(k, claims), **pins)
    k2, _ = _rsa()
    with pytest.raises(attest.AttestationError, match="signature"):
        attest.verify(_token(k2, good), **pins)
    assert attest.status()["deployment"] == "BLOCKED"
