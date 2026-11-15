"""What `knos team …` does, separated from the CLI so tests and the SDK can call it.

Joining is one code sent to the owner plus one command:

    teammate: knos init            -> finds .knos/team.json, prints  knos-join:<key>:<name>  and its fingerprint
    owner:    knos team add <code> -> checks the fingerprint, adds the signer, funds the key, seals the salt on chain
"""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path
from typing import Callable

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer

from .. import keystore
from . import config, protocol, registry, rpc, sas, words

FAUCETS = [
    "https://faucet.solana.com (devnet, sign in with GitHub)",
    "solana airdrop 1 <address> --url devnet",
    "devnet-pow mine --target-lamports 1000000000 (cargo install devnet-pow; proof of work, no account)",
]
CREATE_NEEDS_SOL = 0.12  # credential + four schemas + a member record + the owner's own member float


class TeamError(Exception):
    pass


# ---- join codes -----------------------------------------------------------------------------------------------------

def join_code(key: Pubkey, name: str) -> str:
    return f"knos-join:{key}:{base64.urlsafe_b64encode(name.encode()).decode().rstrip('=')}"


def parse_join_code(code: str) -> tuple[Pubkey, str]:
    parts = code.strip().split(":")
    if len(parts) != 3 or parts[0] != "knos-join":
        raise TeamError("not a Knos join code (knos-join:<key>:<name>)")
    pad = "=" * (-len(parts[2]) % 4)
    return Pubkey.from_string(parts[1]), base64.urlsafe_b64decode(parts[2] + pad).decode("utf-8", "replace")[:64]


def fingerprint(key: Pubkey) -> str:
    return words.fingerprint(bytes(key))


# ---- the owner key -------------------------------------------------------------------------------------------------

def unlock_owner(cluster: str, ask: Callable[[Path, str], str] | None = None) -> Keypair:
    p = config.owner_keystore_path()
    if not p.exists():
        raise TeamError("no team owner key on this machine (it was made by `knos team create`)")
    pw = (ask or (lambda path, cl: keystore.ask(path, cl, "Team owner passphrase: ")))(p, cluster)
    return Keypair.from_bytes(keystore.load(p, pw))


def owner_key_for_create(cluster: str, import_file: Path | None, ask_new: Callable[[Path, str], str] | None = None,
                         ask: Callable[[Path, str], str] | None = None) -> Keypair:
    """The owner key: unlocked if one exists, else imported from a Solana keypair file or made new, then sealed."""
    p = config.owner_keystore_path()
    if p.exists():
        return unlock_owner(cluster, ask)
    k = Keypair.from_bytes(bytes(json.loads(Path(import_file).read_text()))) if import_file else Keypair()
    pw = (ask_new or (lambda path, cl: keystore.ask(path, cl, "New passphrase for the team owner key: ",
                                                     confirm=True)))(p, cluster)
    keystore.save(p, bytes(k), pw, label="knos team owner")
    return k


# ---- create / add / remove / leave -------------------------------------------------------------------------------

def _fund(url: str, payer: Keypair, to: Pubkey, want: int) -> str | None:
    have = rpc.balance(url, to)
    if have >= want:
        return None
    return rpc.send(url, [transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=to, lamports=want - have))],
                    payer)


def create(repo: Path, cluster: str, display: str, owner: Keypair, url: str | None = None,
           max_live_claims: int = 20) -> tuple[config.TeamFile, str]:
    """(team file, credential name). The owner's balance is checked first; a short balance raises with the address
    and the free faucet routes."""
    url = url or config.CLUSTERS[cluster]
    if cluster == "mainnet" and not url:
        raise TeamError("mainnet needs --rpc")
    need = int(CREATE_NEEDS_SOL * registry.LAMPORTS)
    have = rpc.balance(url, owner.pubkey())
    if have < need:
        routes = "\n".join("  - " + f.replace("<address>", str(owner.pubkey())) for f in FAUCETS)
        raise TeamError(f"the owner key {owner.pubkey()} has {have / registry.LAMPORTS:.3f} SOL on {cluster}; "
                        f"a team needs about {CREATE_NEEDS_SOL} SOL (mostly refundable deposits). Free routes:\n{routes}")
    me = config.member_key(create=True)
    made = registry.create(url, owner, [owner.pubkey(), me.pubkey()])
    salt = secrets.token_bytes(32)
    config.store_salt(made.credential, salt)
    registry.add_member_attestation(url, owner, made.credential, me.pubkey(), display, salt)
    if me.pubkey() != owner.pubkey():
        _fund(url, owner, me.pubkey(), registry.float_lamports(max_live_claims))
    tf = config.TeamFile(cluster, made.credential, made.name, owner.pubkey(), made.schemas, config.new_repo_id(),
                         url if url not in config.CLUSTERS.values() else "")
    config.save(repo, tf)
    return tf, made.name


