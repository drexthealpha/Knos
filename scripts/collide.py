"""How many agents collide when nothing coordinates them.

The ablations already answer "what does the store save". This answers the
narrower question the whole product rests on: when several agents reach for
the same work in the same instant, does exactly one get it - and what happens
when they are not sharing a memory.

It is deliberately not a benchmark. There is one number worth having and it is
a count of double-grants, which must be zero for every round while the memory
is shared and everybody-minus-one when it is not. A coordination primitive
that is right 99% of the time is not a coordination primitive.

The ablated condition is *sharing*, not the file. Deleting the store proves
nothing here: the next agent to ask creates it again and coordination works,
because what was lost was the history rather than the mechanism. So the second
arm gives every agent its own memory, which is what an agent has today.

Real operating-system processes, started as close to simultaneously as the
machine allows, because the lock that has to hold is SQLite's across process
boundaries and threads in one interpreter would not exercise it. Each process
opens its own connection, so each one is as much a stranger to the others as
two editors on a laptop are.

    python scripts/collide.py

Writes docs/evidence/collide.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

AGENTS = 16
ROUNDS = 8
TOPIC = "the parser"

# Started in a subprocess, so it says nothing about the harness that started
# it: open the store, try to take the topic, print what happened.
GRAB = """
import json, sys
from datetime import datetime, timezone
from knos.core import Claims
repo, who, topic = sys.argv[1], sys.argv[2], sys.argv[3]
with Claims(repo=repo, who=who) as claims:
    took, holder = claims.take(topic)
print(json.dumps({"who": who, "took": bool(took),
                  "holder": (holder or {}).get("who")}))
"""


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    (repo / "parser.py").write_text("def parse(s):\n    return s\n", encoding="utf-8")
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, capture_output=True, text=True, check=False
    )
    run("init", "-q")
    run("config", "user.email", "collide@example.invalid")
    run("config", "user.name", "collide")
    run("add", "-A")
    run("commit", "-qm", "first")
    return repo


def _round(script: Path, repo: Path, topic: str, env: dict[str, str],
           private_home: Path | None = None) -> list[dict]:
    """AGENTS processes reach for one topic at once. Returns what each said."""

    def grab(n: int) -> dict:
        mine = dict(env)
        if private_home is not None:
            # No shared memory: each agent keeps its own, which is what an
            # agent has today without knos.
            own = private_home / f"agent-{n:02d}"
            own.mkdir(parents=True, exist_ok=True)
            mine["KNOS_HOME"] = str(own)
        done = subprocess.run(
            [sys.executable, str(script), str(repo), f"agent-{n:02d}", topic],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=mine,
        )
        if done.returncode != 0:
            return {"who": f"agent-{n:02d}", "took": None, "error": done.stderr[-300:]}
        return json.loads(done.stdout.strip().splitlines()[-1])

    with ThreadPoolExecutor(max_workers=AGENTS) as pool:
        return list(pool.map(grab, range(AGENTS)))


def main() -> int:
    import os
    import shutil

    home = Path(tempfile.mkdtemp(prefix="knos-collide-home-"))
    work = Path(tempfile.mkdtemp(prefix="knos-collide-"))
    env = {**os.environ, "KNOS_HOME": str(home),
           "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    os.environ["KNOS_HOME"] = str(home)

    try:
        repo = _repo(work)
        script = work / "grab.py"
        script.write_text(GRAB, encoding="utf-8")

        print(f"{AGENTS} agents, {ROUNDS} rounds, one topic each round.")
        print()

        with_store: list[dict] = []
        for r in range(ROUNDS):
            topic = f"{TOPIC} {r}"
            said = _round(script, repo, topic, env)
            winners = [s for s in said if s.get("took") is True]
            broke = [s for s in said if s.get("took") is None]
            # Everybody who lost must be told who has it, and it must be the
            # agent who actually won. A refusal naming nobody is not
            # coordination, it is a failed write.
            told = [s for s in said if s.get("took") is False
                    and winners and s.get("holder") == winners[0]["who"]]
            with_store.append({
                "round": r, "agents": AGENTS, "winners": len(winners),
                "refused": AGENTS - len(winners) - len(broke),
                "refused_told_who_holds_it": len(told), "errors": len(broke),
            })
            mark = "ok " if len(winners) == 1 and not broke else "BAD"
            print(f"  {mark} round {r}: {len(winners)} took it,"
                  f" {AGENTS - len(winners) - len(broke)} refused,"
                  f" {len(told)} told who holds it")

        # ---- the same round, with no shared memory --------------------------
        #
        # Deleting the file is not the counterfactual here. The next agent to
        # ask simply creates it again and coordination works, because what was
        # lost is the history, not the mechanism. The condition being ablated
        # is *sharing*: every agent keeping its own memory, which is precisely
        # what an agent has today without knos.
        print()
        print("  Now give every agent its own memory instead of a shared one.")
        alone = work / "alone"
        said = _round(script, repo, f"{TOPIC} alone", env, private_home=alone)
        winners = [s for s in said if s.get("took") is True]
        print(f"      {len(winners)} of {AGENTS} agents took the same work,")
        print("      each of them certain it was the only one.")

        double_grants = sum(max(0, r["winners"] - 1) for r in with_store)
        report = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "agents": AGENTS,
            "rounds": ROUNDS,
            "processes": "operating-system processes, one connection each",
            "with_store": {
                "rounds": with_store,
                "double_grants": double_grants,
                "rounds_with_exactly_one_winner":
                    sum(1 for r in with_store if r["winners"] == 1),
                "refusals_naming_the_holder":
                    sum(r["refused_told_who_holds_it"] for r in with_store),
                "refusals": sum(r["refused"] for r in with_store),
            },
            "no_shared_store": {
                "agents_that_took_the_same_work": len(winners),
                "double_grants": max(0, len(winners) - 1),
            },
        }

        out = ROOT / "docs" / "evidence" / "collide.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

        print()
        print(f"  memory shared      {double_grants} double-grants"
              f" in {ROUNDS * AGENTS} attempts")
        print(f"  memory not shared  {max(0, len(winners) - 1)} double-grants"
              f" in {AGENTS} attempts")
        print()
        print(f"  wrote {out.relative_to(ROOT).as_posix()}")
        return 0 if double_grants == 0 else 1
    finally:
        os.environ.pop("KNOS_HOME", None)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
