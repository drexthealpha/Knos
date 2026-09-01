"""Sharing a path with a teammate, and stopping.

A person shares a folder; their teammate's agent can read it; they unshare it
and the same question comes back with nothing. The record of who may read
what lives in `contracts/src/Access.sol` on Base Sepolia, so neither person
has to trust the other's copy of it.

None of that is the teammate's problem, so none of those words appear in
anything knos prints. They see a name and a folder.

Signing is done by a key knos made and keeps outside the repo. It is never
printed, and knos never asks anyone to paste one.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

RPC = os.environ.get("KNOS_RPC", "https://sepolia.base.org")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class NotSetUp(RuntimeError):
    """Sharing has not been set up on this machine yet."""


@dataclass(frozen=True)
class Identity:
    """One signer knos holds a key for."""

    name: str
    address: str
    keystore: Path


def keys_dir() -> Path:
    return Path(os.environ.get("KNOS_KEYS", Path.home() / ".knos-keys"))


def _password() -> str:
    p = keys_dir() / "password"
    if not p.exists():
        raise NotSetUp("no key on this machine")
    return p.read_text(encoding="utf-8").strip()


def cast_path() -> str:
    from shutil import which

    found = which("cast")
    if found:
        return found
    guess = Path.home() / ".foundry" / "bin" / ("cast.exe" if os.name == "nt" else "cast")
    if guess.exists():
        return str(guess)
    raise NotSetUp("cast is not installed")


def _run(args: list[str], timeout: int = 180) -> str:
    proc = subprocess.run(
        [cast_path(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise NotSetUp((proc.stderr or proc.stdout).strip()[:300])
    return proc.stdout.strip()


def identity(name: str = "owner") -> Identity:
    keystore = keys_dir() / name
    if not keystore.exists():
        raise NotSetUp(f"no key called {name}")
    address = _run(
        ["wallet", "address", "--keystore", str(keystore), "--password", _password()]
    )
    return Identity(name=name, address=address, keystore=keystore)


def deployment() -> str:
    """Where Access.sol lives, written down when it was deployed."""
    f = keys_dir() / "access.json"
    if not f.exists():
        raise NotSetUp("sharing is not set up yet")
    return json.loads(f.read_text(encoding="utf-8"))["address"]


def record_deployment(address: str, tx: str) -> None:
    (keys_dir() / "access.json").write_text(
        json.dumps({"address": address, "tx": tx}, indent=2), encoding="utf-8"
    )


# ---- naming a teammate ------------------------------------------------


def resolve(who: str) -> str:
    """Turn what a person typed into an address.

    An address is taken as it is. A name is looked up. A name knos already
    holds a key for resolves without asking anyone.
    """
    if ADDRESS.match(who):
        return who
    local = keys_dir() / who
    if local.exists():
        return identity(who).address
    resolved = _run(["resolve-name", who, "--rpc-url", RPC])
    if not ADDRESS.match(resolved):
        raise NotSetUp(f"no one called {who}")
    return resolved


# ---- the two things a person does -------------------------------------


def share(path: str, who: str, as_name: str = "owner") -> str:
    """Let someone read one of your folders. Returns the receipt."""
    me = identity(as_name)
    reader = resolve(who)
    receipt = _send(me, "share(string,address)", [path, reader])
    _settle(me.address, path, reader, expected=True)
    return receipt


def unshare(path: str, who: str, as_name: str = "owner") -> str:
    """Stop them reading it. Returns the receipt."""
    me = identity(as_name)
    reader = resolve(who)
    receipt = _send(me, "unshare(string,address)", [path, reader])
    _settle(me.address, path, reader, expected=False)
    return receipt


def _settle(owner: str, path: str, reader: str, expected: bool, tries: int = 10) -> None:
    """Wait until reading the record agrees with what we just wrote.

    The transaction is mined before `send` returns, but the node answering
    the next read can still be a few blocks behind, so asking straight after
    revoking could say the folder was still shared. knos does not tell
    somebody access is gone until a read confirms it is.
    """
    import time

    for _ in range(tries):
        if may_read(owner, path, reader) == expected:
            return
        time.sleep(2)


def may_read(owner: str, path: str, reader: str) -> bool:
    """Whether that person may read that folder, right now."""
    out = _run(
        [
            "call",
            deployment(),
            "mayRead(address,string,address)(bool)",
            owner,
            path,
            reader,
            "--rpc-url",
            RPC,
        ]
    )
    return out.strip().lower().startswith("true")


def shared_with(owner: str, path: str, readers: list[str]) -> list[str]:
    """Which of these people may read that folder."""
    return [r for r in readers if may_read(owner, path, r)]


def _send(me: Identity, signature: str, args: list[str]) -> str:
    out = _run(
        [
            "send",
            deployment(),
            signature,
            *args,
            "--keystore",
            str(me.keystore),
            "--password",
            _password(),
            "--rpc-url",
            RPC,
            "--json",
        ],
        timeout=300,
    )
    try:
        return json.loads(out).get("transactionHash", "")
    except ValueError:
        return out


def balance(name: str = "owner") -> int:
    """How much this key has to spend. Zero is the normal answer."""
    out = _run(["balance", identity(name).address, "--rpc-url", RPC])
    return int(out.split()[0])
