"""I3 test_iris_trace_complete: a decision's trace lists its tool calls by its session id.
1. One decision through the agent's live path (stub provider, no key): GET /api/knos/traces/<session> holds its tool
   spans (GetBrief, GetCheckRun, SearchCriteria), each saved with that session id.
2. The audit hook is registered on AI Hub's own tool manager: an agent from Knos.Iris.AI.Referee.Audited carries
   Knos.Iris.AI.TraceAudit as its audit policy, holds the referee's tools, and a tool AI Hub executes is written by
   TraceAudit.%LogExecution as a span in the session it ran for.
The tests' overrides (^Knos.LLM("mode"), ^Knos.LLM("provider")) are removed at the end.

    python iris/tests/test_iris_trace_complete.py <container> [result file]
"""
from __future__ import annotations

import json
import random
import sys
import urllib.request
from pathlib import Path

import iris_env  # iris/tests: the password and the signing secrets from iris/.env
import test_iris_bonuses as b  # session() and value() for the container (its argv: <container> [result file])

OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None
WANT = ("GetBrief", "GetCheckRun", "SearchCriteria")


def call(path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(b.BASE + path, data=data, method="GET" if body is None else "POST", headers=iris_env.headers(data, (body or {}).get("kind", "")))
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def main() -> int:
    lines, fails = [], 0

    def ok(c: bool, what: str) -> None:
        nonlocal fails
        fails += not c
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")

    try:
        b.session(['set ^Knos.LLM("mode") = "live", ^Knos.LLM("provider") = "stub"'])
        call("/api/knos/brief", {"id": "github:example/shop", "amount_usdc": 20, "brief": json.loads((b.F / "briefs" / "code.json").read_text())})
        d = call("/api/knos/proof", {"id": "github:example/shop", "kind": "checkrun", "payload": json.loads((b.F / "checkruns" / "pass.json").read_text())})
        sid = int(d.get("session") or 0)
        t = call(f"/api/knos/traces/{sid}")
        tools = [s for s in t.get("spans", []) if s.get("type") == "tool"]
        names = [s.get("name") for s in tools]
        ok(sid > 0 and "stub" in str(d.get("referee")) and all(w in names for w in WANT),
           f"decision {d.get('decision')}, gate {d.get('gate')}, by {d.get('referee')}, session {sid}: /api/knos/traces/{sid} lists {len(tools)} tool call(s): {', '.join(names)}")
        out = b.session([f'&sql(SELECT COUNT(*) INTO :n FROM Knos_Iris_Data.Span WHERE SessionId = {sid} AND Kind = \'tool\')', 'write "BYSESSION=", n, !',
                         '&sql(SELECT COUNT(*) INTO :m FROM Knos_Iris_Data.Span WHERE Kind = \'tool\' AND SessionId IS NULL)', 'write "NOSESSION=", m, !'])
        ok(int(b.value(out, "BYSESSION") or 0) == len(tools) >= 3,
           f"Knos_Iris_Data.Span: {b.value(out, 'BYSESSION')} tool row(s) with SessionId {sid}; tool rows with no session in the table: {b.value(out, 'NOSESSION')}")
        fake = random.randint(900_000_000, 999_999_999)
        hook = b.session([
            'set a = ##class(Knos.Iris.AI.Referee).Audited(##class(Knos.Iris.AI.Referee).%New())',
            'write "POLICY=", $classname(a.ToolManager.AuditPolicy), !',
            'write "TOOLS=", a.ToolManager.GetToolStatuses().%Size(), !',
            f'set ^||Knos.TraceSession = {fake}',
            'set r = a.ToolManager.ExecuteTool("GetBrief", {"id":"github:example/shop"}) write "EXEC=", $isobject(r), !',
            f'&sql(SELECT COUNT(*) INTO :k FROM Knos_Iris_Data.Span WHERE SessionId = {fake} AND Kind = \'tool\')', 'write "HOOKSPANS=", k, !'])
        ok(b.value(hook, "POLICY") == "Knos.Iris.AI.TraceAudit" and int(b.value(hook, "TOOLS") or 0) == 5 and b.value(hook, "EXEC") == "1"
           and int(b.value(hook, "HOOKSPANS") or 0) == 1,
           f"AI Hub's tool manager: audit policy {b.value(hook, 'POLICY') or 'none'}, {b.value(hook, 'TOOLS') or 0} tools held, GetBrief executed by AI Hub, "
           f"{b.value(hook, 'HOOKSPANS') or 0} span written by TraceAudit.%LogExecution in session {fake}")
        b.session([f'&sql(DELETE FROM Knos_Iris_Data.Span WHERE SessionId = {fake})'])
    finally:
        b.session(['kill ^Knos.LLM("mode"), ^Knos.LLM("provider")'])
    lines.append(f"PASS test_iris_trace_complete: {len(lines)} of {len(lines)} checks" if not fails else f"FAIL test_iris_trace_complete: {fails} check(s) failed")
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
