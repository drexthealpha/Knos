"""The Knos checker for one job: for each attempt on chain, it checks the output file's sha256 against the one the agent
submitted and the test file's sha256 against the job's criteria hash, then runs the locked test on that output in a
folder of its own, with a time limit. Only an output that passes gets a signed checker token, and the token is sent
with release_job, which pays that agent the bid. A failing output gets nothing; its reason is printed.

    python near/agents/checker.py <job id>

The checker's key is ~/.knos-checker/checker.pem (made by near/agents/setup_swarm.py, never printed); its public half
is set on chain by 2 of the 3 owners (propose_checker_key).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from common import CONFIG, HERE, JOB_DIR, JOB_TEST, call, sha256_file, tests, view

# the hosted app signs with its own checker key (KNOS_CHECKER_PEM_FILE, KNOS_CHECKER_KID), which 2 owners set and can remove
KEY = Path(os.environ.get("KNOS_CHECKER_PEM_FILE") or Path.home() / ".knos-checker" / "checker.pem")
KID = os.environ.get("KNOS_CHECKER_KID") or CONFIG["checker_kid"]
ISS = "https://knos.onrender.com/checker"


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign(claims: dict) -> str:
    k = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    head = b64u(json.dumps({"alg": "RS256", "kid": KID, "typ": "JWT"}).encode())
    body = b64u(json.dumps(claims).encode())
    sig = k.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64u(sig)}"


def _claim_of(test: str) -> dict:
    """The claim whose locked test this is (near/claims/claims.json): its module name, its data files and its time limit.
    A test that imports its own module (`kepler10b_period`) or reads data next to it says so there; the test is unchanged."""
    try:
        claims = json.loads((HERE.parent / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]
    except (OSError, ValueError, KeyError):
        return {}
    return next((c for c in claims if c.get("test") == test), {})


def run_test(output: Path, test: str = JOB_TEST) -> tuple[bool, str, float]:
    c = _claim_of(test)
    limit = float(c.get("timeout_s") or 20)
    with tempfile.TemporaryDirectory() as d:
        shutil.copy(JOB_DIR / test, Path(d) / test)
        shutil.copy(output, Path(d) / "solution.py")
        if c.get("module"):   # the name the locked test imports agent A's or B's code under
            shutil.copy(output, Path(d) / f"{c['module']}.py")
        for rel in c.get("data") or []:   # the data the test reads next to itself; it checks each file's sha256
            (Path(d) / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(JOB_DIR / rel, Path(d) / rel)
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, "-E", "-s", "-B", test], cwd=d, capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            return False, f"the test ran over {limit:.0f} s", time.time() - t0
        said = (p.stdout + p.stderr).strip().splitlines()
        line = said[-1] if said else ""
        measured = [x for x in said if c.get("said_from") and x.strip().startswith(c["said_from"])]
        if measured and line in ("PASS", "") or measured and line.startswith(("FAIL", "AssertionError")):
            line = f"{measured[-1].strip()}: {'PASS' if p.returncode == 0 else line}"   # the measured number beside the verdict
        return p.returncode == 0, line, time.time() - t0


def release_one(job_id: str, payee: str, output_sha256: str, criteria_hash: str, model: dict | None = None) -> dict:
    """Sign the token for the agent whose output passed and send the release: the one step a visitor waits for. With a
    NEAR AI Cloud signature of the model call that wrote that output ({text, signature, signer}) from a signer the owners
    added on chain, the token names its text and release_job_verified checks the signature with ecrecover before it
    pays; otherwise release_job, which logs "fixed rule, no model signature"."""
    claims = {"iss": ISS, "aud": CONFIG["contract"], "exp": int(time.time()) + 600, "iat": int(time.time()),
              "jti": str(uuid.uuid4()), "job": job_id, "payee": payee, "output_sha256": output_sha256, "criteria_hash": criteria_hash}
    t0 = time.time()
    verified = False
    if model and model.get("text") and model.get("signature") and model.get("signer"):
        try:
            signers = (view(CONFIG["contract"], "get_switches", {}) or {}).get("model_signers") or []
            verified = str(model["signer"]).lower().removeprefix("0x") in signers
        except Exception:  # noqa: BLE001 - an older contract or an unread view: the plain release
            verified = False
    # every receipt executed, the payment callback included; finality follows within seconds
    if verified:
        claims["model_text"] = model["text"]
        r = call(CONFIG["relayer"], CONFIG["contract"], "release_job_verified",
                 {"id": job_id, "token": sign(claims), "model_text": model["text"], "model_signature": model["signature"]},
                 gas="150 Tgas", wait="EXECUTED_OPTIMISTIC")
    else:
        r = call(CONFIG["relayer"], CONFIG["contract"], "release_job", {"id": job_id, "token": sign(claims)}, gas="150 Tgas", wait="EXECUTED_OPTIMISTIC")
    r["model_verified"] = verified
    r["seconds"] = round(time.time() - t0, 1)
    return r


def check(job_id: str, release: bool = True) -> dict:
    job = view(CONFIG["contract"], "get_job", {"id": job_id})
    if not job:
        raise SystemExit(f"no job {job_id}")
    test = tests().get(job["criteria_hash"])   # the one test file whose sha256 the job locked at funding
    out = {"job": job_id, "criteria_hash": job["criteria_hash"], "test_sha256": job["criteria_hash"] if test else None, "test": test, "attempts": []}
    if not test:
        out["refused"] = "no test file has the hash locked at funding"
        return out
    names = {v: k for k, v in CONFIG["agents"].items()}
    for a in job["attempts"]:
        r = {"agent": a["agent"], "output_sha256": a["output_sha256"]}
        f = HERE / "out" / job_id / names.get(a["agent"], "?") / "solution.py"
        if not f.is_file():   # jobs answered before answers had a folder per job
            f = HERE / "out" / names.get(a["agent"], "?") / "solution.py"
        if not f.is_file() or sha256_file(f) != a["output_sha256"]:
            r.update(passed=False, reason="the output file is not the one submitted")
        else:
            ok, said, secs = run_test(f, test)
            r.update(passed=ok, reason=said, test_seconds=round(secs, 2))
            if ok and job["state"] == "Open" and release:
                claims = {"iss": ISS, "aud": CONFIG["contract"], "exp": int(time.time()) + 600, "iat": int(time.time()),
                          "jti": str(uuid.uuid4()), "job": job_id, "payee": a["agent"], "output_sha256": a["output_sha256"],
                          "criteria_hash": job["criteria_hash"]}
                t0 = time.time()
                r["release"] = call(CONFIG["relayer"], CONFIG["contract"], "release_job", {"id": job_id, "token": sign(claims)}, gas="120 Tgas")
                r["release"]["seconds"] = round(time.time() - t0, 1)
                job["state"] = "Paying" if r["release"]["ok"] else job["state"]
        out["attempts"].append(r)
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    print(json.dumps(check(sys.argv[1]), indent=1))
