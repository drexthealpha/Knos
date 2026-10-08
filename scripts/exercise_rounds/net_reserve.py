"""The round `net-reserve`: a buyer's reserve for one supplier, a netted period that spends no more than it holds, draws
paid from it, and what no draw took returned after the deadline. The round itself is scripts/round_net_reserve.py
(tests/test_round_net_reserve.py runs it on the simulator); this file registers it with scripts/exercise_public.py.

    python scripts/exercise_public.py run --only net-reserve --simulate
    python scripts/exercise_public.py run --only net-reserve --rpc URL --keys DIR [--resume]

`xp` is scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROUND = {"name": "net-reserve", "needs": ("knos_oidc", "knos_pay"), "caps": ("netting_reserve",), "phase": "after"}


def _round():
    name, here = "round_net_reserve", Path(__file__).resolve().parents[1]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, here / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def run(book, st: dict) -> None:
    """A buyer locks a reserve for one supplier before the work; a netted period spends no more than it holds and is
    paid by draws on it; what no draw took goes back to the buyer after the deadline, and not before."""
    # the round asks for the script by name (`import exercise_public`): it must get the one that is running it
    had = sys.modules.get("exercise_public")
    sys.modules["exercise_public"] = xp        # noqa: F821
    try:
        _round().round_net_reserve(book, st)
    finally:
        if had is None:
            sys.modules.pop("exercise_public", None)
        else:
            sys.modules["exercise_public"] = had


simulate = run
