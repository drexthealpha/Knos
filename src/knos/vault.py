"""The vault: evidence that outlives devnet and outlives whoever runs Knos.

An evidence bundle (`knos bundle make`: the receipt, the signed token, the key, the terms, the archived chain record)
is sealed to the people who must be able to open it, one file per bundle, and to nobody else. The buyer, the
supplier and an auditor each hold a key of their own; any one of them opens the file alone, and whoever stores it
(a disk, a bucket, the other party's server) reads only the header.

    knos vault keygen       a key pair for one party; the public half is what the others seal to
    knos vault seal         a bundle (or any file) sealed to one or more public keys, into a vault folder
    knos vault open         the bundle again, for the holder of any one of those keys
    knos vault export       a plain archive of everything a key opens, with a checkpoint: for the customer to keep
    knos vault restore      the bundles out of that archive, each checked against the checkpoint
    knos vault retain       a retention policy applied: keep N years, then delete or keep the hash only (--dry-run prints)
    knos vault checkpoint   one hash over every bundle hash, signed when a key is given: anchor it anywhere
    knos vault verify       a checkpoint against a vault, an export or a folder of bundles: no chain, no network

The sealed file, version 1 (docs/VAULT.md has every field and a test vector; tests/data/vault_v1.json is the vector):

    one content key (32 random bytes) encrypts the bundle with ChaCha20-Poly1305 under a random 12-byte nonce.
    one ephemeral X25519 key per file. For each recipient: shared = X25519(ephemeral, recipient's public key),
        key = HKDF-SHA256(shared, salt = ephemeral public || recipient public, info = "knos.vault.v1 key wrap"),
        and the content key is sealed under it with ChaCha20-Poly1305 and a zero nonce (each wrapping key is used once).
    both seals carry the SHA-256 of the header as associated data, so nobody can add, drop or relabel a recipient,
        rename the file or change its date without every open failing.

The header is in the clear, on purpose: the bundle's SHA-256, its size, its name, the time it was sealed and each
recipient's label and public key. A checkpoint and a retention policy work from the header, with no key. So the
header tells whoever stores the file how many bundles there are, how big, when, and for whom. It does not tell
them a repository, an amount or a verdict.

What a checkpoint is: {entries: every bundle's SHA-256 in order, root: one SHA-256 over them, previous: the root of
the checkpoint before}. The root is 64 characters; put it wherever both parties will find it later (an email to the
other side, a transaction memo, a notary, a newspaper). `verify` then shows that a bundle held today is one of those
that existed when the root was written down. It does not show that the bundle was true: `knos bundle verify` does
that, from the issuer's signature.

This module is the whole of it: no server, no account, no chain. The primitives are in vault_crypto.py.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path     # at module level: typer reads the commands' annotations here

from . import vault_crypto as vc

TYPE, VERSION = "knos.vault", 1
KEM, AEAD = "x25519-hkdf-sha256", "chacha20-poly1305"
KEY_TYPE, POLICY_TYPE, CHECKPOINT_TYPE, HASHES_TYPE, EXPORT_TYPE = "knos.vault-key", "knos.retention-policy", "knos.vault-checkpoint", "knos.vault-hashes", "knos.vault-export"
WRAP_INFO, ROOT_TAG = b"knos.vault.v1 key wrap", b"knos.vault.checkpoint.v1\x00"
ANCHOR = "knos-vault-checkpoint:v1:"        # the line to write down: this, then the root
THEN = ("delete", "hashes")                 # what a policy does with a bundle past its years
YEAR = 365 * 86400                          # a policy's year: 365 days, said in the policy's own output
HASHES = "hashes.json"                      # in a vault folder: the bundles whose hash alone was kept
_HEAD = ("type", "version", "kem", "aead", "name", "plain_sha256", "size", "sealed_at", "ephemeral")
_NAME, _LABEL, _HEX64 = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z"), re.compile(r"[a-z0-9][a-z0-9._-]{0,39}\Z"), re.compile(r"[0-9a-f]{64}\Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _unb64(text, size: int | None = None) -> bytes:
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception:  # noqa: BLE001
        raise ValueError("a field of the sealed file is not base64") from None
    if size is not None and len(raw) != size:
        raise ValueError(f"a field of the sealed file is {len(raw)} bytes where {size} are expected")
    return raw


# ---- keys ----------------------------------------------------------------------------------------------------------------
def key_id(public: bytes) -> str:
    return _sha(public)[:16]


def new_key(label: str, rand=os.urandom) -> dict:
    """A party's key file: keep it; hand out only `public`."""
    if not _LABEL.match(label):
        raise ValueError("a label is 1 to 40 of a-z, 0-9, dot, dash, underscore (buyer, supplier, auditor)")
    private = rand(32)
    public = vc.public_of(private)
    return {"type": KEY_TYPE, "version": 1, "label": label, "id": key_id(public), "public": public.hex(), "private": private.hex()}


