"""The round `gitlab`: a gitlab.com pipeline's ID token verified by knos_oidc and an order paid on it by knos_pay. The
round itself is scripts/gitlab_round.py (tests/test_gitlab_round.py); this file registers it with
scripts/exercise_public.py, where it replaces the built-in round of the same name.

    python scripts/exercise_public.py run --only gitlab --simulate
    GITLAB_TOKEN=... KNOS_GITLAB_PROJECT=group/name python scripts/exercise_public.py run --only gitlab --rpc URL --keys DIR [--resume]

Without a token and a project it ends 3 and says what is missing. On the simulator GitLab is a stand-in written in
scripts/gitlab_round.py: evidence of nothing on gitlab.com. `xp` is scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROUND = {"name": "gitlab", "needs": ("knos_oidc", "knos_pay"), "caps": ("verify_gitlab", "gitlab_pay"), "phase": "any"}


def _round():
    name, here = "gitlab_round", Path(__file__).resolve().parents[1]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, here / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def run(book, st: dict) -> None:
    """A gitlab.com pipeline's token is verified by knos_oidc and pays a wallet-funded order to a merge request's author."""
    _round().round_gitlab(book, st, xp)        # noqa: F821


simulate = run
