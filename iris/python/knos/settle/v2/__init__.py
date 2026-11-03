"""Clients for the second deployment (programs-v2): knos-oidc and knos-pay with key expiry, prefunded balances and terms fixed at funding, and knos-meter."""
from __future__ import annotations

import json
import os
import sys
from importlib import resources
from pathlib import Path

PROGRAMS = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")       # the only ids a staging file may replace
_SAID: set[str] = set()


def load_ids(environ=None) -> dict:
    """The pinned ids (program_ids.json), or with KNOS_PROGRAM_IDS set, the same with the PROGRAM addresses of that
    file: a staging deployment (scripts/deploy_v2.sh --rc writes the file), so every instruction of a new build can be
    tried on devnet before the timelocked upgrade of the real programs executes. Only program addresses can be
    replaced: the vaults, the fee owner and the workflow pins are constants of the programs themselves, so a file that
    names another one is refused instead of being believed. It is said once on stderr, so nobody runs against staging
    without knowing."""
    ids = json.loads(resources.files(__package__).joinpath("program_ids.json").read_text())
    named = ((os.environ if environ is None else environ).get("KNOS_PROGRAM_IDS") or "").strip()
    if not named:
        return ids
    try:
        other = json.loads(Path(named).read_text(encoding="utf-8"))
    except (OSError, ValueError) as why:
        raise RuntimeError(f"KNOS_PROGRAM_IDS names {named}, which cannot be read as JSON ({why}). Unset it to use the pinned deployment.") from None
    if not isinstance(other, dict):
        raise RuntimeError(f"KNOS_PROGRAM_IDS names {named}, which is not a JSON object of program ids. Unset it to use the pinned deployment.")
    from solders.pubkey import Pubkey
    for name, value in other.items():
        if name in PROGRAMS:
            try:
                Pubkey.from_string(value)
            except (ValueError, TypeError):
                raise RuntimeError(f"{named}: {name} is not an address ({value!r}). Unset KNOS_PROGRAM_IDS to use the pinned deployment.") from None
        elif name != "staging" and ids.get(name) != value:
            raise RuntimeError(f"{named}: only {', '.join(PROGRAMS)} can be replaced, and it changes {name}, which the programs themselves fix. "
                               "Unset KNOS_PROGRAM_IDS to use the pinned deployment.")
    swapped = {name: other[name] for name in PROGRAMS if name in other and other[name] != ids[name]}
    if swapped and named not in _SAID:
        _SAID.add(named)
        print(f"KNOS_PROGRAM_IDS is set: using the STAGING programs of {named} ({', '.join(f'{k} {v}' for k, v in swapped.items())}), "
              "not the pinned deployment. Unset it to use the real one.", file=sys.stderr)
    return {**ids, **swapped}