def private_of(doc) -> bytes:
    try:
        assert doc["type"] == KEY_TYPE and doc["version"] == 1
        private = bytes.fromhex(doc["private"])
        assert len(private) == 32
    except Exception:  # noqa: BLE001
        raise ValueError("that is not a vault key file (`knos vault keygen` writes one)") from None
    return private


def recipient(spec: str) -> tuple[str, bytes]:
    """`label=<64 hex>`: one recipient as the command line names it."""
    label, _, value = spec.partition("=")
    if not _LABEL.match(label) or not _HEX64.match(value):
        raise ValueError(f"a recipient is label=<the 64 hex characters of its public key>, got {spec!r}")
    return label, bytes.fromhex(value)


# ---- one sealed file -----------------------------------------------------------------------------------------------------
def _bound(doc: dict) -> bytes:
    """What both seals are bound to: the header, and who the recipients are."""
    return hashlib.sha256(_json({**{k: doc[k] for k in _HEAD}, "recipients": [{k: r[k] for k in ("id", "label", "public")} for r in doc["recipients"]]})).digest()


def seal(plain: bytes, recipients: list[tuple[str, bytes]], name: str, now: int, rand=os.urandom) -> bytes:
    """`plain` sealed to every (label, public key) of `recipients`. `rand(n)` gives n random bytes: the system's, except
    in a test."""
    if not recipients or len({p for _l, p in recipients}) != len(recipients) or len({lab for lab, _p in recipients}) != len(recipients):
        raise ValueError("seal to at least one recipient, each label and each key once")
    if not _NAME.match(name) or any(not _LABEL.match(lab) or len(p) != 32 for lab, p in recipients):
        raise ValueError("a name is 1 to 100 of letters, digits, dot, dash, underscore; a recipient is a label and a 32-byte key")
    ephemeral, content_key, nonce = rand(32), rand(32), rand(12)
    eph_public = vc.public_of(ephemeral)
    doc: dict = {"type": TYPE, "version": VERSION, "kem": KEM, "aead": AEAD, "name": name, "plain_sha256": _sha(plain), "size": len(plain), "sealed_at": int(now),
                 "ephemeral": _b64(eph_public), "recipients": [{"id": key_id(p), "label": lab, "public": _b64(p)} for lab, p in sorted(recipients)]}
    bound = _bound(doc)
    for r, (_lab, public) in zip(doc["recipients"], sorted(recipients)):
        wrap = vc.hkdf(vc.x25519(ephemeral, public), eph_public + public, WRAP_INFO)
        r["wrapped"] = _b64(vc.aead_seal(wrap, bytes(12), content_key, bound))
    doc["nonce"], doc["ciphertext"] = _b64(nonce), _b64(vc.aead_seal(content_key, nonce, plain, bound))
    return _json(doc)


