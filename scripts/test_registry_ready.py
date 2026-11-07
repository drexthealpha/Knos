"""test_registry_ready: server.json in the repository root names io.github.drexthealpha/knos with its streamable-http
remote, its PyPI package and the founder's description, and passes `mcp-publisher validate` (the registry's own check); every MCP
tool the server lists has a description of one sentence under 160 characters; the founder's two publishing steps are
written down. Publishing itself is the founder's step (an interactive GitHub sign-in).

    python scripts/test_registry_ready.py <path to mcp-publisher>
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = Path(os.environ.get("KNOS_WORLD") or Path(os.environ.get("KNOS_PRIVATE_DIR", ".")) / "v0328" / "world")
OUT = WORLD / "test_registry_ready.txt"
DESC = "Knos carries research across the valley of death."


def tools() -> list[dict]:
    sys.path[:0] = [str(ROOT / "apps" / "wanted"), str(ROOT / "src")]
    from knos_wanted import agent
    from knos_wanted.qloo_mcp import InProcess, Qloo

    class State:
        q = Qloo(InProcess(), mode="mock")
    got = agent.mcp(State(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return got["result"]["tools"]


def main() -> int:
    lines, fails = [], 0

    def ok(c: bool, what: str) -> None:
        nonlocal fails
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        fails += not c
    doc = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    ok(doc.get("name") == "io.github.drexthealpha/knos" and doc.get("remotes") == [{"type": "streamable-http", "url": "https://knos.onrender.com/mcp"}],
       "server.json: name io.github.drexthealpha/knos, remote streamable-http https://knos.onrender.com/mcp")
    ok(doc.get("description") == DESC, f"server.json: the given description ({len(doc.get('description') or '')} characters)")
    ok(any(x.get("registryType") == "pypi" for x in doc.get("packages") or []), "server.json: the PyPI package entry is kept")
    pub = sys.argv[1] if len(sys.argv) > 1 else "mcp-publisher"
    v = subprocess.run([pub, "validate"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    said = (v.stdout + v.stderr).strip().replace("\n", " ")
    ok(v.returncode == 0, f"mcp-publisher validate: exit {v.returncode}: {said[:300]}")
    rows = tools()
    bad = [(t["name"], len(t["description"])) for t in rows
           if len(t["description"]) >= 160 or len(re.findall(r"[.!?](\s|$)", t["description"].strip())) != 1]
    ok(not bad, f"{len(rows)} tool descriptions, {len(bad)} not one sentence under 160 characters {bad[:6]}")
    ok((WORLD / "F6-founder-steps.md").is_file(), "the founder's steps: v0328/world/F6-founder-steps.md")
    lines.append(f"FAIL test_registry_ready: {fails} check(s) failed" if fails else
                 f"PASS test_registry_ready: server.json validates, {len(rows)} tool descriptions one sentence under 160 characters, founder steps written")
    print("\n".join(lines))
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
