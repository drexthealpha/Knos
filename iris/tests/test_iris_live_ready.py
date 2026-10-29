"""I9 test_iris_live_ready: the live path proved with the stub provider, on a running Knos Referee on IRIS. With live
mode and the stub, one decision goes through the agent with its tool calls traced; the spend cap refuses call 31 and
any call past 2.00 USD; with no key for a real provider, live mode refuses in one plain sentence. The tests' overrides
(^Knos.LLM("mode"), ^Knos.LLM("provider")) are removed at the end.

    python iris/tests/test_iris_live_ready.py <container> [http://localhost:52773] [result file]
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
C = sys.argv[1] if len(sys.argv) > 1 else "knos-iris"
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:52773"
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else None
AUTH = "Basic " + base64.b64encode(b"_SYSTEM:SYS").decode()


def session(lines: list[str]) -> str:
    """ObjectScript lines run in namespace KNOS, from a file on stdin (no heredoc); what they wrote."""
    with tempfile.NamedTemporaryFile("w", suffix=".script", delete=False, encoding="utf-8") as f:
        f.write("zn \"KNOS\"\n" + "\n".join(lines) + "\nhalt\n")
        path = f.name
    with open(path, encoding="utf-8") as stdin:
        r = subprocess.run(["docker", "exec", "-i", C, "iris", "session", "IRIS", "-U", "%SYS"], stdin=stdin, capture_output=True, text=True, timeout=300)
    Path(path).unlink(missing_ok=True)
    return r.stdout


def tools() -> int:
    got = re.search(r"TOOLS=(\d+)", session(['&sql(SELECT COUNT(*) INTO :n FROM Knos_Iris_Data.Span WHERE Kind = \'tool\')', 'write "TOOLS=", n, !']))
    return int(got.group(1)) if got else -1


def proof() -> dict:
    body = {"id": "github:example/shop", "kind": "checkrun", "payload": json.loads((HERE / "fixtures" / "checkruns" / "pass.json").read_text())}
    req = urllib.request.Request(BASE + "/api/knos/proof", json.dumps(body).encode(), {"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def main() -> int:
    lines, fails = [], []

    def ok(c, what):
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        if not c:
            fails.append(what)

    try:
        session(['kill ^Knos.LLM', 'set ^Knos.LLM("mode") = "live", ^Knos.LLM("provider") = "stub"'])
        before = tools()
        d = proof()
        after = tools()
        ok("stub" in str(d.get("referee")) and after - before >= 3, f"live mode, stub provider: decision {d.get('decision')}, gate {d.get('gate')}, by {d.get('referee')}; {after - before} tool calls traced")
        session(['set ^Knos.LLM("calls") = 30'])
        d = proof()
        ok("spend cap" in str(d.get("referee")) and "30 of 30" in str(d.get("referee")), f"call 31 refused: {d.get('referee')}")
        session(['set ^Knos.LLM("calls") = 0, ^Knos.LLM("usd") = 2.00'])
        d = proof()
        ok("spend cap" in str(d.get("referee")) and "USD" in str(d.get("referee")), f"a call past 2.00 USD refused: {d.get('referee')}")
        session(['kill ^Knos.LLM("calls"), ^Knos.LLM("usd")', 'set ^Knos.LLM("provider") = "anthropic"'])
        d = proof()
        said = str(d.get("referee") or "")
        ok("needs a model key" in said and said.count(".") <= 2, f"no key set: {said}")
    finally:
        session(['kill ^Knos.LLM'])
    lines.append("PASS test_iris_live_ready: one decision through the agent with the stub provider and its tool calls traced; call 31 and a call past 2.00 USD refused; "
                 "with no key, one plain sentence" if not fails else f"FAIL test_iris_live_ready: {len(fails)} check(s) failed")
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