def header(blob: bytes) -> dict:
    """The clear part of a sealed file, checked for shape. Nothing here is proved until a key opens the file."""
    try:
        doc = json.loads(blob)
        assert isinstance(doc, dict) and doc["type"] == TYPE and isinstance(doc["recipients"], list) and doc["recipients"]
    except Exception:  # noqa: BLE001
        raise ValueError("this is not a sealed vault file") from None
    if doc.get("version") != VERSION or doc.get("kem") != KEM or doc.get("aead") != AEAD:
        raise ValueError(f"this sealed file is of version {doc.get('version')!r} ({doc.get('kem')}, {doc.get('aead')}): this build reads version {VERSION} ({KEM}, {AEAD})")
    ok = (isinstance(doc.get("name"), str) and _NAME.match(doc["name"]) and isinstance(doc.get("plain_sha256"), str) and _HEX64.match(doc["plain_sha256"])
          and type(doc.get("size")) is int and type(doc.get("sealed_at")) is int
          and all(isinstance(r, dict) and set(r) == {"id", "label", "public", "wrapped"} and isinstance(r["label"], str) for r in doc["recipients"]))
    if not ok or set(doc) != {*_HEAD, "recipients", "nonce", "ciphertext"}:
        raise ValueError("the sealed file's header is not the one version 1 has (docs/VAULT.md)")
    return doc


def open_(blob: bytes, private: bytes) -> tuple[bytes, dict]:
    """(the bundle, the header) for the holder of `private`. Raises ValueError, in words, for a key the file was not
    sealed to and for a file that was changed."""
    doc = header(blob)
    public = vc.public_of(private)
    mine = [r for r in doc["recipients"] if _unb64(r["public"], 32) == public]
    if not mine:
        raise ValueError(f"this file was not sealed to that key ({key_id(public)}). It was sealed to: " + ", ".join(f"{r['label']} ({r['id']})" for r in doc["recipients"]))
    bound, eph_public = _bound(doc), _unb64(doc["ephemeral"], 32)
    try:
        content_key = vc.aead_open(vc.hkdf(vc.x25519(private, eph_public), eph_public + public, WRAP_INFO), bytes(12), _unb64(mine[0]["wrapped"], 48), bound)
        plain = vc.aead_open(content_key, _unb64(doc["nonce"], 12), _unb64(doc["ciphertext"]), bound)
    except ValueError as why:
        raise ValueError(f"the sealed file does not open: it was changed after it was sealed (its header, its recipients or its contents; {why})") from None
    if _sha(plain) != doc["plain_sha256"] or len(plain) != doc["size"]:
        raise ValueError("the sealed file opens to other bytes than its header names")
    return plain, doc


# ---- a vault folder ------------------------------------------------------------------------------------------------------
def _kept(folder: Path) -> dict:
    path = Path(folder) / HASHES
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["type"] == HASHES_TYPE and doc["version"] == 1 and all(_HEX64.match(k) for k in doc["kept"])
    except Exception:  # noqa: BLE001
        raise ValueError(f"{path} is not the list of kept hashes this command writes") from None
    return dict(doc["kept"])


def entries(folder: Path) -> list[dict]:
    """Every bundle a vault folder knows, in order of hash: {sha256, name, size, sealed_at, state, path}. `state` is
    `sealed` (the file is here) or `hash only` (a policy removed the file and kept this line)."""
    folder, out = Path(folder), {}
    if not folder.is_dir():
        raise ValueError(f"{folder} is not a vault folder")
    for sha, row in _kept(folder).items():
        out[sha] = {"sha256": sha, "name": row.get("name", ""), "size": row.get("size", 0), "sealed_at": row.get("sealed_at", 0), "state": "hash only", "path": None}
    for path in sorted(folder.glob("*.vault")):
        doc = header(path.read_bytes())
        if path.name != f"{doc['plain_sha256']}.vault":
            raise ValueError(f"{path.name} is not named for the bundle its header names ({doc['plain_sha256']}): it was renamed or replaced")
        out[doc["plain_sha256"]] = {"sha256": doc["plain_sha256"], "name": doc["name"], "size": doc["size"], "sealed_at": doc["sealed_at"], "state": "sealed", "path": path}
    return [out[k] for k in sorted(out)]


def put(folder: Path, sealed: bytes) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{header(sealed)['plain_sha256']}.vault"
    path.write_bytes(sealed)
    return path


