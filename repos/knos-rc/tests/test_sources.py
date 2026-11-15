"""knos.sources: signed results from systems other than CI. The Sigstore adapter accepts two real SLSA provenance
bundles recorded from npm's registry on 10 Oct 2026 (knos-settle 0.3.25, built by this repository's release workflow;
sigstore 3.0.0, built by sigstore-js), and refuses each one when any signed byte changes."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from knos import ledger
from knos import sources
from knos.sources import der, sigstore

DATA = Path(__file__).resolve().parent / "data" / "sources"
KNOS = DATA / "npm_knos-settle_0.3.25.json"
SIGJS = DATA / "npm_sigstore_3.0.0.json"
TERMS = sources.Terms(buyer=1, seller=142920951, order="ab" * 32, policy="cd" * 32, milestone=1, rate=5_000_000,
                      repository="https://github.com/drexthealpha/Knos", workflow=".github/workflows/release.yml",
                      subject="a28e612c3a78d08fe5be2e55c7ac5538ede3eedf8aecaf776bfbcb4f431a1f2481d1ce8cb3a99b8dd1fff2dddb44d03a17962f91808d5babeeb16a02786bac29")


@pytest.fixture(scope="module")
def src():
    return sigstore.Sigstore()


def _bundle(path: Path) -> dict:
    return sigstore.pick(path.read_bytes())


def _raw(b: dict) -> bytes:
    return json.dumps(b).encode()


def test_trusted_root_is_the_pinned_file():
    assert hashlib.sha256(sigstore.ROOT.read_bytes()).hexdigest() == sigstore.ROOT_SHA256


def test_the_two_recorded_bundles_verify(src):
    ev = src.verify(KNOS.read_bytes())
    assert (ev.issuer, ev.repository, ev.commit) == (sigstore.GITHUB, "https://github.com/drexthealpha/Knos", "095f52ae0dbf8cb5e46af32a123dc74641d1ca13")
    assert ev.signer == "https://github.com/drexthealpha/Knos/.github/workflows/release.yml@refs/tags/v0.3.25"
    assert ev.run == "https://github.com/drexthealpha/Knos/actions/runs/38019116727/attempts/1"
    assert ev.log == "https://rekor.sigstore.dev #3177480388" and ev.signed_at == 1791602205
    assert ev.subjects == (("pkg:npm/knos-settle@0.3.25", "sha512", TERMS.subject),)
    other = src.verify(SIGJS.read_bytes())       # an older bundle format (0.2) and log entry kind (intoto 0.0.2)
    assert (other.repository, other.commit) == ("https://github.com/sigstore/sigstore-js", "3a57a741bfb9f7c3bca69b63e170fc28e9432e69")


def test_a_matching_bundle_is_one_accepted_meter_line(src):
    ev = src.verify(KNOS.read_bytes())
    e = sources.line(ev, TERMS)
    assert (e.accepted, e.verdict, e.artifact, e.evidence, e.evaluator) == (True, "accepted", ev.commit, ev.digest, "sigstore@1")
    assert ledger.parse(e.line()) == e


@pytest.mark.parametrize("change, why", [
    ({"repository": "https://github.com/someone/else"}, "is about"),
    ({"workflow": ".github/workflows/other.yml"}, "not the workflow"),
    ({"subject": "00" * 64}, "no built artifact"),
])
def test_evidence_that_does_not_meet_the_terms_is_no_line(src, change, why):
    ev = src.verify(KNOS.read_bytes())
    with pytest.raises(sources.Refused, match=why):
        sources.line(ev, sources.Terms(**{**TERMS.__dict__, **change}))


def _payload(b):
    st = json.loads(base64.b64decode(b["dsseEnvelope"]["payload"]))
    st["predicate"]["buildDefinition"]["resolvedDependencies"][0]["digest"]["gitCommit"] = "f" * 40
    b["dsseEnvelope"]["payload"] = base64.b64encode(json.dumps(st).encode()).decode()


def _flip(text: str, at: int = 10) -> str:
    raw = bytearray(base64.b64decode(text))
    raw[at] ^= 1
    return base64.b64encode(bytes(raw)).decode()


def _entry(b):
    return b["verificationMaterial"]["tlogEntries"][0]


def _cert(b):
    return b["verificationMaterial"]["certificate"]


def _checkpoint(b):
    p = _entry(b)["inclusionProof"]
    head, _, sig = p["checkpoint"]["envelope"].partition("\n\n")
    lines = head.split("\n")
    lines[2] = base64.b64encode(b"\x00" * 32).decode()
    p["checkpoint"]["envelope"] = "\n".join(lines) + "\n\n" + sig


def _other_cert(b):
    _cert(b)["rawBytes"] = _bundle(SIGJS)["verificationMaterial"]["x509CertificateChain"]["certificates"][0]["rawBytes"]


TAMPER = {
    "the statement": (_payload, "signature does not check"),
    "the statement's signature": (lambda b: b["dsseEnvelope"]["signatures"][0].update(sig=_flip(b["dsseEnvelope"]["signatures"][0]["sig"], 40)), "signature does not check"),
    "the certificate": (lambda b: _cert(b).update(rawBytes=_flip(_cert(b)["rawBytes"], 300)), "not issued by"),
    "another certificate": (_other_cert, "ten minutes"),
    "the log's promise": (lambda b: _entry(b)["inclusionPromise"].update(signedEntryTimestamp=_flip(_entry(b)["inclusionPromise"]["signedEntryTimestamp"], 40)), "signed promise"),
    "the time": (lambda b: _entry(b).update(integratedTime=str(int(_entry(b)["integratedTime"]) + 1)), "signed promise"),
    "a proof hash": (lambda b: _entry(b)["inclusionProof"]["hashes"].__setitem__(0, _flip(_entry(b)["inclusionProof"]["hashes"][0], 3)), "inclusion proof"),
    "the checkpoint's root": (_checkpoint, "checkpoint"),
    "the log's id": (lambda b: _entry(b)["logId"].update(keyId=_flip(_entry(b)["logId"]["keyId"], 0)), "cannot check"),
}


@pytest.mark.parametrize("name", list(TAMPER))
def test_every_signed_part_is_checked(src, name):
    b = copy.deepcopy(_bundle(KNOS))
    how, why = TAMPER[name]
    how(b)
    with pytest.raises(sources.Refused, match=why):
        src.verify(_raw(b))


def test_a_bare_key_bundle_is_refused_and_so_is_an_unpinned_root(tmp_path, src):
    publish = [a["bundle"] for a in json.loads(KNOS.read_bytes())["attestations"] if "slsa" not in a["predicateType"]][0]
    with pytest.raises(sources.Refused, match="bare key"):
        src.verify(_raw(publish))
    changed = tmp_path / "root.json"
    changed.write_bytes(sigstore.ROOT.read_bytes() + b"\n")
    with pytest.raises(sources.Refused, match="not the pinned one"):
        sigstore.trust(changed)
    with pytest.raises(sources.Refused, match="no adapter"):
        sources.adapter("hmac-webhook")


def test_the_inclusion_proof_climb_agrees_with_the_ledgers_tree():
    for size in range(1, 20):
        leaves = [ledger.leaf(bytes([i])) for i in range(size)]
        for m in range(size):
            assert sigstore._climb(m, size, leaves[m], ledger._path(m, leaves)) == ledger._tree(leaves)
        assert sigstore._climb(size, size, leaves[0], []) is None


def test_ecdsa_agrees_with_openssl():
    crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    b = _bundle(KNOS)
    leaf_der = base64.b64decode(_cert(b)["rawBytes"])
    leaf, ours = x509.load_der_x509_certificate(leaf_der), der.cert(leaf_der)
    nums = leaf.public_key().public_numbers()
    assert (ours.key.x, ours.key.y, ours.key.curve) == (nums.x, nums.y, "P-256")
    assert (ours.not_before, ours.not_after) == (int(leaf.not_valid_before_utc.timestamp()), int(leaf.not_valid_after_utc.timestamp()))
    env = b["dsseEnvelope"]
    msg, sig = sigstore.pae(env["payloadType"], base64.b64decode(env["payload"])), base64.b64decode(env["signatures"][0]["sig"])
    for m in (msg, msg + b"x"):
        try:
            leaf.public_key().verify(sig, m, crypto.ECDSA(hashes.SHA256()))
            theirs = True
        except Exception:
            theirs = False
        assert der.ecdsa(ours.key, m, sig) is theirs
    chain = sigstore.trust().cas[-1][0]
    inter = x509.load_der_x509_certificate(chain[0].der)
    inter.public_key().verify(ours.signature, ours.tbs, crypto.ECDSA(hashes.SHA384()))   # P-384: OpenSSL agrees
    assert chain[0].key.curve == "P-384" and der.ecdsa(chain[0].key, ours.tbs, ours.signature)
