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

from common import CONFIG, HERE, JOB_DIR, call, sha256_file, view

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


def run_test(output: Path) -> tuple[bool, str, float]:
    with tempfile.TemporaryDirectory() as d:
        shutil.copy(JOB_DIR / "test_slug.py", Path(d) / "test_slug.py")
        shutil.copy(output, Path(d) / "solution.py")
        t0 = time.time()
        try:
            p = subprocess.run([sys.executable, "-E", "-s", "-B", "test_slug.py"], cwd=d, capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            return False, "the test ran over 20 s", time.time() - t0
        said = (p.stdout + p.stderr).strip().splitlines()
        return p.returncode == 0, said[-1] if said else "", time.time() - t0


def check(job_id: str) -> dict:
    job = view(CONFIG["contract"], "get_job", {"id": job_id})
    if not job:
        raise SystemExit(f"no job {job_id}")
    test_hash = sha256_file(JOB_DIR / "test_slug.py")
    out = {"job": job_id, "criteria_hash": job["criteria_hash"], "test_sha256": test_hash, "attempts": []}
    if test_hash != job["criteria_hash"]:
        out["refused"] = "the test file is not the one locked at funding"
        return out
    names = {v: k for k, v in CONFIG["agents"].items()}
    for a in job["attempts"]:
        r = {"agent": a["agent"], "output_sha256": a["output_sha256"]}
        f = HERE / "out" / names.get(a["agent"], "?") / "solution.py"
        if not f.is_file() or sha256_file(f) != a["output_sha256"]:
            r.update(passed=False, reason="the output file is not the one submitted")
        else:
            ok, said, secs = run_test(f)
            r.update(passed=ok, reason=said, test_seconds=round(secs, 2))
            if ok and job["state"] == "Open":
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
