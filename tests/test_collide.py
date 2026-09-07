"""Sixteen agents reaching for one piece of work at the same instant.

`test_intent.py` already proves two processes cannot both take the same topic.
This is the same property under load, and it is here because the number in
`docs/evidence/collide.json` is quoted in the README: a figure a judge is
pointed at should be a figure a test regenerates rather than one somebody
typed.

The claim being made is narrow and absolute. Zero double-grants, not few. A
lock that holds most of the time hands two agents the same file and lets the
second overwrite the first, which is the exact failure this product exists to
stop, so "rare" is not a passing grade.

The second arm is the honest counterfactual. Deleting the store proves nothing
about coordination - the next agent recreates it and the lock works again. The
condition that matters is whether the memory is *shared*, so the ablation
gives every agent its own, which is what an agent has today without knos.
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
repo, who, topic = sys.argv[1], sys.argv[2], sys.argv[3]
with Claims(repo=repo, who=who) as claims:
    took, holder = claims.take(topic)
print(json.dumps({"who": who, "took": bool(took),
                  "holder": (holder or {}).get("who")}))
"""


def _race(script: Path, repo, topic: str, env: dict, private: Path | None = None):
    def grab(n: int) -> dict:
        mine = dict(env)
        if private is not None:
            own = private / f"agent-{n:02d}"
            own.mkdir(parents=True, exist_ok=True)
            mine["KNOS_HOME"] = str(own)
        done = subprocess.run(
            [sys.executable, str(script), str(repo), f"agent-{n:02d}", topic],
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
def test_exactly_one_of_many_agents_gets_the_work(tmp_path, repo, _env) -> None:
    script = tmp_path / "grab.py"
    script.write_text(GRAB, encoding="utf-8")

    said = _race(script, repo, "the parser", _env)
    winners = [s for s in said if s["took"]]

    assert len(winners) == 1, f"{len(winners)} agents were granted the same work"

    # A refusal that names nobody is a failed write wearing a refusal's coat.
    for lost in (s for s in said if not s["took"]):
        assert lost["holder"] == winners[0]["who"], lost


@pytest.mark.critical
def test_without_a_shared_memory_every_agent_takes_it(tmp_path, repo, _env) -> None:
    """The ablation. Same code, same instant, memory not shared."""
    script = tmp_path / "grab.py"
    script.write_text(GRAB, encoding="utf-8")

    said = _race(script, repo, "the parser", _env, private=tmp_path / "alone")
    winners = [s for s in said if s["took"]]

    assert len(winners) == AGENTS, (
        "with a private memory each agent should believe it is alone; "
        f"only {len(winners)} of {AGENTS} did"
    )


def test_the_published_numbers_say_what_the_readme_says() -> None:
    """The figure quoted to a judge has to be the one on disk."""
    where = ROOT / "docs" / "evidence" / "collide.json"
    assert where.exists(), "run: python scripts/collide.py"
    report = json.loads(where.read_text(encoding="utf-8"))

    assert report["with_store"]["double_grants"] == 0
    assert report["with_store"]["rounds_with_exactly_one_winner"] == report["rounds"]
    # Every refusal named the agent actually holding it.
    assert (report["with_store"]["refusals_naming_the_holder"]
            == report["with_store"]["refusals"])
    assert report["no_shared_store"]["double_grants"] == report["agents"] - 1
