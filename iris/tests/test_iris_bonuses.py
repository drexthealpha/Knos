"""I3 test_iris_bonuses: one check per bonus Claude Code can earn on its own, on a running Knos Referee on IRIS.

1. PEX: a passing check run's PAY sends Knos's transaction from ProofDecision to SolanaSubmit (the Java operation),
   a message in that session's Visual Trace.
2. Workflow: a lab result over the payout threshold creates a PayoutApprovers task; answering it Approve turns the stored
   decision into PAY.
3. Custom adapters: a check-run file through CheckRunInbound (GitHubCheckRunPoller) and a devnet read through
   SolanaRpcOutbound (SolanaRead), each a message.
4. Embedded Python: knos.ready's criteria hash computed inside IRIS equals the one computed outside it.
5. Vector Search: the agent's SearchCriteria tool (the RAG knowledge base over the brief's criteria) answers with cosines.
6. Docker: I1's pass line.
7. ZPM: the module installed into a newly created empty namespace KNOSZPM.

    python iris/tests/test_iris_bonuses.py <container> [result file] [the I1 result line]
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

C = sys.argv[1] if len(sys.argv) > 1 else "knos-iris"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None
DOCKER = sys.argv[3] if len(sys.argv) > 3 else ""
HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
BASE = "http://localhost:52773"
AUTH = "Basic " + base64.b64encode(b"_SYSTEM:SYS").decode()
F = HERE / "fixtures"


def session(lines: list[str], ns: str = "KNOS") -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".script", delete=False, encoding="utf-8") as f:
        f.write(f'zn "{ns}"\n' + "\n".join(lines) + "\nhalt\n")
        path = f.name
    with open(path, encoding="utf-8") as stdin:
        r = subprocess.run(["docker", "exec", "-i", C, "iris", "session", "IRIS", "-U", "%SYS"], stdin=stdin, capture_output=True, text=True, timeout=900)
    Path(path).unlink(missing_ok=True)
    return r.stdout + r.stderr


def value(out: str, key: str) -> str:
    m = re.search(rf"{key}=([^\r\n]*)", out)
    return m.group(1).strip() if m else ""


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def headers(sid, target: str, source: str = "") -> int:
    q = f"SELECT COUNT(*) INTO :n FROM Ens.MessageHeader WHERE SessionId = {int(sid)} AND TargetConfigName = '{target}'" + (f" AND SourceConfigName = '{source}'" if source else "")
    return int(value(session([f"&sql({q})", 'write "N=", n, !']), "N") or -1)


def main() -> int:
    lines, fails = [], []

    def ok(c, what):
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        if not c:
            fails.append(what)

    code = json.loads((F / "briefs" / "code.json").read_text())
    lab = json.loads((F / "briefs" / "lab.json").read_text())
    post("/api/knos/brief", {"id": "github:example/shop", "amount_usdc": 20, "brief": code})
    post("/api/knos/brief", {"id": "lab-glucose", "amount_usdc": 120, "brief": lab})
    # 1. PEX on the PAY path
    d = post("/api/knos/proof", {"id": "github:example/shop", "kind": "checkrun", "payload": json.loads((F / "checkruns" / "pass.json").read_text())})
    time.sleep(8)
    n = headers(d.get("session"), "SolanaSubmit", "ProofDecision")
    ok(d.get("gate") == "PAY" and n >= 1, f"PEX: gate {d.get('gate')}, {n} message(s) ProofDecision to SolanaSubmit in session {d.get('session')} (Visual Trace)")
    # 3b. the custom outbound adapter, in the same PAY
    m = headers(d.get("session"), "SolanaRead")
    ok(m >= 1, f"custom outbound adapter SolanaRpcOutbound: {m} message(s) to SolanaRead in session {d.get('session')}")
    # 2. Workflow: a task created, then answered Approve
    w = post("/api/knos/proof", {"id": "lab-glucose", "kind": "observation", "payload": json.loads((F / "observations" / "glucose-pass.json").read_text())})
    time.sleep(8)
    out = session(['&sql(SELECT TOP 1 ID INTO :t FROM EnsLib_Workflow.TaskResponse WHERE %Status = \'Assigned\' OR %Status = \'Unassigned\' ORDER BY ID DESC)', 'write "TASK=", $get(t), !',
                   'set r = ##class(EnsLib.Workflow.TaskResponse).%OpenId($get(t))',
                   'if $isobject(r) { set sc = r.CompleteTask("Approve") write "DONE=", $select(sc:1, 1:$system.Status.GetErrorText(sc)), ! }'])
    time.sleep(10)
    g = value(session([f'&sql(SELECT Gate INTO :g FROM Knos_Iris_Data.Decision WHERE SessionId = {int(w.get("session") or 0)})', 'write "GATE=", $get(g), !']), "GATE")
    ok(w.get("gate") == "HUMAN" and value(out, "TASK") not in ("", "0") and value(out, "DONE") == "1" and g == "PAY",
       f"Workflow: gate {w.get('gate')}, task {value(out, 'TASK')} answered Approve ({value(out, 'DONE')}), the stored decision now {g}")
    # 3a. the custom inbound adapter: a check-run file
    name = f"bonus-{int(time.time())}.json"
    body = json.dumps({**json.loads((F / "checkruns" / "pass.json").read_text()), "repository": {"full_name": "example/shop"}})
    before = int(value(session(["&sql(SELECT COUNT(*) INTO :n FROM Ens.MessageHeader WHERE SourceConfigName = 'GitHubCheckRunPoller')", 'write "N=", n, !']), "N") or 0)
    subprocess.run(["docker", "exec", "-i", C, "sh", "-c", f"cat > /home/irisowner/knos/inbox/checkruns/{name}"], input=body, text=True, timeout=60)
    time.sleep(25)
    after = int(value(session(["&sql(SELECT COUNT(*) INTO :n FROM Ens.MessageHeader WHERE SourceConfigName = 'GitHubCheckRunPoller')", 'write "N=", n, !']), "N") or 0)
    left = subprocess.run(["docker", "exec", C, "sh", "-c", f"ls /home/irisowner/knos/inbox/checkruns/ | grep {name}"], capture_output=True, text=True).stdout.split()
    ok(after > before and any(x.endswith((".done", ".err")) for x in left), f"custom inbound adapter CheckRunInbound: {after - before} message(s) from the poller, the file now {left}")
    # 4. Embedded Python importing src/knos
    sys.path.insert(0, str(ROOT / "src"))
    from knos import ready
    inside = value(session([f'write "HASH=", ##class(Knos.Iris.Py.Ready).Hash({json.dumps(json.dumps(code))}), !']), "HASH")
    ok(inside == ready.criteria_hash(code), f"Embedded Python: knos.ready inside IRIS {inside[:16]}, outside {ready.criteria_hash(code)[:16]}")
    # 5. Vector Search through the agent's RAG tool
    h = ready.criteria_hash(lab)
    near = value(session([f'write "NEAR=", ##class(Knos.Iris.AI.RefereeTools).SearchCriteria("{h}", "glucose under 7.0 mmol/L in 12 samples"), !']), "NEAR")
    try:
        rows = json.loads(near)
    except ValueError:
        rows = []
    ok(len(rows) >= 1 and all("cosine" in r for r in rows), f"Vector Search: the agent's SearchCriteria tool answers {near[:160]}")
    # 6. Docker
    ok(DOCKER.startswith("PASS"), f"Docker: {DOCKER[:160] or 'I1 not given'}")
    # 7. ZPM into a new empty namespace
    out = session(['if \'##class(Config.Namespaces).Exists("KNOSZPM") { set p("Globals") = "KNOSZPM", p("Routines") = "KNOSZPM" set d("Directory") = "/usr/irissys/mgr/knoszpm/" do ##class(%File).CreateDirectoryChain(d("Directory")) do ##class(SYS.Database).CreateDatabase(d("Directory")) do ##class(Config.Databases).Create("KNOSZPM", .d) do ##class(Config.Namespaces).Create("KNOSZPM", .p) }',
                   'write "MADE=", ##class(Config.Namespaces).Exists("KNOSZPM"), !',
                   'write "IPM=", ##class(%Dictionary.CompiledClass).%ExistsId("%IPM.Main"), !'], ns="%SYS")
    zpm = ""
    if value(out, "IPM") == "1":
        res = session(['zpm "load /home/irisowner/knos/iris -v"', 'write "LOADED=", ##class(%Dictionary.CompiledClass).%ExistsId("Knos.Iris.Setup"), !'], ns="KNOSZPM")
        zpm = value(res, "LOADED")
    ok(value(out, "MADE") == "1" and zpm == "1", f"ZPM: namespace KNOSZPM {'made' if value(out, 'MADE') == '1' else 'not made'}; IPM {'present' if value(out, 'IPM') == '1' else 'not in this image'}; module {'installed' if zpm == '1' else 'not installed'}")
    bonus = {"PEX": "PEX", "Workflow": "Workflow", "custom": "custom adapters", "Embedded": "Embedded Python", "Vector": "Vector Search", "Docker": "Docker", "ZPM": "ZPM"}
    failed = {v for k, v in bonus.items() if any(x.startswith(k) for x in fails)}
    lines.append("PASS test_iris_bonuses: 7 of 7 bonus checks pass" if not fails else f"FAIL test_iris_bonuses: {7 - len(failed)} of 7 bonus checks pass; failed: {', '.join(sorted(failed))}")
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
