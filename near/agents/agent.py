"""One agent on one job: take it, write its output, submit the output's sha256, each step a testnet transaction signed
with the agent's own function-call key. pass_agent.py and fail_agent.py are this with two outputs.

    python near/agents/pass_agent.py <job id>        python near/agents/fail_agent.py <job id>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from common import CONFIG, HERE, call, sha256_file

# take and submit burn about 2.3 Tgas (measured on testnet); NEAR checks a function-call key's allowance against the gas
# attached, so attaching little lets what is left of the agent's allowance last hundreds of calls
AGENT_GAS = "20 Tgas"


def run(name: str, solution: str, job: str) -> dict:
    agent = CONFIG["agents"][name]
    out = HERE / "out" / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "solution.py").write_text(solution, encoding="utf-8")
    h = sha256_file(out / "solution.py")
    took = call(agent, CONFIG["contract"], "take", {"id": job}, gas=AGENT_GAS)
    sent = call(agent, CONFIG["contract"], "submit", {"id": job, "output_sha256": h}, gas=AGENT_GAS)
    r = {"agent": agent, "output": str(out / "solution.py"), "output_sha256": h, "take": took, "submit": sent}
    print(json.dumps(r))
    return r


def main(name: str, solution: str) -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    r = run(name, solution, sys.argv[1])
    return 0 if r["take"]["ok"] and r["submit"]["ok"] else 1


__all__ = ["run", "main", "Path"]