# ---- checkpoints ---------------------------------------------------------------------------------------------------------
def root_of(hashes) -> str:
    """One hash over a set of bundle hashes: SHA-256 of a tag, the count as 8 bytes, and the hashes in order."""
    ordered = sorted(set(hashes))
    if any(not _HEX64.match(h) for h in ordered):
        raise ValueError("a checkpoint's entries are SHA-256 hashes in lower-case hex")
    return _sha(ROOT_TAG + len(ordered).to_bytes(8, "big") + b"".join(bytes.fromhex(h) for h in ordered))


def _signed_part(doc: dict) -> bytes:
    return _json({k: doc[k] for k in ("type", "version", "at", "count", "entries", "root", "previous")})


def checkpoint(hashes, now: int, previous: str | None = None, keypair=None) -> dict:
    """The checkpoint of these bundle hashes. `keypair`: a solders Keypair (the Ed25519 key of a Solana wallet file); with
    it the checkpoint says who made it. Without it, the root is a hash anyone can recompute, and that is all it is."""
    ordered = sorted(set(hashes))
    doc = {"type": CHECKPOINT_TYPE, "version": 1, "at": int(now), "count": len(ordered), "entries": ordered, "root": root_of(ordered), "previous": previous, "signature": None}
    if keypair is not None:
        doc["signature"] = {"scheme": "ed25519", "public": str(keypair.pubkey()), "value": str(keypair.sign_message(_signed_part(doc)))}
    return doc


def check_checkpoint(doc) -> list[str]:
    """What holds of a checkpoint by itself, as lines. Raises ValueError when it does not hold."""
    try:
        assert doc["type"] == CHECKPOINT_TYPE and doc["version"] == 1 and isinstance(doc["entries"], list) and type(doc["at"]) is int
        assert doc["previous"] is None or _HEX64.match(doc["previous"])
        sig = doc["signature"]
    except Exception:  # noqa: BLE001
        raise ValueError("this is not a vault checkpoint, version 1") from None
    if doc["entries"] != sorted(set(doc["entries"])) or doc.get("count") != len(doc["entries"]) or root_of(doc["entries"]) != doc.get("root"):
        raise ValueError("the checkpoint's root is not the hash of its entries: an entry was added, dropped or changed")
    said = [f"the root {doc['root']} is the hash of its {doc['count']} entries"]
    if sig is None:
        return said + ["signed by nobody: it shows what existed only to someone who wrote the root down somewhere else at the time"]
    try:
        from solders.pubkey import Pubkey
        from solders.signature import Signature
        assert sig["scheme"] == "ed25519"
        held = Signature.from_string(sig["value"]).verify(Pubkey.from_string(sig["public"]), _signed_part(doc))
    except Exception:  # noqa: BLE001
        held = False
    if not held:
        raise ValueError("the checkpoint's signature does not hold: it was changed after it was signed, or signed by another key than it names")
    return said + [f"signed by {sig['public']} (Ed25519): that key's holder made this checkpoint. Who holds the key is not in the file"]


def held_in(source: Path, private: bytes | None = None) -> dict[str, str]:
    """{bundle hash: how it is held} for a vault folder, an export archive or a folder of plain bundles."""
    source = Path(source)
    if source.is_file():
        return {sha: "in the archive, its bytes hashed" for sha, _n, _b in _export_files(source.read_bytes())[1]}
    if not source.is_dir():
        raise ValueError(f"{source} is neither a folder nor an export archive")
    have: dict[str, str] = {}
    if any(source.glob("*.vault")) or (source / HASHES).is_file():
        for e in entries(source):
            if e["state"] == "hash only":
                have[e["sha256"]] = "hash only: a retention policy removed the file"
            elif private is not None:
                open_(e["path"].read_bytes(), private)
                have[e["sha256"]] = "sealed, opened with the key and hashed"
            else:
                have[e["sha256"]] = "sealed: the header names it (give --key to open and hash it)"
        return have
    for path in sorted(p for p in source.iterdir() if p.is_file() and p.name != "CHECKPOINT.json"):
        have[_sha(path.read_bytes())] = "a plain file, its bytes hashed"
    return have


