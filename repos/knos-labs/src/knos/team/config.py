"""Where a team lives: `.knos/team.json` in the repo (public, committed) and this machine's keys under `~/.knos/team/`.

    .knos/team.json          cluster, rpc, credential, name, owner public key, schema addresses, repo_id (32 random
                             bytes). Public by design: it holds no secret, and committing it is how a team spreads.
    ~/.knos/team/member.json this person's member key (hot: it signs every claim, so it cannot be passphrase-locked).
                             Owner-only. One key per person, carried to their other machines by `knos team key export`.
                             In a cloud sandbox it comes from the KNOS_MEMBER_KEY environment variable instead.
    ~/.knos/team/owner.keystore  the team owner key, encrypted (scrypt + AES-GCM, see knos.keystore).
    ~/.knos/team/<credential>/salt  this machine's copy of the team salt (owner-only). Fetched from the member's own
                             sealed box on chain the first time it is needed.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .. import keystore, paths
from . import protocol, registry, rpc

TEAM_FILE = Path(".knos") / "team.json"
CLUSTERS = rpc.CLUSTERS


@dataclass(frozen=True)
class TeamFile:
    cluster: str
    credential: Pubkey
    name: str
    authority: Pubkey
    schemas: dict[str, Pubkey]
    repo_id: bytes
    rpc: str = ""

    @property
    def url(self) -> str:
        return os.environ.get("KNOS_SOLANA_RPC") or self.rpc or CLUSTERS.get(self.cluster, CLUSTERS["devnet"])

    def to_json(self) -> dict:
        out = {"version": 1, "cluster": self.cluster, "credential": str(self.credential), "name": self.name,
               "authority": str(self.authority), "schemas": {k: str(v) for k, v in self.schemas.items()},
               "repo_id": self.repo_id.hex()}
        if self.rpc:
            out["rpc"] = self.rpc
        return out

    @classmethod
    def from_json(cls, d: dict) -> "TeamFile":
        return cls(cluster=str(d["cluster"]), credential=Pubkey.from_string(d["credential"]), name=str(d["name"]),
                   authority=Pubkey.from_string(d["authority"]),
                   schemas={k: Pubkey.from_string(v) for k, v in d["schemas"].items()},
                   repo_id=bytes.fromhex(d["repo_id"]), rpc=str(d.get("rpc", "")))


def team_path(repo: Path) -> Path:
    return Path(repo) / TEAM_FILE


def load(repo: Path) -> TeamFile | None:
    p = team_path(repo)
    try:
        return TeamFile.from_json(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


def save(repo: Path, tf: TeamFile) -> Path:
    p = team_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(tf.to_json(), indent=2) + "\n", encoding="utf-8")
    return p


def new_repo_id() -> bytes:
    return secrets.token_bytes(32)


# ---- this machine ---------------------------------------------------------------------------------------------------

def root() -> Path:
    d = paths.home() / "team"
    d.mkdir(parents=True, exist_ok=True)
    return d


def machine_id() -> str:
    p = paths.home() / "machine-id"
    try:
        got = p.read_text(encoding="utf-8").strip()
        if got:
            return got
    except OSError:
        pass
    got = secrets.token_hex(8)
    keystore.write_private(p, got)
    return got


def _keypair_from_text(text: str) -> Keypair:
    text = text.strip()
    if text.startswith("["):
        return Keypair.from_bytes(bytes(json.loads(text)))
    return Keypair.from_base58_string(text)


def member_key_path() -> Path:
    return root() / "member.json"


def member_key(create: bool = False) -> Keypair | None:
    """This person's member key: KNOS_MEMBER_KEY (a cloud sandbox) or ~/.knos/team/member.json."""
    env = os.environ.get("KNOS_MEMBER_KEY")
    if env:
        return _keypair_from_text(env)
    p = member_key_path()
    try:
        return _keypair_from_text(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not create:
        return None
    k = Keypair()
    keystore.write_private(p, json.dumps(list(bytes(k))))
    return k


def write_member_key(k: Keypair) -> Path:
    p = member_key_path()
    keystore.write_private(p, json.dumps(list(bytes(k))))
    return p


def owner_keystore_path() -> Path:
    return root() / "owner.keystore"


def salt_path(credential: Pubkey) -> Path:
    return root() / str(credential) / "salt"


def salt(tf: TeamFile, key: Keypair | None = None, fetch: bool = True, timeout: float = 5.0) -> bytes | None:
    """This machine's copy of the team salt, fetched from chain (the member's own sealed box) on first use."""
    p = salt_path(tf.credential)
    try:
        return bytes.fromhex(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    if not fetch:
        return None
    key = key or member_key()
    if key is None:
        return None
    try:
        got = registry.my_salt(tf.url, tf.credential, key)
    except Exception:  # noqa: BLE001 - offline or not yet added: the caller falls back to local mode
        return None
    if got:
        keystore.write_private(p, got.hex())
    return got


def store_salt(credential: Pubkey, value: bytes) -> None:
    keystore.write_private(salt_path(credential), value.hex())


def protocol_team(tf: TeamFile, team_salt: bytes) -> protocol.Team:
    extra = tuple(u for u in os.environ.get("KNOS_SOLANA_READ_RPC", "").split(",") if u)
    return protocol.Team(tf.url, tf.credential, tf.schemas["claim"], tf.schemas["renew"], tf.repo_id, team_salt,
                         extra)
