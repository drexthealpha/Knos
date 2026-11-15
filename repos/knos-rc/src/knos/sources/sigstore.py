"""The Sigstore adapter: SLSA build provenance signed in GitHub Actions, as npm and GitHub publish it.

What is checked, with no network, against the keys in `sigstore_trusted_root.json` (Sigstore's own trusted root,
taken from its TUF repository https://tuf-repo-cdn.sigstore.dev, file sha256 `ROOT_SHA256`):

1. The signing certificate was issued by Fulcio, Sigstore's certificate authority: its signature checks against a
   Fulcio certificate in the trusted root, it is for code signing, and the log recorded the entry while it was valid.
2. The certificate says GitHub Actions vouched for the signer (`token.actions.githubusercontent.com`) on a runner
   GitHub hosts, and names the repository, the commit, the workflow file and the run.
3. The DSSE envelope (the signed statement) checks against the certificate's key.
4. Rekor, Sigstore's public transparency log, recorded this exact signature, certificate and statement: the
   entry's body matches them; Rekor's signed promise checks against Rekor's key; the inclusion proof leads to a tree
   root that Rekor signed (a checkpoint).
5. The statement is in-toto, its predicate is SLSA provenance v1, and its repository and commit are the ones the
   certificate names.

Not checked: that the trusted root file is current (refresh it from TUF; the log key and the certificate authority
carry their own dates), the certificate transparency stamp in the certificate, and entries in the newer Rekor log
signed with Ed25519 (refused as "a log this adapter cannot check").
"""
from __future__ import annotations

import base64
import hashlib
import json
import urllib.request
from pathlib import Path

from . import Evidence, Refused
from .der import DerError, Key, cert, ecdsa, pem_certs, san_uris, spki, text_ext

ROOT = Path(__file__).with_name("sigstore_trusted_root.json")
ROOT_SHA256 = "6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66"
GITHUB = "https://token.actions.githubusercontent.com"
SLSA_V1 = "https://slsa.dev/provenance/v1"
STATEMENTS = ("https://in-toto.io/Statement/v1", "https://in-toto.io/Statement/v0.1")
BUNDLES = ("application/vnd.dev.sigstore.bundle+json;version=0.2", "application/vnd.dev.sigstore.bundle.v0.3+json")
CODE_SIGNING = bytes.fromhex("06082b06010505070303")        # the OID 1.3.6.1.5.5.7.3.3 as DER, inside extKeyUsage
F = "1.3.6.1.4.1.57264.1."                                 # Fulcio's extensions
ISSUER_V1, ISSUER, SIGNER, RUNNER, REPO, COMMIT, RUN = F + "1", F + "8", F + "9", F + "11", F + "12", F + "13", F + "21"