def verify(doc, have: dict[str, str]) -> tuple[list[str], list[str]]:
    """(what holds, the entries of the checkpoint that are not held), with no chain and no network."""
    said = check_checkpoint(doc)
    missing = [h for h in doc["entries"] if h not in have]
    said += [f"{h}: {have[h]}" for h in doc["entries"] if h in have]
    extra = sorted(set(have) - set(doc["entries"]))
    if extra:
        said.append(f"{len(extra)} held that the checkpoint does not list (newer than it, or not a bundle of this vault): " + ", ".join(h[:16] for h in extra))
    return said, missing


# ---- export and restore --------------------------------------------------------------------------------------------------
README = ("This archive is a plain copy of evidence bundles from a Knos vault. Nothing in it is encrypted: keep it as you keep contracts.\n"
          "bundles/<sha256>/<name> are the bundles. CHECKPOINT.json lists the SHA-256 of each and one root over them.\n"
          "Check a bundle with no chain and no network:   knos bundle verify --no-chain --no-network bundles/<sha256>/<name>\n"
          "Check the archive against the checkpoint:       knos vault verify CHECKPOINT.json --against <this archive>\n"
          "Both need only the knos package. Neither needs Knos's operator, a cluster or an account.\n")


def _tar(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = len(data), 0, 0o644, 0, 0, "", ""
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def export(folder: Path, private: bytes, now: int, keypair=None) -> tuple[bytes, dict]:
    """(a plain archive of every bundle in the vault folder, its checkpoint). Every sealed file must open with
    `private`: an export that silently left one out would look complete. Bundles kept as a hash only are listed in
    the checkpoint and in EXPORT.json, and are not in the archive."""
    files: dict[str, bytes] = {}
    rows, hash_only = entries(folder), []
    for e in rows:
        if e["state"] == "hash only":
            hash_only.append(e["sha256"])
            continue
        plain, doc = open_(e["path"].read_bytes(), private)
        files[f"bundles/{e['sha256']}/{doc['name']}"] = plain
    mark = checkpoint([e["sha256"] for e in rows], now, keypair=keypair)
    files["CHECKPOINT.json"] = _json(mark)
    files["EXPORT.json"] = _json({"type": EXPORT_TYPE, "version": 1, "at": int(now), "bundles": len(rows) - len(hash_only), "hashes_only": hash_only})
    files["README.txt"] = README.encode()
    return _tar(files), mark


def _export_files(blob: bytes) -> tuple[dict, list[tuple[str, str, bytes]]]:
    """(the checkpoint, [(sha256, name, bytes)]) of an export archive, every bundle hashed. Raises ValueError."""
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as tar:
            members = tar.getmembers()
            if any(not m.isfile() for m in members) or len({m.name for m in members}) != len(members):
                raise ValueError("the archive holds something that is not a plain file, or a name twice")
            files = {m.name: (tar.extractfile(m) or io.BytesIO()).read() for m in members}
    except tarfile.TarError as e:
        raise ValueError(f"this is not an export archive (not a tar: {e})") from None
    try:
        mark = json.loads(files["CHECKPOINT.json"])
    except Exception:  # noqa: BLE001
        raise ValueError("the archive has no CHECKPOINT.json") from None
    check_checkpoint(mark)
    out = []
    for name, data in sorted(files.items()):
        if name in ("CHECKPOINT.json", "EXPORT.json", "README.txt"):
            continue
        m = re.match(r"bundles/([0-9a-f]{64})/([A-Za-z0-9][A-Za-z0-9._-]{0,99})\Z", name)
        if not m:
            raise ValueError(f"the archive holds {name!r}, which is not a file an export holds")
        if _sha(data) != m.group(1) or m.group(1) not in mark["entries"]:
            raise ValueError(f"{name} is not the bundle its folder names, or the checkpoint does not list it: the archive was changed")
        out.append((m.group(1), m.group(2), data))
    return mark, out


def restore(blob: bytes, to: Path) -> list[Path]:
    """Write every bundle of an export archive into `to` as <first 16 of its hash>-<name>, each checked against the
    archive's checkpoint first, and the checkpoint beside them. Needs nothing but the archive."""
    mark, rows = _export_files(blob)
    to = Path(to)
    to.mkdir(parents=True, exist_ok=True)
    out = []
    for sha, name, data in rows:
        path = to / f"{sha[:16]}-{name}"
        path.write_bytes(data)
        out.append(path)
    (to / "CHECKPOINT.json").write_bytes(_json(mark))
    return out


# ---- retention -----------------------------------------------------------------------------------------------------------
def policy_of(doc) -> dict:
    """A retention policy, checked: {"type": "knos.retention-policy", "version": 1, "keep_years": N, "then": "delete" | "hashes"}."""
    try:
        assert doc["type"] == POLICY_TYPE and doc["version"] == 1 and type(doc["keep_years"]) is int and 0 <= doc["keep_years"] <= 100 and doc["then"] in THEN
        assert set(doc) <= {"type", "version", "keep_years", "then", "note"}
    except Exception:  # noqa: BLE001
        raise ValueError('a retention policy is {"type": "knos.retention-policy", "version": 1, "keep_years": 0 to 100, "then": "delete" or "hashes"} '
                         "(and a \"note\" in your own words)") from None
    return doc


def retain(folder: Path, policy: dict, now: int, dry_run: bool = True) -> list[dict]:
    """What the policy does to each sealed bundle of the folder: {sha256, name, sealed_at, age_days, action}, where
    action is `keep`, `delete` or `hashes`. With `dry_run` nothing is touched. A year is 365 days. The age is counted
    from the header's `sealed_at`, which only a key holder can confirm: whoever can write to the folder could have
    replaced the file anyway."""
    policy, folder = policy_of(policy), Path(folder)
    out, kept = [], _kept(folder)
    for e in entries(folder):
        if e["state"] != "sealed":
            continue
        age = int(now) - e["sealed_at"]
        action = policy["then"] if age > policy["keep_years"] * YEAR else "keep"
        out.append({"sha256": e["sha256"], "name": e["name"], "sealed_at": e["sealed_at"], "age_days": age // 86400, "action": action})
        if dry_run or action == "keep":
            continue
        if action == "hashes":
            kept[e["sha256"]] = {"name": e["name"], "size": e["size"], "sealed_at": e["sealed_at"], "removed_at": int(now)}
            (folder / HASHES).write_bytes(_json({"type": HASHES_TYPE, "version": 1, "kept": kept}))     # the line first: a crash between the two leaves both, never neither
        e["path"].unlink()
    return out


# ---- the commands --------------------------------------------------------------------------------------------------------
def register(app, help_lines: list | None = None) -> None:
    """`knos vault keygen | seal | open | export | restore | retain | checkpoint | verify`. `help_lines`: cli._HELP."""
    import importlib
    import time
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("vault", "For money", "Evidence that outlives devnet: bundles sealed to buyer, supplier and auditor; export, retention, checkpoints, restore."))

    def stop(words: str, code: int = 1):
        typer.echo(words, err=True)
        raise typer.Exit(code)

    def key(path: Path) -> bytes:
        try:
            return private_of(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as why:
            stop(f"no key was read from {path}: {why}")
            raise

    def signer(path: Path | None):
        if path is None:
            return None
        try:
            from solders.keypair import Keypair
            return Keypair.from_bytes(bytes(json.loads(path.read_text(encoding="utf-8"))))
        except Exception as why:  # noqa: BLE001
            stop(f"{path} is not a Solana keypair file (a JSON list of 64 numbers): {why}")

    def utc(t: int) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(t))

    vault = typer.Typer(help="Evidence that outlives devnet and the operator: bundles sealed to the people who may open them, and checkpoints anyone can verify.", no_args_is_help=True)
    app.add_typer(vault, name="vault")
    now_opt = typer.Option(None, "--now", help="the time to record, in seconds since 1970 (default: this machine's clock)")

    @vault.command("keygen")
    def keygen_cmd(label: str = typer.Argument(..., help="who this key is for: buyer, supplier, auditor"),
                   out_file: Path = typer.Option(None, "--out", help="where to write the key file (default: <label>.vaultkey.json)")) -> None:
        """Make one party's key pair. Keep the file; give the others the public line it prints."""
        try:
            doc = new_key(label)
        except ValueError as why:
            stop(str(why), 2)
        path = out_file or Path(f"{label}.vaultkey.json")
        if path.exists():
            stop(f"{path} exists and is not overwritten: a key that is replaced opens nothing sealed to the old one.")
        path.write_bytes(_json(doc))
        try:
            path.chmod(0o600)
        except OSError:
            pass
        typer.echo(f"{path}: keep it, and a copy somewhere else. Whoever seals to you needs only this:\n{label}={doc['public']}")

    @vault.command("seal")
    def seal_cmd(path: Path = typer.Argument(..., help="a bundle written by `knos bundle make` (any file is sealed the same way)"),
                 to: list[str] = typer.Option(..., "--to", help="a recipient, as label=<public key>: once for each of buyer, supplier, auditor"),
                 folder: Path = typer.Option(Path("vault"), "--vault", help="the vault folder the sealed file goes into"),
                 now: int = now_opt) -> None:
        """Seal one bundle so that each named recipient can open it alone, and nobody else can."""
        try:
            plain = path.read_bytes()
            name = path.name if _NAME.match(path.name) else "bundle.tar"
            written = put(folder, seal(plain, [recipient(t) for t in to], name, int(time.time()) if now is None else now))
        except (OSError, ValueError) as why:
            stop(f"nothing was sealed: {why}")
        typer.echo(f"{written}: {len(plain)} bytes sealed to {len(to)} ({', '.join(t.partition('=')[0] for t in to)}). bundle sha256:{_sha(plain)}")

    @vault.command("open")
    def open_cmd(path: Path = typer.Argument(..., help="a sealed file (<sha256>.vault)"),
                 key_file: Path = typer.Option(..., "--key", help="your key file"),
                 out_file: Path = typer.Option(None, "--out", help="where to write the bundle (default: the name in its header)")) -> None:
        """Open one sealed file with your key and write the bundle."""
        try:
            plain, doc = open_(path.read_bytes(), key(key_file))
            target = out_file or Path(doc["name"])
            target.write_bytes(plain)
        except (OSError, ValueError) as why:
            stop(f"not opened: {why}")
        typer.echo(f"{target}: {len(plain)} bytes, sha256:{doc['plain_sha256']}, sealed {utc(doc['sealed_at'])}. Check it: knos bundle verify --no-chain {target}")

    @vault.command("export")
    def export_cmd(folder: Path = typer.Argument(..., help="the vault folder"),
                   key_file: Path = typer.Option(..., "--key", help="your key file: every sealed file must open with it"),
                   out_file: Path = typer.Option(Path("knos-evidence.tar"), "--out", help="the plain archive to write"),
                   sign: Path = typer.Option(None, "--sign", help="a Solana keypair file: the archive's checkpoint is signed with it"),
                   now: int = now_opt) -> None:
        """Write a plain archive of every bundle, with a checkpoint, for the customer to keep. It is not encrypted."""
        try:
            blob, mark = export(folder, key(key_file), int(time.time()) if now is None else now, signer(sign))
            out_file.write_bytes(blob)
        except (OSError, ValueError) as why:
            stop(f"nothing was exported: {why}")
        typer.echo(f"{out_file}: {mark['count']} bundle hashes, not encrypted, sha256:{_sha(blob)}\n{ANCHOR}{mark['root']}\n"
                   f"Restore from it alone: knos vault restore {out_file} --to DIR")

    @vault.command("restore")
    def restore_cmd(archive: Path = typer.Argument(..., help="an archive written by `knos vault export`"),
                    to: Path = typer.Option(..., "--to", help="the folder the bundles are written into")) -> None:
        """Write the bundles of an export archive into a folder, each checked against the archive's checkpoint."""
        try:
            written = restore(archive.read_bytes(), to)
        except (OSError, ValueError) as why:
            stop(f"nothing was restored: {why}")
        for p in written:
            typer.echo(str(p))
        typer.echo(f"{len(written)} bundles restored and checked against the checkpoint. Check each: knos bundle verify --no-chain FILE")

    @vault.command("retain")
    def retain_cmd(folder: Path = typer.Argument(..., help="the vault folder"),
                   policy: Path = typer.Option(..., "--policy", help="the retention policy file"),
                   dry_run: bool = typer.Option(False, "--dry-run", help="print what would go, and touch nothing"),
                   now: int = now_opt) -> None:
        """Apply a retention policy: keep N years, then delete, or keep the hash only."""
        try:
            doc = policy_of(json.loads(policy.read_text(encoding="utf-8")))
            rows = retain(folder, doc, int(time.time()) if now is None else now, dry_run)
        except (OSError, ValueError) as why:
            stop(f"nothing was changed: {why}")
        words = {"keep": "kept", "delete": "would be deleted" if dry_run else "deleted", "hashes": "would be removed, its hash kept" if dry_run else "removed, its hash kept"}
        for r in rows:
            typer.echo(f"{r['sha256']}  {r['name']}  sealed {utc(r['sealed_at'])}, {r['age_days']} days old: {words[r['action']]}")
        gone = sum(r["action"] != "keep" for r in rows)
        typer.echo(f"policy: keep {doc['keep_years']} years (of 365 days), then {'delete' if doc['then'] == 'delete' else 'keep the hash only'}. "
                   f"{gone} of {len(rows)} {'would go' if dry_run else 'went'}." + (" Dry run: nothing was touched." if dry_run else ""))

    @vault.command("checkpoint")
    def checkpoint_cmd(folder: Path = typer.Argument(..., help="the vault folder"),
                       out_file: Path = typer.Option(Path("checkpoint.json"), "--out", help="the checkpoint file to write"),
                       previous: Path = typer.Option(None, "--previous", help="the checkpoint before this one: its root is recorded, so the two form a chain"),
                       sign: Path = typer.Option(None, "--sign", help="a Solana keypair file: the checkpoint is signed with it (without it, it is a hash)"),
                       now: int = now_opt) -> None:
        """Write one hash over every bundle hash in the vault. Put the line it prints anywhere both parties will find it."""
        try:
            before = None
            if previous is not None:
                old = json.loads(previous.read_text(encoding="utf-8"))
                check_checkpoint(old)
                before = old["root"]
            mark = checkpoint([e["sha256"] for e in entries(folder)], int(time.time()) if now is None else now, before, signer(sign))
            out_file.write_bytes(_json(mark))
        except (OSError, ValueError) as why:
            stop(f"no checkpoint was written: {why}")
        typer.echo(f"{out_file}: {mark['count']} bundles, {'signed by ' + mark['signature']['public'] if mark['signature'] else 'not signed (a hash)'}\n{ANCHOR}{mark['root']}")

    @vault.command("verify")
    def verify_cmd(mark_file: Path = typer.Argument(..., help="a checkpoint file"),
                   against: Path = typer.Option(None, "--against", help="a vault folder, an export archive, or a folder of plain bundles"),
                   key_file: Path = typer.Option(None, "--key", help="with a vault folder: open every sealed file and hash it, not only read its header"),
                   root: str = typer.Option("", "--root", help="the root you wrote down at the time (with or without its prefix): must be this checkpoint's")) -> None:
        """Check a checkpoint, and that everything it lists is held. No chain and no network are used."""
        try:
            mark = json.loads(mark_file.read_text(encoding="utf-8"))
            have = held_in(against, key(key_file) if key_file else None) if against is not None else {}
            said, missing = verify(mark, have) if against is not None else (check_checkpoint(mark), [])
        except (OSError, ValueError) as why:
            stop(f"not verified: {why}")
        if root and root.removeprefix(ANCHOR) != mark["root"]:
            stop(f"not verified: the root you give is not this checkpoint's ({mark['root']}).")
        for line in said:
            typer.echo(line)
        if missing:
            stop(f"not verified: {len(missing)} of {mark['count']} listed bundles are not held: " + ", ".join(missing))
        typer.echo(f"verified with no chain and no network. {ANCHOR}{mark['root']}")
