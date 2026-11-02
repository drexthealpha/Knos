"""K4 one decision, six parts: a check-run file through CheckRunInbound for a brief over the payout threshold, so one
session's trace holds a message from each of CheckRunInbound (GitHubCheckRunPoller), Embedded Python (knos.ready's hash),
Vector Search (the nearest locked criterion), Workflow (PayoutApprovers, answered Approve), Java PEX (SolanaSubmit) and
SolanaRpcOutbound (SolanaRead).

    python iris/tests/test_iris_one_trace.py [container] [result file]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_iris_bonuses as b  # noqa: E402

OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None
BRIEF = "github:example/onetrace"


def main() -> int:
    code = json.loads((b.F / "briefs" / "code.json").read_text())
    r = b.post("/api/knos/brief", {"id": BRIEF, "amount_usdc": 120, "brief": code})
    q = "SELECT MAX(SessionId) INTO :n FROM Ens.MessageHeader WHERE SourceConfigName = 'GitHubCheckRunPoller'"
    before = int(b.value(b.session([f"&sql({q})", 'write "N=", +$get(n), !']), "N") or 0)
    name = f"onetrace-{int(time.time())}.json"
    body = json.dumps({**json.loads((b.F / "checkruns" / "pass.json").read_text()), "repository": {"full_name": "example/onetrace"}})
    subprocess.run(["docker", "exec", "-i", b.C, "sh", "-c", f"cat > /home/irisowner/knos/inbox/checkruns/{name}"], input=body, text=True, timeout=60)
    sid = 0
    for _ in range(18):
        time.sleep(10)
        sid = int(b.value(b.session([f"&sql({q})", 'write "N=", +$get(n), !']), "N") or 0)
        if sid > before:
            break
    out = b.session([f"&sql(SELECT TOP 1 ID INTO :t FROM EnsLib_Workflow.TaskResponse WHERE %Status <> 'Completed' AND %Subject [ '{BRIEF}' ORDER BY ID DESC)",
                     'write "TASK=", $get(t), !', 'set r = ##class(EnsLib.Workflow.TaskResponse).%OpenId($get(t))',
                     'if $isobject(r) { set sc = r.CompleteTask("Approve") write "DONE=", $select(sc:1, 1:$system.Status.GetErrorText(sc)), ! }'])
    trace: dict = {}
    for _ in range(12):
        time.sleep(10)
        req = b.urllib.request.Request(f"{b.BASE}/api/knos/traces/{sid}", headers={"Authorization": b.AUTH})
        with b.urllib.request.urlopen(req, timeout=120) as resp:
            trace = json.loads(resp.read())
        if any(m["to"] == "SolanaRead" for m in trace.get("messages", [])):
            break
    msgs, spans = trace.get("messages", []), trace.get("spans", [])
    parts = {"CheckRunInbound": any(m["from"] == "GitHubCheckRunPoller" for m in msgs),
             "Embedded Python": any("Embedded Python" in (s.get("name") or "") for s in spans),
             "Vector Search": any("Vector Search" in (s.get("name") or "") for s in spans),
             "Workflow": any(m["to"] == "PayoutApprovers" for m in msgs),
             "Java PEX": any(m["to"] == "SolanaSubmit" for m in msgs),
             "SolanaRpcOutbound": any(m["to"] == "SolanaRead" for m in msgs)}
    lines = [f"     brief {BRIEF} locked: ready {r.get('ready')}, 120 USDC over the threshold; file {name}; session {sid}; "
             f"task {b.value(out, 'TASK')} answered Approve ({b.value(out, 'DONE')}); {len(msgs)} messages, {len(spans)} spans"]
    lines += [f"{'ok  ' if v else 'FAIL'} {k}" for k, v in parts.items()]
    got = sum(parts.values())
    lines.append(f"{'PASS' if got == 6 else 'FAIL'} one trace: {got} of 6 parts in session {sid}, "
                 f"{b.BASE}/csp/healthshare/knos/EnsPortal.VisualTrace.zen?SESSIONID={sid}")
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0 if got == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
