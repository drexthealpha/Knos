"""Knos's referee panel as ONE threshold key: the Zcash Foundation's FROST (frost-ed25519 3.0.0, RFC 9591).

Three referee hosts each hold one key SHARE, made by FROST's distributed key generation (no dealer; no machine ever
holds the whole key). Any two of the three produce ONE standard Ed25519 signature under the group public key; one
share alone produces nothing. The PANEL order of the knos_pay panel test build pins that group key as a 1-of-1 panel
(order_proof.rs: panel_of accepts 1 <= m <= n), so Solana's Ed25519 precompile checks the aggregated signature exactly
as it checks a single referee's, and the program pays at the first (and only) panel key: m = 1.

    participant 1  render   the Knos app server (knos.onrender.com): its share in a Render secret file
    participant 2  gh       GitHub Actions in drexthealpha/Knos (.github/workflows/referee.yml): a repository secret
    participant 3  pc       a machine the operator keeps (WSL daemon): its share in a local file, never committed

The cryptography is the Rust crate itself, run as `knos-frost` (tools/knos-frost, a JSON command): this module only
moves its packages between hosts. Modules: session (the coordinator on the app server), participant (each host's
signer: it re-checks the milestone itself, then signs), dkg (key generation), check (the milestone check every
signer runs), codeattest (the code referee's attestation: GitHub Actions run, knos_oidc on chain, Sigstore), ghoidc
(host 2's GitHub OIDC token), attest (a Google Confidential Space token verifier: UNUSED, kept only because it is tested;
ghoidc uses its RS256 helpers).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

HOSTS = {1: "render", 2: "gh", 3: "pc"}           # gh = GitHub Actions in drexthealpha/Knos
MIN, MAX = 2, 3
SHARE_KIND = "knos-referee-frost-share"
GROUP_KIND = "knos-referee-frost-group"
GROUP_FILE = Path(__file__).resolve().parents[3] / "config" / "referee-frost.json"
BIN_ENV = "KNOS_FROST_BIN"


class FrostError(RuntimeError):
    pass


def binary() -> str:
    """The knos-frost command: $KNOS_FROST_BIN, else the repository's release build, else `knos-frost` on PATH."""
    env = os.environ.get(BIN_ENV)
    if env:
        return env
    built = Path(__file__).resolve().parents[3] / "tools" / "knos-frost" / "target" / "release" / "knos-frost"
    if built.is_file():
        return str(built)
    found = shutil.which("knos-frost")
    if found:
        return found
    raise FrostError("knos-frost is not built: cargo build --release --manifest-path tools/knos-frost/Cargo.toml "
                     f"(or set {BIN_ENV})")


def run(op: str, payload: dict) -> dict:
    """One FROST operation in the Rust crate. Secrets go through stdin/stdout only; an error never echoes input."""
    p = subprocess.run([binary(), op], input=json.dumps(payload).encode(), capture_output=True, timeout=60, check=False)
    try:
        out = json.loads(p.stdout.decode() or "{}")
    except ValueError:
        raise FrostError(f"knos-frost {op}: no JSON answer (exit {p.returncode})") from None
    if p.returncode != 0 or "error" in out:
        raise FrostError(f"knos-frost {op}: {out.get('error', 'failed')}")
    return out


def b58(hexkey: str) -> str:
    from solders.pubkey import Pubkey
    return str(Pubkey.from_bytes(bytes.fromhex(hexkey)))


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def load_group(path: str | Path | None = None) -> dict:
    """The PUBLIC group record: group key, FROST public key package, each host's transport key. Committed in
    config/referee-frost.json; $KNOS_REFEREE_FROST_GROUP overrides."""
    p = Path(path or os.environ.get("KNOS_REFEREE_FROST_GROUP") or GROUP_FILE)
    g = json.loads(p.read_text(encoding="utf-8"))
    if g.get("kind") != GROUP_KIND:
        raise FrostError(f"{p}: not a Knos referee FROST group record")
    return g


def load_share(path_or_json: str | Path) -> dict:
    """One host's share record (SECRET): a file path, or the JSON itself (a GitHub secret arrives as text)."""
    raw = str(path_or_json)
    text = raw if raw.lstrip().startswith("{") else Path(raw).expanduser().read_text(encoding="utf-8")
    s = json.loads(text)
    if s.get("kind") != SHARE_KIND or s.get("id") not in HOSTS:
        raise FrostError("not a Knos referee FROST share record")
    return s


def transport_keypair(share: dict):
    from solders.keypair import Keypair
    return Keypair.from_base58_string(share["transport_secret"])


def auth(share: dict, what: str, session: str, body) -> str:
    """The host's transport signature (Ed25519, its own transport key, not its FROST share) over one message."""
    msg = hashlib.sha256(b"knos3:referee-frost:" + canon({"what": what, "session": session, "id": share["id"], "body": body})).digest()
    return str(transport_keypair(share).sign_message(msg))


def auth_ok(group: dict, pid: int, what: str, session: str, body, sig: str) -> bool:
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    host = (group.get("hosts") or {}).get(str(pid))
    if not host:
        return False
    msg = hashlib.sha256(b"knos3:referee-frost:" + canon({"what": what, "session": session, "id": pid, "body": body})).digest()
    try:
        return Signature.from_string(sig).verify(Pubkey.from_string(host["transport_key"]), msg)
    except (ValueError, TypeError):
        return False
