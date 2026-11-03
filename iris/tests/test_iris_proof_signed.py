"""I2 test_iris_proof_signed: proof is signed and the image's password is gone.
- a check run without GitHub's X-Hub-Signature-256 (or with a wrong one) is refused with 401, on /proof and /webhook;
  a signed GitHub check_run event on /webhook is decided;
- a referee verdict whose "signature" does not verify (forged, or none) is rejected by the decision; a signed one is read;
- _SYSTEM with the image's SYS is refused on the web port (52773) and the superserver (1972); the .env password works.

    python iris/tests/test_iris_proof_signed.py [http://localhost:52773] [result file]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import iris_env  # iris/tests: the password and the signing secrets from iris/.env

HERE = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:52773"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None
F = HERE / "fixtures"


def post(path: str, data: bytes, headers: dict) -> tuple[int, dict]:
    req = urllib.request.Request(BASE + path, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def get_status(path: str, password: str) -> int:
    req = urllib.request.Request(BASE + path, headers={"Authorization": iris_env.auth(password)})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def superserver(password: str) -> str:
    """'ok' when _SYSTEM logs in on 1972 with this password, else the refusal (intersystems-irispython)."""
    try:
        import iris  # noqa: PLC0415 - the native API, installed for this test only
    except ImportError as e:
        return f"no native API: {e}"
    try:
        conn = iris.connect(urlparse(BASE).hostname, 1972, "USER", "_SYSTEM", password)
        conn.close()
        return "ok"
    except Exception as e:  # noqa: BLE001 - the refusal is the answer
        return f"refused: {str(e)[:120]}"


def main() -> int:
    lines, fails = [], 0

    def ok(c: bool, what: str) -> None:
        nonlocal fails
        fails += not c
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")

    plain = {"Authorization": iris_env.auth(), "Content-Type": "application/json"}
    for bid, f, amount in (("github:example/shop", "code.json", 20), ("lab-glucose", "lab.json", 120)):
        s, r = post("/api/knos/brief", json.dumps({"id": bid, "amount_usdc": amount, "brief": json.loads((F / "briefs" / f).read_text())}).encode(), plain)
        ok(s == 200 and r.get("ready") in (1, True), f"lock {bid}: HTTP {s}, ready {r.get('ready')}")
    event = json.loads((F / "checkruns" / "pass.json").read_text())
    proof = json.dumps({"id": "github:example/shop", "kind": "checkrun", "payload": event}).encode()
    s, r = post("/api/knos/proof", proof, plain)
    ok(s == 401, f"an unsigned check run on /proof: HTTP {s} {str(r.get('error', ''))[:90]}")
    s, r = post("/api/knos/proof", proof, {**plain, "X-Hub-Signature-256": iris_env.sign(proof, "not-the-secret")})
    ok(s == 401, f"a check run signed with another secret on /proof: HTTP {s}")
    raw = json.dumps(event).encode()
    s, r = post("/api/knos/webhook", raw, {**plain, "X-GitHub-Event": "check_run"})
    ok(s == 401, f"an unsigned GitHub check_run webhook on /webhook: HTTP {s}")
    s, r = post("/api/knos/webhook", raw, {**plain, "X-GitHub-Event": "check_run", "X-Hub-Signature-256": iris_env.sign(raw)})
    ok(s == 200 and r.get("gate") == "PAY", f"the same webhook signed: HTTP {s}, decision {r.get('decision')}, gate {r.get('gate')}, session {r.get('session')}")
    verdict = json.loads((F / "verdicts" / "passed.json").read_text())
    for name, v, want in (("a forged verdict (signed with another secret)", iris_env.signed_verdict(verdict, "not-the-secret"), "REJECT"),
                          ("an unsigned verdict", verdict, "REJECT"),
                          ("a verdict whose body changed after signing", {**iris_env.signed_verdict(verdict), "failed": ["works"]}, "REJECT"),
                          ("a signed verdict (control)", iris_env.signed_verdict(verdict), "read")):
        s, r = post("/api/knos/proof", json.dumps({"id": "lab-glucose", "kind": "verdict", "payload": v}).encode(), plain)
        good = s == 200 and ((r.get("gate") == "REJECT" and "signature" in str(r.get("decision"))) if want == "REJECT" else
                             (r.get("gate") != "REJECT" and r.get("decision") == "met"))
        ok(good, f"{name}: HTTP {s}, decision {r.get('decision')}, gate {r.get('gate')}, by {r.get('referee')}, session {r.get('session')}")
    s_sys, s_env = get_status("/api/knos/health", "SYS"), get_status("/api/knos/health", iris_env.value("IRIS_PASSWORD"))
    ok(s_sys == 401 and s_env == 200, f"port 52773: _SYSTEM with SYS HTTP {s_sys}; with the .env password HTTP {s_env}")
    n_sys, n_env = superserver("SYS"), superserver(iris_env.value("IRIS_PASSWORD"))
    ok(n_sys.startswith("refused") and n_env == "ok", f"port 1972 (native API): _SYSTEM with SYS {n_sys}; with the .env password {n_env}")
    lines.append(f"PASS test_iris_proof_signed: {len(lines)} of {len(lines)} checks" if not fails else f"FAIL test_iris_proof_signed: {fails} check(s) failed")
    print("\n".join(lines))
    if OUT:
        with OUT.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
