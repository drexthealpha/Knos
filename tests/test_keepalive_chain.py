"""Never asleep (.github/workflows/worker.yml): every run of the always-on worker's chain pings the app's health check in
a job of its own, and the chain's own watchdog is what keeps that going. Here: chain.py's `healthz` against a local
server that fails first, and the job's shape in worker.yml."""
from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from knos.proof import chain

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"


def test_healthz_tries_again_after_a_cold_start_and_says_each_answer():
    seq = iter([503, 502, 200])
    said, naps = [], []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(next(seq)); self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/healthz"
    import urllib.request
    try:
        assert chain.healthz("https://x.invalid/healthz", opener=lambda req, timeout: urllib.request.urlopen(url, timeout=timeout),
                             sleep=naps.append, say=said.append)
    finally:
        srv.shutdown()
    assert naps == [20.0, 20.0] and [s.split(":")[1].split()[0] for s in said] == ["503", "502", "200"]
    # all tries fail: False after the last one (here 2); no answer at all is said by name; http is refused before anything is sent
    assert not chain.healthz("https://x.invalid/healthz", tries=2, opener=lambda r, timeout: (_ for _ in ()).throw(OSError("down")),
                             sleep=naps.append, say=said.append)
    assert said[-1].startswith("healthz attempt 2: OSError")
    with pytest.raises(chain.Refused):
        chain.healthz("http://knos.onrender.com/healthz")


def test_the_command_runs_with_nothing_but_the_standard_library():
    r = subprocess.run([sys.executable, "-I", str(ROOT / "src" / "knos" / "proof" / "chain.py"), "healthz", "--url", "http://127.0.0.1:9/healthz"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "https" in r.stderr                                # refused, said, red


def test_every_chain_run_pings_in_a_job_that_holds_nothing_and_waits_for_nothing():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((WF / "worker.yml").read_text(encoding="utf-8"))
    job = doc["jobs"]["healthz"]
    assert job["if"] == "github.event_name == 'workflow_dispatch'"           # every run of the chain (each starts the next by dispatch)
    assert job["permissions"] == {"contents": "read"} and "needs" not in job and "secrets." not in json.dumps(job)
    assert [s.get("uses", "").split("@")[0] for s in job["steps"]] == ["actions/checkout", ""]
    assert job["steps"][0]["with"] == {"persist-credentials": False, "sparse-checkout": "src/knos/proof"}
    assert job["steps"][-1]["run"] == "python3 -I src/knos/proof/chain.py healthz" and chain.HEALTHZ == "https://knos.onrender.com/healthz"
    # nothing in the chain waits for it, and the relay's own jobs are unchanged
    assert not any("healthz" in str(j.get("needs", "")) for j in doc["jobs"].values())
    # the watchdog that revives the chain runs on GitHub's timer, on every event worker.yml takes, and from watchdog.yml
    assert doc["jobs"]["watchdog"]["steps"][-1]["run"].endswith("chain.py watch") or "chain.py watch" in json.dumps(doc["jobs"]["watchdog"])
    wd = yaml.safe_load((WF / "watchdog.yml").read_text(encoding="utf-8"))
    wd["on"] = wd.pop(True, wd.get("on"))
    assert set(wd["on"]) == {"workflow_run", "repository_dispatch", "workflow_dispatch"} and "chain.py watch" in json.dumps(wd["jobs"])
    keep = yaml.safe_load((WF / "keepalive.yml").read_text(encoding="utf-8"))
    keep["on"] = keep.pop(True, keep.get("on"))
    assert keep["on"]["schedule"] == [{"cron": "*/5 * * * *"}]
