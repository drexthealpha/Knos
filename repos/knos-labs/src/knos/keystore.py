"""Encrypted keys for money and authority: the team owner, the Tempo budget root and the Solana budget vaults.

A keystore file is JSON: scrypt (N = 2^17, r = 8, p = 1) derives a key from the passphrase, and AES-256-GCM seals the
secret. The file is owner-only. The passphrase is never cached and is read only from an interactive terminal: if
stdin is not a TTY, or the process runs inside an agent or CI (`CLAUDECODE`, `CODEX_*`, `CI`), it refuses and says to
run the command in your own terminal. An agent therefore cannot unlock a root key.

Test escape: `KNOS_TEST_PASSPHRASE_FILE` is honoured only for a keystore under `~/.knos-test-wallets/` and only on a
local or test cluster (local, localnet, devnet, moderato). Anywhere else it is refused.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

N, R, P = 2 ** 17, 8, 1
TEST_CLUSTERS = {"local", "localnet", "devnet", "moderato", "testnet"}


class KeystoreError(Exception):
    pass


class NotATerminal(KeystoreError):
    def __init__(self) -> None:
        super().__init__("this needs your passphrase: run this in your own terminal (not through an agent or CI)")


def _derive(passphrase: str, salt: bytes, n: int = N, r: int = R, p: int = P) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def strong_enough(passphrase: str) -> bool:
    """At least 12 characters, or at least 4 words."""
    return len(passphrase) >= 12 or len(passphrase.split()) >= 4


def seal(secret: bytes, passphrase: str, label: str = "") -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not strong_enough(passphrase):
        raise KeystoreError("passphrase too short: use at least 12 characters or 4 words")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    box = AESGCM(_derive(passphrase, salt)).encrypt(nonce, secret, label.encode())
    enc = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"version": 1, "kdf": {"name": "scrypt", "n": N, "r": R, "p": P, "salt": enc(salt)},
            "cipher": {"name": "aes-256-gcm", "nonce": enc(nonce)}, "label": label, "ciphertext": enc(box)}


def unseal(doc: dict, passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    kdf, dec = doc["kdf"], base64.b64decode
    if kdf.get("name") != "scrypt" or int(kdf["n"]) < N:
        raise KeystoreError("unsupported or weakened keystore")
    key = _derive(passphrase, dec(kdf["salt"]), int(kdf["n"]), int(kdf["r"]), int(kdf["p"]))
    try:
        return AESGCM(key).decrypt(dec(doc["cipher"]["nonce"]), dec(doc["ciphertext"]), doc.get("label", "").encode())
    except InvalidTag:
        raise KeystoreError("wrong passphrase") from None


def write_private(path: Path, text: str) -> None:
    """Create `path` owner-only (0600 on POSIX) and write `text`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def save(path: Path, secret: bytes, passphrase: str, label: str = "") -> None:
    write_private(path, json.dumps(seal(secret, passphrase, label), indent=1))


def load(path: Path, passphrase: str) -> bytes:
    return unseal(json.loads(Path(path).read_text(encoding="utf-8")), passphrase)


def _in_agent() -> bool:
    env = os.environ
    return bool(env.get("CLAUDECODE") or env.get("CI") or any(k.startswith("CODEX_") for k in env))


def _test_escape(path: Path, cluster: str) -> str | None:
    f = os.environ.get("KNOS_TEST_PASSPHRASE_FILE")
    if not f:
        return None
    root = (Path.home() / ".knos-test-wallets").resolve()
    try:
        inside = Path(path).resolve().is_relative_to(root)
    except (OSError, ValueError):
        inside = False
    if not inside or cluster not in TEST_CLUSTERS:
        raise KeystoreError("KNOS_TEST_PASSPHRASE_FILE is only for test keystores under ~/.knos-test-wallets/ on a "
                            "local or test cluster")
    return Path(f).read_text(encoding="utf-8").strip()


def ask(path: Path, cluster: str, prompt: str = "Passphrase: ", confirm: bool = False) -> str:
    """The passphrase for `path`: from the test escape when it applies, otherwise typed at an interactive terminal."""
    got = _test_escape(path, cluster)
    if got is not None:
        return got
    if _in_agent() or not sys.stdin.isatty():
        raise NotATerminal()
    first = getpass.getpass(prompt)
    if confirm:
        if not strong_enough(first):
            raise KeystoreError("passphrase too short: use at least 12 characters or 4 words")
        if getpass.getpass("Again: ") != first:
            raise KeystoreError("the two passphrases differ")
    return first
