"""Shared helpers for the tests that run against a local validator (scripts/devchain.sh start)."""

from __future__ import annotations

import os
import secrets

import pytest

from knos.team import protocol, registry, rpc
from solders.keypair import Keypair

URL = os.environ.get("KNOS_DEVCHAIN_URL", "http://127.0.0.1:8899")


def up() -> bool:
    try:
        return rpc.call(URL, "getHealth", [], timeout=2) == "ok"
    except Exception:
        return False


_skip = pytest.mark.skipif(not up(), reason="no local validator: scripts/devchain.sh start")


def devchain(fn):
    """A test that needs the local validator: marked `chain` (not in the default run) and skipped if none is up."""
    return pytest.mark.chain(_skip(fn))


def funded(sol: float = 2.0) -> Keypair:
    k = Keypair()
    rpc.airdrop(URL, k.pubkey(), int(sol * 1_000_000_000))
    return k


def new_team(members: int = 2, read_urls: tuple[str, ...] = ()) -> tuple[protocol.Team, Keypair, list[Keypair]]:
    owner = funded(5)
    keys = [funded(1) for _ in range(members)]
    made = registry.create(URL, owner, [owner.pubkey(), *[k.pubkey() for k in keys]])
    team = protocol.Team(URL, made.credential, made.schemas["claim"], made.schemas["renew"], secrets.token_bytes(32),
                         secrets.token_bytes(32), read_urls)
    return team, owner, keys
