"""Many agents reaching for the same files at the same instant.

`test_intent.py` proves two processes cannot both claim the same file. This is the same property under load, and it
is the property `knos bench` measures and `docs/BENCH.md` publishes.

The claim being made is narrow and absolute. Zero double-grants, not few. A lock that holds most of the time hands
two agents the same file and lets the second overwrite the first, which is the exact failure this product exists to
stop, so "rare" is not a passing grade.

The second arm is the honest counterfactual: the condition that matters is whether the claim list is *shared*, so
the ablation gives every agent its own, which is what an agent has without knos.

Rewritten for 0.2.0: agents claim a path (`src/auth.py`) through the embeddable `knos.core.Claims`, since a claim on
prose ("the parser") is advisory and never blocks. Dropped: the checks on docs/evidence/collide.json and
scripts/collide.py, which are not part of 0.2.0 (knos bench replaces them).
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

AGENTS = 8  # smaller than the study's 16; the property does not depend on it

GRAB = """
import json, sys
from knos.core import Claims
repo, who, path = sys.argv[1], sys.argv[2], sys.argv[3]
with Claims(repo=repo, who=who) as claims:
    took, holder = claims.take("working on " + path, paths=[path])
    held = claims.holder(path)
print(json.dumps({"who": who, "took": bool(took),
                  "holder": (holder or {}).get("host"),
                  "blocked_after": (held or {}).get("host")}))
"""


def _race(script: Path, repo, path: str, env: dict, private: Path | None = None):
    def grab(n: int) -> dict:
        mine = dict(env)
        if private is not None:
            own = private / f"agent-{n:02d}"
            own.mkdir(parents=True, exist_ok=True)
            mine["KNOS_HOME"] = str(own)
        done = subprocess.run(
            [sys.executable, str(script), str(repo), f"agent-{n:02d}", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=mine,
        )
        assert done.returncode == 0, done.stderr[-500:]
        return json.loads(done.stdout.strip().splitlines()[-1])

    with ThreadPoolExecutor(max_workers=AGENTS) as pool:
        return list(pool.map(grab, range(AGENTS)))


@pytest.fixture
def _env(knos_home, monkeypatch):
    import os

    return {**os.environ, "KNOS_HOME": str(knos_home),
            "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}


@pytest.mark.critical
def test_exactly_one_of_many_agents_gets_the_file(tmp_path, repo, _env) -> None:
    from knos.claims import Claims

    script = tmp_path / "grab.py"
    script.write_text(GRAB, encoding="utf-8")

    said = _race(script, repo, "src/auth.py", _env)
    winners = [s for s in said if s["took"]]

    assert len(winners) == 1, f"{len(winners)} agents were granted the same file"

    # A refusal that names nobody is a failed write wearing a refusal's coat.
    for lost in (s for s in said if not s["took"]):
        assert lost["holder"] == winners[0]["who"], lost
        assert lost["blocked_after"] == winners[0]["who"], lost
    assert winners[0]["blocked_after"] is None, "the winner was blocked by its own claim"

    with Claims(repo) as c:
        live = c.live()
    assert [(x.host, x.globs) for x in live] == [(winners[0]["who"], ("src/auth.py",))]


@pytest.mark.critical
def test_without_a_shared_claim_list_every_agent_takes_it(tmp_path, repo, _env) -> None:
    """The ablation. Same code, same instant, claims not shared."""
    script = tmp_path / "grab.py"
    script.write_text(GRAB, encoding="utf-8")

    said = _race(script, repo, "src/auth.py", _env, private=tmp_path / "alone")
    winners = [s for s in said if s["took"]]

    assert len(winners) == AGENTS, (
        "with a private claim list each agent should believe it is alone; "
        f"only {len(winners)} of {AGENTS} did"
    )
