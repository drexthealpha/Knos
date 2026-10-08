"""Which knos-pay the cluster runs (`version`, asked by simulation, or read from the deployed executable), kept per
cluster until `forget`."""
from __future__ import annotations

import re

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .... import chain, fees
from .. import pay

from .pins import _BROKE, _code


_VERSION: dict[tuple, int] = {}         # (cluster, program) -> what Version answered, for as long as this process lives


_VERSION_LINE = b"knos2:version"         # Version's log line (fund.rs: msg!("knos2:version {}", VERSION)): only a build that answers 12 holds it


_UPGRADEABLE = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")      # its program account names the ProgramData that holds the code


# The 0.3.14 fee's upper tier edge, 50,000 whole units, as the executable of 2.1 holds it: one 64-bit load (lddw, any
# register) of 50,000,000,000. The build with one fee rate (2.2) has no tiers, so no such load.
_TIERED = re.compile(rb"\x18[\x00-\x0f]\x00\x00" + (50_000_000_000 & 0xFFFFFFFF).to_bytes(4, "little") + rb"\x00{4}"
                     + re.escape((50_000_000_000 >> 32).to_bytes(4, "little")))


def _built(ledger) -> int | None:
    """Which knos-pay is deployed, read from its executable: no transaction, so no fee payer. 0 when the bytes do not
    hold Version's log line (2.0 refuses instruction 12 and has no such line); with the line, 1 when they hold the
    tiered fee of 0.3.14 (`_TIERED`: 2.1) and 2 when they do not (2.2, one rate: the number a log line prints is not
    in the bytes as text, the fee rule is in them as code). None when they could not be read. The program account
    holds the executable itself (loader v2, v4), or (the upgradeable loader) is the tag 2 and the address of the
    ProgramData account that holds it."""
    infos = getattr(ledger, "infos", None)
    if infos is None:
        return None
    try:
        got = infos([pay.PAY_ID])[0]
        if got is not None and got[0] == _UPGRADEABLE:
            data = got[1]
            got = infos([Pubkey.from_bytes(data[4:36])])[0] if len(data) >= 36 and data[:4] == (2).to_bytes(4, "little") else None
    except Exception:  # noqa: BLE001 - not read is no answer
        return None
    if got is None:
        return None
    code = bytes(got[1])
    return 0 if _VERSION_LINE not in code else 1 if _TIERED.search(code) else fees.NEW_VERSION


def forget(ledger=None) -> None:
    """Forgets what Version answered (for this ledger's cluster; with None, for every one), so that the next call asks
    again. A worker calls it when a pass begins: an upgrade that executed between two passes is met by the next one,
    and within a pass every token is planned against one answer."""
    if ledger is None:
        _VERSION.clear()
    else:
        _VERSION.pop((getattr(ledger, "url", None) or id(ledger), pay.PAY_ID), None)


def version(ledger, payer: Keypair | None = None) -> int:
    """Which knos-pay the cluster runs: 2 once 2.2 is live (its instruction 12 logs `knos2:version 2`: one fee rate,
    judges counted by owner, markers bound to an order's funding, the presentation grace), 1 for 2.1, 0 for the 2.0
    program, which refuses that instruction. Asked by simulation, so it costs nothing, and once per cluster until
    `forget` (a worker forgets when a pass begins). A ledger that cannot simulate, or a cluster that did not answer,
    counts as 0 for this call and is asked again on the next: everything 2.1 added is used only on an answer of 1 or
    more, and everything 2.2 changed only on 2 or more (the fee funded, the markers read, who counts as a judge), so
    whichever build is live is met with its own rules. `payer`: any funded key (default: the relay key).
    A simulation needs a fee payer that is on chain. A seller with no relay key (`knos settle --neutral`) or a
    repository with no secret has none, and the cluster refuses the simulation for that (AccountNotFound): then the
    deployed executable is read instead, which needs no payer at all (`_built`)."""
    where = (getattr(ledger, "url", None) or id(ledger), pay.PAY_ID)
    if where in _VERSION:
        return _VERSION[where]
    ask = getattr(ledger, "simulate", None)
    if ask is None:
        return 0
    try:
        logs = ask([pay.version_ix()], payer or chain.key())
    except Exception as why:  # noqa: BLE001 - a refusal by the program is the answer 0; anything else is no answer
        text = " ".join([str(why), *((getattr(why, "data", None) or {}).get("logs") or [])]) if isinstance(getattr(why, "data", None), dict) else str(why)
        if "InstructionError" in text or "invalid instruction data" in text or _code(text) is not None:
            _VERSION[where] = 0
        elif any(mark in text for mark in _BROKE):     # the fee payer is not on chain, or holds no SOL: nothing was asked
            built = _built(ledger)
            if built is not None:
                _VERSION[where] = built
                return built
        return 0
    found = next((int(m.group(1)) for m in (re.fullmatch(r"knos2:version (\d+)", line) for line in chain.said(logs, pay.PAY_ID)) if m), 0)
    _VERSION[where] = found
    return found
