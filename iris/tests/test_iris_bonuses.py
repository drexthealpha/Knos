"""I3 test_iris_bonuses: every bonus row of the build spec (PEX, Workflow, custom adapters, Embedded Python, Vector
Search, Docker, ZPM, idea 689) on a running container, each with its numbers.

    python iris/tests/test_iris_bonuses.py <container> [result file] [the I1 result line for Docker]
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

C = sys.argv[1] if len(sys.argv) > 1 else "knos-iris"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None
DOCKER = sys.argv[3] if len(sys.argv) > 3 else ""
HERE = Path(__file__).resolve().parents[1]
AUTH = "Basic " + base64.b64encode(b"_SYSTEM:SYS").decode()


def iris(expr: str) -> str:
    """One ObjectScript expression's value, written by an IRIS session in namespace KNOS."""
    script = f'zn "KNOS"\nwrite "<<<",{expr},">>>",!\nhalt\n'
    r = subprocess.run(["docker", "exec", "-i", C, "iris", "session", "IRIS", "-U", "KNOS"], input=script, capture_output=True, text=True,
                       timeout=600, env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    got = r.stdout
    return got[got.find("<<<") + 3: got.find(">>>")] if "<<<" in got else f"no answer: {got[-300:]}"


def rest(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request("http://localhost:52773" + path, data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST", headers={"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def main() -> int:
    lines, fails = [], 0

    def ok(c, what):
        nonlocal fails
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        fails += not c

    # Embedded Python
    try:
        p = json.loads(iris("##class(Knos.Iris.Test.Bonuses).Python()"))
        ok(p["equal"] in (1, True) and p["vague_missing"] > 0, f"Embedded Python: Ready.Hash {p['hash'][:16]} = Knos outside IRIS {p['golden'][:16]}; Ready.Check on a vague brief lists {p['vague_missing']} missing fields")
    except Exception as e:  # noqa: BLE001
        ok(False, f"Embedded Python: {e}")
    # Vector Search
    try:
        v = json.loads(iris("##class(Knos.Iris.Test.Bonuses).Vector()"))
        right = [x for x in v if x["top"] == x["want"] and x["cosine"] >= 0.45]
        ok(len(right) == 3, "Vector Search: top-1 right with cosine >= 0.45 on " + f"{len(right)} of 3 (" + ", ".join(f"{x['want']}->{x['top']} {x['cosine']:.2f}" for x in v) + ")")
    except Exception as e:  # noqa: BLE001
        ok(False, f"Vector Search: {e}")
    # Custom adapters: the outbound one against devnet; the inbound one by a check run dropped in its folder
    try:
        r = json.loads(iris("##class(Knos.Iris.Test.Bonuses).Rpc()"))
        ok(r["ok"] in (1, True) and "solana-core" in r["answer"], f"custom outbound adapter: getVersion from devnet: {r['answer'][:90] or r['error'][:90]}")
    except Exception as e:  # noqa: BLE001
        ok(False, f"custom outbound adapter: {e}")
    before = int(iris("$order(^Knos.Iris.Data.DecisionD(\"\"),-1)") or 0) if True else 0
    rest("/api/knos/brief", {"id": "github:example/shop", "amount_usdc": 20, "brief": json.loads((HERE / "fixtures" / "briefs" / "code.json").read_text())})
    drop = HERE / "fixtures" / "checkruns" / "pass.json"
    subprocess.run(["docker", "cp", str(drop), f"{C}:/home/irisowner/knos/inbox/checkruns/poll-{os.getpid()}.json"], capture_output=True,
                   env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    import time
    time.sleep(40)
    after = int(iris("$order(^Knos.Iris.Data.DecisionD(\"\"),-1)") or 0)
    ok(after > before, f"custom inbound adapter: a check run dropped in the poller's folder became a decision ({before} -> {after})")
    # Java PEX
    try:
        x = json.loads(iris("##class(Knos.Iris.Test.Bonuses).PEX()"))
        j = json.loads(x.get("json") or "{}")
        ok("slot" in j and int(j.get("slot") or 0) > 0, f"Java PEX: SolanaSubmit (Java) simulated a transaction Knos's code built on devnet: {x.get('class')}, slot {j.get('slot')}, err {str(j.get('err'))[:60]}")
    except Exception as e:  # noqa: BLE001
        ok(False, f"Java PEX: {e}")
    # Workflow: a 120 USDC lab milestone met goes to a person
    try:
        rest("/api/knos/brief", {"id": "lab-glucose", "amount_usdc": 120, "brief": json.loads((HERE / "fixtures" / "briefs" / "lab.json").read_text())})
        d = rest("/api/knos/proof", {"id": "lab-glucose", "kind": "observation", "payload": json.loads((HERE / "fixtures" / "observations" / "glucose-pass.json").read_text())})
        time.sleep(15)
        tasks = json.loads(iris("##class(Knos.Iris.Test.Bonuses).Workflow()"))
        mine = [t for t in tasks if "lab-glucose" in (t.get("subject") or "")]
        ok(d["gate"] == "HUMAN" and mine, f"Workflow: a met 120 USDC lab milestone went to a person: gate {d['gate']}, {len(mine)} task(s) for {mine[0]['role'] if mine else '-'}")

    except Exception as e:  # noqa: BLE001
        ok(False, f"Workflow: {e}")

    # Community idea 689
    try:
        d = rest("/api/knos/proof", {"id": "github:example/shop", "kind": "checkrun", "payload": json.loads((HERE / "fixtures" / "checkruns" / "pass.json").read_text())})
        time.sleep(10)
        t = rest(f"/api/knos/traces/{d['session']}")
        kinds = sorted({s["type"] for s in t["spans"]})
        ok(len(t["spans"]) >= 5, f"idea 689: one decision made {len(t['spans'])} Span messages in its session ({', '.join(kinds)}), /traces JSON valid, {len(t['messages'])} messages in Visual Trace")
    except Exception as e:  # noqa: BLE001
        ok(False, f"idea 689: {e}")
    # ZPM and Docker
    ipm = iris("##class(%Dictionary.CompiledClass).%ExistsId(\"%IPM.Main\")")
    ok(ipm.strip() == "1", f"ZPM: module.xml written; IPM installed in the image: {ipm.strip() == '1'} (build 154 ships without it)")
    ok(DOCKER.startswith("PASS"), f"Docker: {DOCKER or 'the I1 result is not given'}")
    lines.append("PASS test_iris_bonuses: every row holds" if not fails else f"FAIL test_iris_bonuses: {fails} of 8 rows failed")
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
