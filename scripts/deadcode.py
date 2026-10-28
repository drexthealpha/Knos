"""Reachability: which knos modules are imported (statically, at any depth, including imports inside functions) from
the product's entry points. Anything not reached is unused.

Entry points: the console script (knos.__main__:main), `python -m knos`, the relay the always-on worker runs
(knos.proof.ghrelay), and the repo's scripts. CI runs `python scripts/deadcode.py` and fails if any module is
unreached; functions are checked by vulture (scripts/vulture_whitelist.py).
"""
import ast
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# knos.settle.v2.passkey_fund: the Python builders of what web/passkey_fund.js sends (a public client with no caller in
# the package; tests/test_passkey_fund.py and tests/test_passkey_chain.py hold it to the program).
# knos.private: `python -m knos.private record|check`, what the workflow in examples/private runs inside a customer's
# network (tests/test_private_path.py runs it the same way).
# knos.host_judge: `python -m knos.host_judge link|editor|level|says`, what docs/reference/ATTESTOR.md gives a host (tests/test_host_a_judge.py);
# the round `judge` of scripts/exercise_rounds/ reads a host's level through it.
# knos.sources.sigstore: the adapter docs/reference/VERIFIER.md gives a caller to use in its own code (verify, then knos.sources.line);
# nothing in the package calls it yet, and tests/test_sources.py holds it to two recorded npm build records.
# knos.outcomes.__main__: `python -m knos.outcomes measure|audiences|check-audience`, what .github/workflows/knos-outcome.yml runs
# with the standard library alone (tests/test_outcome_workflow.py runs it the same way).
# knos.autoresearch.__main__: `python -m knos.autoresearch run <task>`, the autoresearch loop (examples/autoresearch/README.md)
# knos.record.__main__, knos.self.__main__: `python -m knos.record|self ...` (docs/reference/KNOS_RECORD.md, targets.yml)
# knos.gate.app: the GitHub App's webhook handler that github-app/server.py runs (docs/reference/REFEREE.md)
# knos.hermes_plugin: the `hermes_agent.plugins` entry point in pyproject.toml; knos.verify.sealed: the sealed scorer that
# hermes/gepa and hermes/atropos import (docs/reference/AGENTS.md)
# knos.money.x402: `python -m knos.money.x402`, the x402 endpoint; knos.money.revenue: writes the revenue data (--out);
# knos.graduation.devnet: the devnet demo of the escrow and pre-order pool (docs/reference/MONEY.md)
# knos.zk.__main__: `python -m knos.zk verify DIR`, the Groth16 checker (src/knos/zk)
# knos.platform.claims: the per-claim account check a relay calls before batching claims (docs/reference/PLATFORM.md)
# knos.repro.example: `python -m knos.repro.example`, the synthetic example repository (docs/reference/REPRODUCED.md)
# knos.nebius.__main__: `python -m knos.nebius status|demo|rerun|job`, Knos on Nemotron (examples/nebius/README.md)
# knos.money.business: `python -m knos.money.business`, writes the prices JSON (--out; src/knos/money/teams.py)
# knos.game.__main__, knos.game.devnet, knos.game.local_agent: `python -m knos.game ...` (= `knos game`), the game's devnet
# round, and the no-model agent behind the command protocol (docs/reference/AGENTS.md)
# knos.ideas.devnet / devnet_panel: the devnet demos of docs/reference/IDEAS.md; knos.ideas.tools: the opt-in MCP tools (KNOS_MCP_TOOLS=ideas)
# knos.demand_tool: the opt-in MCP tool knos_demand_check (KNOS_MCP_TOOLS=demand), loaded by name from knos.mcp
# knos.readings (with knos.porter): which one do you mean?, imported by the hosted app (apps/wanted which.py);
# knos.referee_rules: the one rules referee, imported by the hosted app and by IRIS (iris/python/knos_iris/referee.py)
# knos.labs.*: one adapter per lab, loaded by name (python -m knos.labs; src/knos/labs); knos.a2a: `python -m knos.a2a serve`;
# knos.claude.managed, knos.money.cctp, knos.money.kora: designs callers import (CAPABILITIES-GAP); knos.platform.verdict: the off-chain
# mirror of the m-of-n verdict release (docs/reference/REFEREE_FROST.md)
# knos.threshold.__main__ / knos.threshold.session: `python -m knos.threshold` (the FROST referee hosts: referee.yml, the PC
# daemon) and the coordinator the web app runs (apps/wanted/knos_wanted/referee.py; docs/reference/REFEREE_FROST.md);
# knos.threshold.codeattest: `python -m knos.threshold.codeattest post` (referee.yml, job attest) and the app server's /api/referee/attest;
# knos.settle.v2.passkey_smart: the LazorKit passkey wallet the web app's pre-orders and factoring use (apps/wanted wallets.py)
ENTRY = ["knos.cli", "knos.__main__", "knos.proof.ghrelay", "knos.settle.v2.passkey_fund", "knos.private", "knos.host_judge", "knos.sources.sigstore",
         "knos.outcomes.__main__", "knos.autoresearch.__main__", "knos.record.__main__", "knos.self.__main__", "knos.gate.app",
         "knos.hermes_plugin", "knos.verify.sealed", "knos.money.x402", "knos.money.revenue", "knos.graduation.devnet", "knos.repro.example", "knos.zk.__main__", "knos.platform.claims",
         "knos.nebius.__main__", "knos.money.business",
         "knos.game.__main__", "knos.game.devnet", "knos.game.local_agent", "knos.ideas.devnet", "knos.ideas.devnet_panel", "knos.ideas.tools", "knos.a2a", "knos.claude.managed", "knos.labs.__main__", "knos.labs.adaptyv", "knos.labs.chemistry", "knos.labs.devnet", "knos.labs.electronics", "knos.labs.escrow", "knos.labs.evm", "knos.labs.materials", "knos.labs.mechanical", "knos.labs.plr_runner", "knos.labs.privacy", "knos.labs.x402pay", "knos.money.cctp", "knos.money.kora", "knos.platform.verdict", "knos.demand_tool", "knos.readings", "knos.referee_rules",
         "knos.threshold.__main__", "knos.threshold.session", "knos.threshold.codeattest", "knos.settle.v2.passkey_smart"]