FREE_MEMBER_KEYS = 3


def team_seats() -> int:
    """Seats on this machine's Knos Team licence (0 without one)."""
    try:
        from ..pro import licence
        lic = licence.read()
        if lic and licence.valid(lic) and str(lic.get("plan", "")).startswith("team"):
            return int(lic.get("seats", 0))
    except Exception:  # noqa: BLE001
        pass
    return 0


def public_repo(repo: Path, timeout: float = 5.0) -> bool:
    """Whether this repo's origin is a public GitHub repository (checked with GitHub's public API)."""
    import re
    import subprocess
    import urllib.request
    try:
        url = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    m = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$", url)
    if not m:
        return False
    req = urllib.request.Request(f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}",
                                 headers={"User-Agent": "knos", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - GitHub's public API
            return json.loads(r.read()).get("private") is False
    except (OSError, ValueError):
        return False


def add(tf: config.TeamFile, owner: Keypair, code: str, max_live_claims: int = 20, repo: Path | None = None) -> dict:
    """Add a member from their join code: signer list, key float, sealed salt and name. Idempotent.

    Free covers up to 3 member keys, and any number for a public open-source repo; past that it is the Team plan."""
    key, display = parse_join_code(code)
    url = tf.url
    members_now = [k for k in registry.signers(url, tf.credential) if k != tf.authority]
    if key not in members_now and len(members_now) + 1 > FREE_MEMBER_KEYS:
        seats = team_seats()
        if seats < len(members_now) + 1 and not (repo is not None and public_repo(repo)):
            raise TeamError(f"A team of more than {FREE_MEMBER_KEYS} member keys is the Team plan (free for public "
                            f"open-source repos). {len(members_now)} keys now; this licence covers {seats}. "
                            f"knos pro buy --team {max(3, len(members_now) + 1)}")
    salt = config.salt(tf, fetch=False) or registry.my_salt(url, tf.credential, config.member_key() or owner)
    if not salt:
        raise TeamError("this machine does not hold the team salt")
    current = registry.signers(url, tf.credential)
    done = {"key": str(key), "name": display, "fingerprint": fingerprint(key), "steps": []}
    if key not in current:
        if len(current) >= registry.MAX_SIGNERS:
            raise TeamError(f"a team holds at most {registry.MAX_SIGNERS} member keys")
        registry.set_signers(url, owner, tf.credential, [*current, key])
        done["steps"].append("added")
    if _fund(url, owner, key, registry.float_lamports(max_live_claims)):
        done["steps"].append("funded key")
    member_schema = tf.schemas["member"]
    if rpc.account_data(url, sas.attestation_pda(tf.credential, member_schema, key))[1] is None:
        registry.add_member_attestation(url, owner, tf.credential, key, display, salt)
        done["steps"].append("sealed team secret on chain")
    return done


def add_cloud(tf: config.TeamFile, owner: Keypair, name: str, max_live_claims: int = 20) -> tuple[dict, Path]:
    """A revocable member key for a cloud sandbox, written owner-only to ~/.knos/team/cloud-<name>.json. It can
    create and close claims and write records; it cannot change signers or move budgets."""
    k = Keypair()
    p = config.root() / f"cloud-{name}.json"
    keystore.write_private(p, json.dumps(list(bytes(k))))
    return add(tf, owner, join_code(k.pubkey(), f"{name} (cloud)"), max_live_claims), p


def remove(tf: config.TeamFile, owner: Keypair, who: str) -> dict:
    """Remove a member by public key or display name: out of the signer list, member record closed."""
    url = tf.url
    salt = config.salt(tf, fetch=False)
    people = registry.members(url, tf.credential, salt)
    key = None
    for k, info in people.items():
        if who in (k, info.get("name")):
            key = Pubkey.from_string(k)
    if key is None:
        try:
            key = Pubkey.from_string(who)
        except ValueError:
            raise TeamError(f"no member named {who!r}") from None
    if key == owner.pubkey():
        raise TeamError("the owner cannot remove itself")
    current = registry.signers(url, tf.credential)
    out = {"key": str(key), "steps": []}
    addr = sas.attestation_pda(tf.credential, tf.schemas["member"], key)
    _, raw = rpc.account_data(url, addr)
    if raw is not None:
        att = sas.parse_attestation(raw)
        rpc.send(url, sas.compare_close(owner.pubkey(), owner.pubkey(), att, addr), owner)
        out["steps"].append("member record closed")
    if key in current:
        registry.set_signers(url, owner, tf.credential, [k for k in current if k != key])
        out["steps"].append("removed from signers")
    return out


def leave(tf: config.TeamFile) -> dict:
    """Close this member's own record and forget the salt here. The owner still has to remove the signer."""
    key = config.member_key()
    if key is None:
        raise TeamError("no member key on this machine")
    url = tf.url
    addr = sas.attestation_pda(tf.credential, tf.schemas["member"], key.pubkey())
    _, raw = rpc.account_data(url, addr)
    if raw is not None:
        att = sas.parse_attestation(raw)
        rpc.send(url, sas.compare_close(att.signer, key.pubkey(), att, addr), key)
    try:
        config.salt_path(tf.credential).unlink()
    except OSError:
        pass
    return {"key": str(key.pubkey())}


def status(tf: config.TeamFile) -> dict:
    url = tf.url
    salt = config.salt(tf)
    key = config.member_key()
    out: dict = {"name": tf.name, "cluster": tf.cluster, "credential": str(tf.credential), "rpc": url,
                 "max_signers": registry.MAX_SIGNERS}
    signers = registry.signers(url, tf.credential)
    people = registry.members(url, tf.credential, salt)
    out["members"] = [{"key": str(k), "name": people.get(str(k), {}).get("name", ""), "owner": k == tf.authority}
                      for k in signers]
    if salt:
        _, live = protocol.read_live(config.protocol_team(tf, salt))
        out["live_claims"] = len(live)
    if key is not None:
        bal = rpc.balance(url, key.pubkey())
        out["me"] = {"key": str(key.pubkey()), "member": key.pubkey() in signers, "sol": bal / registry.LAMPORTS,
                     "claims_headroom": max(0, int((bal - registry.FEE_BUFFER_SOL * registry.LAMPORTS)
                                                   // (registry.CLAIM_RENT_SOL * registry.LAMPORTS)))}
    return out


# ---- carrying the member key to your other machines ----------------------------------------------------------------

def key_export(dest: Path) -> str:
    """Seal this member key to a fresh one-time code; write the sealed file to `dest`; return the code. The key is
    never printed: the file is useless without the code, and the code is useless without the file."""
    key = config.member_key()
    if key is None:
        raise TeamError("no member key on this machine")
    code = words.one_time_code(8)
    doc = keystore.seal(bytes(key), code, label="knos member key")
    keystore.write_private(Path(dest), json.dumps(doc))
    return code


def key_import(src: Path, code: str) -> Pubkey:
    doc = json.loads(Path(src).read_text(encoding="utf-8"))
    k = Keypair.from_bytes(keystore.unseal(doc, code.strip()))
    config.write_member_key(k)
    return k.pubkey()


def is_member(tf: config.TeamFile, key: Pubkey) -> bool:
    return key in registry.signers(tf.url, tf.credential)

