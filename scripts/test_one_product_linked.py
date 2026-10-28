"""test_one_product_linked (O1), live: Knos is one product on every surface. The same lab proof gets the same verdict
through IRIS's referee module and through the hosted MCP's knos_milestone_submit; `knos demand`, the SDK's demand(),
the hosted MCP and /api/check give the same readings for one idea; the app's proof step links the IRIS referee;
server.json says which MCP server is which; 0 second product names (scripts/test_one_product.py).

    python scripts/test_one_product_linked.py <commit sha> [result file]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = "https://knos.onrender.com"
IDEA = "a vegan ramen food truck"
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "iris" / "python")]


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(APP + path, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "knos-o1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def mcp(name: str, args: dict) -> dict:
    r = post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]
    return r.get("structuredContent") or json.loads(r["content"][0]["text"])


def texts(w: dict) -> list[str]:
    return [r["text"] for r in w.get("readings") or []]


def main(argv: list[str]) -> int:
    sha, out = argv[0], Path(argv[1]) if len(argv) > 1 else None
    lines, fails = [], []

    def ok(c, what):
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        if not c:
            fails.append(what)

    from knos import ready
    from knos_iris import referee
    brief = json.loads((ROOT / "iris/fixtures/briefs/lab.json").read_text(encoding="utf-8"))
    obs = json.loads((ROOT / "iris/fixtures/observations/glucose-pass.json").read_text(encoding="utf-8"))
    oru = (ROOT / "iris/fixtures/oru/glucose-high.hl7").read_text(encoding="utf-8")
    for kind, proof in (("observation", obs), ("oru", oru)):
        local = json.loads(referee.decide(json.dumps(brief), kind, proof if isinstance(proof, str) else json.dumps(proof), ready.criteria_hash(brief)))
        hosted = mcp("knos_milestone_submit", {"kind": kind, "proof": proof, "brief": brief})
        same = (local["decision"], [m["met"] for m in local["milestones"]]) == (hosted.get("decision"), [m["met"] for m in hosted.get("milestones") or []])
        ok(same, f"lab proof ({kind}): IRIS's referee module says {local['decision']}, the hosted MCP says {hosted.get('decision')}, by {hosted.get('referee')}")
    api = texts(post("/api/check", {"idea": IDEA}))
    hosted = texts(mcp("knos_demand_check", {"idea": IDEA}))
    cli = texts(json.loads(subprocess.run([sys.executable, "-m", "knos", "demand", IDEA, "--json"], capture_output=True, text=True, encoding="utf-8",
                                          env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}, timeout=180).stdout or "{}"))
    sdk_js = ROOT / "sdk" / "settle" / "agent.js"
    sdk = texts(json.loads(subprocess.run(["node", "-e", f"import('{sdk_js.as_uri()}').then((m) => m.demand({json.dumps(IDEA)})).then((r) => console.log(JSON.stringify(r)))"],
                                          capture_output=True, text=True, encoding="utf-8", timeout=180).stdout or "{}"))
    ok(api and api == hosted == cli == sdk, f"the readings of '{IDEA}': /api/check {api}; MCP {hosted == api}; knos demand {cli == api}; the SDK {sdk == api}")
    with urllib.request.urlopen(urllib.request.Request(APP + "/app/", headers={"User-Agent": "knos-o1"}), timeout=120) as r:
        app = r.read().decode("utf-8", "replace")
    ok("Checked inside a lab's own IRIS" in app and "iris/README.md" in app, "the app's proof step lists Checked inside a lab's own IRIS, linked to iris/README.md")
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    two = sum(1 for p in ROOT.glob("server*.json")) >= 2
    ok(two, f"server.json and a second file name the hosted MCP and the local knos mcp apart ({server.get('name')}, {len(server.get('packages') or [])} package, {len(server.get('remotes') or [])} remote in one file)")
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_one_product.py"), sha, str(Path(tmp) / "one.txt")], capture_output=True, text=True, encoding="utf-8", timeout=1500)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    ok(last.startswith("PASS"), f"0 second product names: {last[:200]}")
    lines.append(f"FAIL test_one_product_linked: {len(fails)} check(s) failed" if fails else
                 "PASS test_one_product_linked: one lab verdict through IRIS and the MCP, the same readings on 4 surfaces, IRIS linked from the app, 0 second product names")
    print("\n".join(lines))
    if out:
        with out.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