SCRIPTS = [p for p in list((ROOT / "scripts").glob("*.py")) + list((ROOT / "scripts" / "exercise_rounds").glob("*.py")) + list((ROOT / "examples").glob("*.py"))
           if p.name not in ("deadcode.py", "vulture_whitelist.py")]


def modname(path: Path) -> str:
    rel = path.relative_to(SRC).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


MODULES = {modname(p): p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts}


def resolve(current: str, node: ast.ImportFrom) -> list[str]:
    is_pkg = MODULES.get(current, Path()).name == "__init__.py"
    base = current.split(".") if is_pkg else current.split(".")[:-1]
    if node.level:
        base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
        prefix = ".".join(base + ([node.module] if node.module else []))
    else:
        prefix = node.module or ""
    out = [prefix]
    for a in node.names:
        out.append(f"{prefix}.{a.name}" if prefix else a.name)
    return out


def imports(path: Path, current: str | None) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    got = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                got.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and current is None:
                continue
            got.update(resolve(current, node) if current else [node.module or ""] +
                       [f"{node.module}.{a.name}" for a in node.names])
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
              and (getattr(node.func, "id", "") == "__import__" or getattr(node.func, "attr", "") == "import_module")):
            got.add(node.args[0].value)        # a module named in a call: __import__("knos.x"), importlib.import_module("knos.x")
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
              and getattr(node.func, "id", "") == "_mod" and current):
            # knos.cli loads a command's module when the command is asked for: `_mod("observe")` is
            # importlib.import_module("knos.observe"), a sibling of the module that calls it
            got.add(f"{current.rsplit('.', 1)[0]}.{node.args[0].value}")
    found = set()
    for name in got:
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            cand = ".".join(parts[:i])
            if cand in MODULES:
                found.add(cand)
                # a package import also runs its __init__ parents
                break
    return found


seen, todo = set(), list(ENTRY)
for s in SCRIPTS:
    todo += list(imports(s, None))
while todo:
    m = todo.pop()
    if m in seen or m not in MODULES:
        continue
    seen.add(m)
    parts = m.split(".")
    for i in range(1, len(parts)):
        todo.append(".".join(parts[:i]))
    todo += list(imports(MODULES[m], m))

unreached = sorted(set(MODULES) - seen)
print(f"modules: {len(MODULES)}; reached from entry points: {len(seen)}; unreached: {len(unreached)}")
for u in unreached:
    print("  UNREACHED", u)
sys.exit(1 if unreached else 0)
