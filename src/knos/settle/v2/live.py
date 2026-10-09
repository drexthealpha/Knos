"""Which build of knos_meter and knos_passkey a cluster runs, asked before anything that needs the newer one is sent.

Both were deployed at 1.0. Their 1.1 (the meter's batch mode, the passkey wallet's Fund) came as a proposal of the
upgrade multisig (proposals 5 and 6 at the public ids, executed), and a 1.0 program keeps running until such a proposal
executes, 48 hours after it was approved at the earliest. A 1.0 program answers an instruction it does not have with "invalid instruction data", which tells nobody
what to do. So the relay asks first, by simulation (no fee, nothing sent):

    knos_meter     Version (7): 1.1 logs `knosm:version 1.1`; 1.0 has no instruction 7
    knos_passkey   Fund (2) with no accounts: 1.1 answers its own error 110 (a wrong account); 1.0 has no instruction 2

and when the answer is 1.0, `needs` is the sentence for the person who asked: what is needed and when the upgrade
executes, read from the multisig's own proposals on the same cluster. Everything both builds have (Record, OpenCredits,
Open, Withdraw, ...) is sent as before, to either. A cluster that could not be asked is no answer: the instruction is
then sent as it always was, and the program's own refusal stands.
"""
from __future__ import annotations

import re
import weakref
from datetime import datetime, timezone

from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from ... import mainnet_check as mc
from . import meter, passkey

WANT = {"knos_meter": "1.1", "knos_passkey": "1.1"}
HAS = {"knos_meter": "1.0", "knos_passkey": "1.0"}              # what was deployed before the upgrade
_ABSENT = ("InvalidInstructionData", "invalid instruction data")  # a ledger's words for "this program has no such instruction"
_NEW: set[tuple] = set()                                        # (cluster, program) that answered as the newer build: an upgrade is never undone


def _probe(name: str) -> tuple[Pubkey, Instruction]:
    if name == "knos_meter":
        return meter.METER_ID, meter.version_ix()
    return passkey.PASSKEY_ID, Instruction(passkey.PASSKEY_ID, b"\x02", [])


def runs(ledger, payer: Keypair, name: str) -> bool | None:
    """True: `name` answers as the build WANT names. False: it is the older one (it refused the probe as an instruction
    it does not have). None: it could not be asked (a ledger that cannot simulate, a cluster that did not answer, a fee
    payer that is not on chain)."""
    program, ix = _probe(name)
    where = (getattr(ledger, "url", None) or id(ledger), program)
    if where in _NEW:
        return True
    ask = getattr(ledger, "simulate", None)
    if ask is None:
        return None
    try:
        logs = ask([ix], payer)
    except Exception as why:  # noqa: BLE001 - the program's refusal is the answer; anything else is no answer
        data = getattr(why, "data", None)
        text = " ".join([str(why), *((data.get("logs") or []) if isinstance(data, dict) else [])])
        if any(mark in text for mark in _ABSENT):
            return False
        if name != "knos_passkey" or not re.search(r"custom program error: 0x6e\b|'Custom': 110\b|Custom\(110\)", text):
            return None
        logs = None                                             # Fund is there: it looked at its accounts and found none
    if logs is not None and not any(line.endswith(f"knosm:version {WANT[name]}") for line in logs):
        return None
    _NEW.add(where)
    if not getattr(ledger, "url", None):    # known by id(), which Python gives to another object once this one is gone
        try:
            weakref.finalize(ledger, _drop, where)
        except TypeError:
            pass
    return True


def _drop(where: tuple) -> None:
    """A ledger with no url is gone: what it answered goes with it, so a later one with its id() is asked itself."""
    _NEW.discard(where)


def executes(ledger, name: str) -> tuple[int | None, int | None, bool]:
    """(when the proposed upgrade of `name` can be executed, its proposal's index, whether a proposal was found at all),
    from the upgrade multisig on this cluster. The time is None while the proposal still collects approvals, and
    (None, None, False) when no proposal upgrades `name` or the multisig could not be read."""
    infos = getattr(ledger, "infos", None)
    if infos is None:
        return None, None, False
    ids = meter.IDS

    def account(address: str):
        got = infos([Pubkey.from_string(address)])[0]
        return None if got is None else (str(got[0]), bytes(got[1]))
    try:
        ms, _why = mc.multisig_at(account, ids["upgrade_multisig"], ids["squads_program"])
        found = [p for p in mc.pending_proposals(account, ids["upgrade_multisig"], ms, ids["squads_program"])
                 if p.kind == "upgrade" and p.program == ids[name]] if ms else []
    except Exception:  # noqa: BLE001 - the sentence is still said, without a date
        return None, None, False
    approved = [p for p in found if p.executes_at is not None]
    best = approved[0] if approved else found[0] if found else None     # newest first
    return (best.executes_at, best.index, True) if best else (None, None, False)


def _when(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def needs(ledger, payer: Keypair, name: str, now: int | None = None) -> str | None:
    """None when `name` runs the build WANT names, or could not be asked. Else the plain refusal: what this needs,
    and when the upgrade executes."""
    if runs(ledger, payer, name) is not False:
        return None
    at, index, found = executes(ledger, name)
    head = f"this needs {name} {WANT[name]}, which "
    if at is not None:
        late = now is not None and now >= at
        head += (f"could be executed since {_when(at)} and has not been yet" if late else f"executes on {_when(at)} or shortly after") + \
                f" (proposal {index} of the upgrade multisig, public for 48 hours before it runs)"
    elif found:
        head += f"is proposed (proposal {index} of the upgrade multisig) and executes 48 hours after the members approve it"
    else:
        head += "is not on this cluster yet: no approved upgrade of it was found (knos status says what is proposed)"
    return (f"{head}. The cluster runs {name} {HAS[name]} until then, which has no such instruction. Nothing was sent and nothing was charged: "
            f"do this again once {WANT[name]} is live (knos status says which build runs)")
