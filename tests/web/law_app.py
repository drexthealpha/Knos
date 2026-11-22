"""The Knos app, run locally for the browser tests of the law checks (tests/web/law_checks.mjs, tests/web/section12.mjs).

python tests/web/law_app.py          prints "port <n>" once it serves, then serves until its stdin closes

The same set-up as apps/wanted/tests/test_tool_run.py's `app` fixture: the app's own handler on 127.0.0.1,
no chain count from the network, a state folder of its own (KNOS_WANTED_STATE, a new temporary folder).
The tool's program is the released one (near/agents/job/data/limit/released_solution.py) when it exists; until then the
stand-in written to the locked test's interface, apps/wanted/tests/limit_standin.py, which is kept only under tests."""
import hashlib
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
os.environ.setdefault("KNOS_WANTED_STATE", tempfile.mkdtemp(prefix="knos-law-state-"))
os.environ.setdefault("SIBYL_MEMORY_TELEMETRY", "0")
for p in (REPO / "apps" / "wanted", REPO / "src"):
    sys.path.insert(0, str(p))

from knos_wanted import server, tool_run, usage  # noqa: E402


def main() -> int:
    # the released program once it is the one released for the claim's locked test (test_limit3.py), else the stand-in
    released = tool_run.ready() and str(tool_run.released().get("test") or "").endswith("/" + tool_run.CONF["claim_test"])
    if not released:
        standin = REPO / "apps" / "wanted" / "tests" / "limit_standin.py"
        rel = {**tool_run.released(), "sha256": hashlib.sha256(standin.read_bytes()).hexdigest()}
        tool_run.program_path = lambda: standin
        tool_run.released = lambda: rel          # ready() compares the program with released.json
    usage.chain_count = lambda url=None: (_ for _ in ()).throw(OSError("no network in tests"))
    state = server.State()
    state.allow = lambda *a, **k: True          # the tests press far more often than a person: no rate limit here
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"port {httpd.server_address[1]}", flush=True)
    print(f"program {'released' if released else 'stand-in (no released_solution.py yet)'}", flush=True)
    try:
        sys.stdin.read()                         # the test closes stdin (or ends) to stop the app
    except KeyboardInterrupt:
        pass
    httpd.shutdown()
    httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