def _b64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def _when(text: str) -> int:
    import calendar
    import datetime
    t = datetime.datetime.strptime(text.split(".")[0].rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    return calendar.timegm(t.timetuple())


def _within(valid: dict | None, at: int) -> bool:
    valid = valid or {}
    return (not valid.get("start") or _when(valid["start"]) <= at) and (not valid.get("end") or at <= _when(valid["end"]))


class Trust:
    """The keys of Sigstore's trusted root: Rekor's ECDSA keys by log id, and Fulcio's certificate chains."""

    def __init__(self, raw: bytes):
        o = json.loads(raw)
        self.logs: dict[bytes, tuple[str, Key, dict]] = {}
        self.cas: list[tuple[list, dict]] = []
        for log in o.get("tlogs", []):
            pk = log["publicKey"]
            if pk.get("keyDetails") == "PKIX_ECDSA_P256_SHA_256":
                self.logs[_b64(log["logId"]["keyId"])] = (log["baseUrl"], spki(_b64(pk["rawBytes"])), pk.get("validFor") or {})
        for ca in o.get("certificateAuthorities", []):
            self.cas.append(([cert(_b64(c["rawBytes"])) for c in ca["certChain"]["certificates"]], ca.get("validFor") or {}))


def trust(path: Path = ROOT, pinned: str | None = ROOT_SHA256) -> Trust:
    raw = path.read_bytes()
    if pinned and hashlib.sha256(raw).hexdigest() != pinned:
        raise Refused(f"the trusted root {path.name} is not the pinned one (sha256 {pinned[:16]}...)")
    return Trust(raw)


def pae(kind: str, body: bytes) -> bytes:
    """DSSE's pre-authentication encoding (https://github.com/secure-systems-lab/dsse/blob/master/protocol.md)."""
    k = kind.encode()
    return b"DSSEv1 %d %s %d %s" % (len(k), k, len(body), body)


def _climb(index: int, size: int, leaf: bytes, path: list[bytes]) -> bytes | None:
    """The root an inclusion proof leads to (RFC 9162, 2.1.3.2); None when the proof's shape is wrong."""
    if index >= size:
        return None
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return None
        if fn & 1 or fn == sn:
            r = hashlib.sha256(b"\x01" + p + r).digest()
            if not fn & 1:
                while not fn & 1 and fn:
                    fn, sn = fn >> 1, sn >> 1
        else:
            r = hashlib.sha256(b"\x01" + r + p).digest()
        fn, sn = fn >> 1, sn >> 1
    return r if sn == 0 else None


def _checkpoint(note: str, log_id: bytes, key: Key) -> tuple[int, bytes]:
    """(tree size, root) of a checkpoint whose signed note checks against the log's key
    (https://github.com/transparency-dev/formats/blob/main/log/README.md)."""
    body, _, sigs = note.partition("\n\n")
    lines = body.split("\n")
    if len(lines) < 3:
        raise Refused("the checkpoint is not a signed note")
    for s in sigs.strip().split("\n"):
        raw = _b64(s.rsplit(" ", 1)[-1])
        if raw[:4] == log_id[:4] and ecdsa(key, (body + "\n").encode(), raw[4:]):
            return int(lines[1]), _b64(lines[2])
    raise Refused("the checkpoint is not signed by the log's key")


def pick(raw: bytes) -> dict:
    """The provenance bundle in what was fetched: a bundle itself, or the first SLSA provenance among the
    `attestations` of an npm or GitHub answer."""
    o = json.loads(raw)
    if "attestations" in o:
        for a in o["attestations"]:
            b = a.get("bundle") or {}
            if a.get("predicateType", SLSA_V1) == SLSA_V1 and "dsseEnvelope" in b:
                return b
        raise Refused("the answer holds no SLSA provenance")
    return o


class Sigstore:
    name = "sigstore"

    def __init__(self, keys: Trust | None = None):
        self.keys = keys or trust()

    def fetch(self, ref: str) -> bytes:
        """`npm:<package>@<version>` (npm's attestations) or `github:<owner>/<repo>@sha256:<digest>` (GitHub's)."""
        kind, _, what = ref.partition(":")
        if kind == "npm":
            url = f"https://registry.npmjs.org/-/npm/v1/attestations/{what}"
        elif kind == "github" and "@sha256:" in what:
            repo, digest = what.split("@", 1)
            url = f"https://api.github.com/repos/{repo}/attestations/{digest}"
        else:
            raise Refused("a reference is npm:<package>@<version> or github:<owner>/<repo>@sha256:<digest>")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=20) as r:  # noqa: S310 (fixed https hosts)
            return r.read()

    def verify(self, raw: bytes) -> Evidence:
        try:
            return self._verify(pick(raw))
        except (DerError, KeyError, IndexError, TypeError, ValueError) as why:
            if isinstance(why, Refused):
                raise
            raise Refused(f"the bundle cannot be read: {why}") from None

    def _verify(self, b: dict) -> Evidence:
        if b.get("mediaType") not in BUNDLES:
            raise Refused(f"a bundle of type {b.get('mediaType')!r} is not read; {BUNDLES[0]} and {BUNDLES[1]} are")
        vm = b["verificationMaterial"]
        if "certificate" in vm:
            leaf_der = _b64(vm["certificate"]["rawBytes"])
        elif "x509CertificateChain" in vm:
            leaf_der = _b64(vm["x509CertificateChain"]["certificates"][0]["rawBytes"])
        else:
            raise Refused("the bundle is signed with a bare key, not a certificate Sigstore issued; this adapter does not read it")
        leaf = cert(leaf_der)

        # 4 first: the log entry fixes the time every other check is made at
        entry = next((e for e in vm["tlogEntries"] if _b64(e["logId"]["keyId"]) in self.keys.logs), None)
        if entry is None:
            raise Refused("the entry is in a log this adapter cannot check")
        log_id = _b64(entry["logId"]["keyId"])
        url, log_key, log_valid = self.keys.logs[log_id]
        at, index, body_b64 = int(entry["integratedTime"]), int(entry["logIndex"]), entry["canonicalizedBody"]
        if not _within(log_valid, at):
            raise Refused("the log's key was not in use when the entry was recorded")
        promise = json.dumps({"body": body_b64, "integratedTime": at, "logID": log_id.hex(), "logIndex": index},
                             sort_keys=True, separators=(",", ":")).encode()
        if not ecdsa(log_key, promise, _b64(entry["inclusionPromise"]["signedEntryTimestamp"])):
            raise Refused("the log's signed promise does not check against the log's key")
        proof = entry["inclusionProof"]
        body = _b64(body_b64)
        root = _climb(int(proof["logIndex"]), int(proof["treeSize"]), hashlib.sha256(b"\x00" + body).digest(), [_b64(h) for h in proof["hashes"]])
        size, signed_root = _checkpoint(proof["checkpoint"]["envelope"], log_id, log_key)
        if root is None or root != _b64(proof["rootHash"]) or (size, signed_root) != (int(proof["treeSize"]), root):
            raise Refused("the inclusion proof does not lead to the root the log signed")

        # 1: Fulcio issued the certificate, for code signing, valid when the log recorded the entry
        if not leaf.not_before <= at <= leaf.not_after:
            raise Refused("the log recorded the entry outside the certificate's ten minutes")
        if CODE_SIGNING not in leaf.extensions.get("2.5.29.37", b""):
            raise Refused("the certificate is not for code signing")
        if not any(_within(valid, at) and chain[0].subject == leaf.issuer and ecdsa(chain[0].key, leaf.tbs, leaf.signature)
                   for chain, valid in self.keys.cas):
            raise Refused("the certificate was not issued by Sigstore's certificate authority")

        # 2: who signed
        issuer = text_ext(leaf, ISSUER) or text_ext(leaf, ISSUER_V1) or ""
        if issuer != GITHUB:
            raise Refused(f"the signer's identity was vouched for by {issuer or 'nobody'}, not GitHub Actions")
        if text_ext(leaf, RUNNER) != "github-hosted":
            raise Refused("the build ran on a machine its owner controls (a self-hosted runner), so it proves nothing to others")
        signer = text_ext(leaf, SIGNER) or (san_uris(leaf) or [""])[0]
        repo, commit, run = text_ext(leaf, REPO) or "", text_ext(leaf, COMMIT) or "", text_ext(leaf, RUN) or ""

        # 3: the statement is signed by the certificate's key
        env = b["dsseEnvelope"]
        payload, sig = _b64(env["payload"]), _b64(env["signatures"][0]["sig"])
        if len(env["signatures"]) != 1 or not ecdsa(leaf.key, pae(env["payloadType"], payload), sig, hashlib.sha256):
            raise Refused("the statement's signature does not check against the certificate")

        # 4, continued: the log's entry is this signature, this certificate and this statement
        o = json.loads(body)
        if (o.get("kind"), o.get("apiVersion")) == ("dsse", "0.0.1"):
            spec = o["spec"]
            pairs = [(_b64(s["signature"]), pem_certs(_b64(s["verifier"]).decode())[0]) for s in spec["signatures"]]
            payload_hash = spec["payloadHash"]["value"]
        elif (o.get("kind"), o.get("apiVersion")) == ("intoto", "0.0.2"):
            spec = o["spec"]["content"]
            pairs = [(_b64(_b64(s["sig"]).decode()), pem_certs(_b64(s["publicKey"]).decode())[0]) for s in spec["envelope"]["signatures"]]
            payload_hash = spec["payloadHash"]["value"]
        else:
            raise Refused(f"a log entry of kind {o.get('kind')} {o.get('apiVersion')} is not read")
        if pairs != [(sig, leaf_der)] or payload_hash != hashlib.sha256(payload).hexdigest():
            raise Refused("the log's entry is not this signature, certificate and statement")

        # 5: what the statement says, and that it agrees with the certificate
        st = json.loads(payload)
        if env["payloadType"] != "application/vnd.in-toto+json" or st.get("_type") not in STATEMENTS or st.get("predicateType") != SLSA_V1:
            raise Refused("the statement is not SLSA provenance v1")
        bd = st["predicate"]["buildDefinition"]
        said_repo = bd["externalParameters"]["workflow"]["repository"]
        said_commit = next((d["digest"]["gitCommit"] for d in bd.get("resolvedDependencies", []) if "gitCommit" in d.get("digest", {})), "")
        if said_repo != repo or said_commit != commit or len(commit) != 40:
            raise Refused("the statement's repository or commit is not the one the certificate names")
        subjects = tuple((s.get("name", ""), a, d.lower()) for s in st["subject"] for a, d in sorted(s["digest"].items()))
        digest = hashlib.sha256(json.dumps(b, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return Evidence("sigstore", issuer, signer, repo, commit, subjects, run, at, f"{url} #{index}", digest)
