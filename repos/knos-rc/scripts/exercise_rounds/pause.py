"""The round `pause`: the guardian multisig stops new funding at the public knos_pay for PAUSE seconds
(scripts/governance.mjs `guardian pause`), one funding from the funder's wallet is held to the program's refusal
(error 96, E_PAUSED), and the pause is lifted at once (`guardian pause 0`). A pause also ends by itself, so a round
stopped half way leaves nothing paused for long. Payments, refunds, withdrawals and binds are never paused.

    python scripts/exercise_public.py run --only pause --rpc URL --keys DIR

The member keys: scripts/exercise_rounds/_guardian.py. Nothing to simulate: the guardian is a Squads vault. `xp` is
scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

# "alone": it stops new funding for everyone while it runs, so `run` and `run --phase after` pass it by: only `--only pause`
# starts it, when no round at the public ids is mid-flight (docs/reference/RELEASE.md).
ROUND = {"name": "pause", "needs": ("knos_pay", "public"), "caps": ("pause",), "phase": "any", "alone": True}
PAUSE = 120                 # seconds
E_PAUSED = 96               # programs-v2/knos_pay/src/lib.rs


def _xp() -> Any:
    return globals()["xp"]


def common() -> Any:
    """scripts/exercise_rounds/_guardian.py, loaded once."""
    name = "knos_exercise_guardian_common"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name("_guardian.py"))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[name]


def run(book, st: dict) -> None:
    """The guardian pauses new funding for two minutes, a funding is refused meanwhile, and the pause is lifted."""
    x, w = _xp(), book.w
    if "lifted" in st:
        return
    common().keys(x, w)
    account = x.pay.pause_pda()
    if "paused" not in st:
        common().govern(x, w, ["guardian", "pause", str(PAUSE)])
        until = x.pay.read_pause(w.account(account))
        x._check(until > w.now(), f"new funding is not paused after the guardian's proposal (the pause account reads {until})")
        sig = next(iter(w.ledger.history(account, 5)), None)
        x._on_chain(w, sig, ("knos_pay",), (str(account),))
        st["paused"] = {"signature": sig, "until": until}
        book.tx(st, f"the guardian pauses new funding for {PAUSE} s", str(sig), "knos_pay")
    if "refused" not in st and x.pay.read_pause(w.account(account)) > w.now():
        repo, sha, repo_id = w.pin()
        issue = 900_000 + int(st["paused"]["until"]) % 100_000          # an issue no order names: nothing is created either way
        sig, code = w.refused([x.pay.fund_order_wallet_ix(w.funder.pubkey(), w.funder_token, w.mint, repo_id, issue, x.AMOUNT, repo, sha, x.RC_TERMS)],
                              w.funder)
        x._check(code == E_PAUSED, f"a funding during the pause failed with error {code}, not {E_PAUSED} (new funding is paused)")
        st["refused"] = {"signature": sig, "error": code}
        book.tx(st, "a funding from the funder's wallet during the pause", sig, "knos_pay", code, "new funding is paused")
    common().govern(x, w, ["guardian", "pause", "0"])
    x._check(x.pay.read_pause(w.account(account)) == 0, "the pause was not lifted")
    lift = next(iter(w.ledger.history(account, 5)), None)
    x._on_chain(w, lift, ("knos_pay",), (str(account),))
    st["lifted"] = {"signature": lift}
    book.tx(st, "the guardian lifts the pause", str(lift), "knos_pay")
    refusals = [{"signature": st["refused"]["signature"], "error": E_PAUSED, "means": "new funding is paused"}] if "refused" in st else None
    book.done(st, "pause", "knos_pay", st["paused"]["signature"],
              [f"the pause account read a time {PAUSE} s ahead after the guardian's proposal executed, and 0 after the lift"]
              + (["a funding sent meanwhile landed and failed with error 96 (new funding is paused)"] if refusals else []), refusals)
