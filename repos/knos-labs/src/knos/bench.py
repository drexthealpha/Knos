"""`knos bench`: measure knos on this machine against the obvious ways of doing without it. Free and re-runnable.

  collide   3 scripted agents x N rounds reach for the same file at the same instant, through the real claim and
            edit-guard code (guard.run, the function the hooks call). Arms: none (no coordination), advisory (a
            shared lease file checked then written, as advisory-lease tools do; a simulation of that approach), and
            knos. Counted: rounds in which more than one agent's edit reached the file.
  friction  steps from nothing to three hosts sharing memory and claims: knos's is the one command it times here;
            each alternative's is counted from its own README (URL and date in FRICTION below).
  history   20 questions whose answers exist only in past agent sessions (Claude Code and Codex transcripts) and
            commits, written as fixtures and read by knos's real readers. Baseline: what a fresh agent has without
            shared memory, the repo's CLAUDE.md. Counted: questions whose top 3 answers contain the answer and cite it.
  speed     the guard's decision and a search on a 5,000-file repo; p50 and p95 in milliseconds.
  budget    200 attempted agent payments of random size against a cap, through the gate that runs before any
            signature. Counted: spend beyond the cap.
  init      seconds for `knos init` to wire four hosts in a fresh home, self-test included.

Everything runs in a temporary KNOS_HOME and HOME; your repos, agents' settings and store are not touched.
"""

from __future__ import annotations

import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Steps from nothing to three hosts (e.g. Claude Code, Cursor, Codex) sharing one memory and one claim list, counted
# from each project's own README. A "step" is one command to run or one config block to paste per host.
FRICTION = [
    # (name, steps, what the steps are, url, read on)
    ("knos", 1, "`knos init` (memory + claims + edit guard, every host it finds)", "this repo", "measured"),
    ("MCP Agent Mail", 5, "installer, start the server (`am`), register_agent in each of 3 hosts; claims only "
     "(advisory leases), no memory of past sessions", "https://github.com/Dicklesworthstone/mcp_agent_mail",
     "2026-09-29"),
    ("Sibyl Memory", 3, "`pip install sibyl-memory-cli[mcp]`, `sibyl init` (browser sign-in), `sibyl setup`; "
     "memory only, no claims", "https://docs.sibyllabs.org/memory/install", "2026-09-29"),
    ("Sibyl Memory + MCP Agent Mail", 8, "both of the above, to get memory and claims", "as above", "2026-09-29"),
]

RACER = r"""
import json, os, random, sys, time
arm, repo, target, start, rounds, name = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
from knos import guard
from knos.claims import Claims
from knos.identity import Agent
me = Agent(host=name, session="s-" + name)
out = []
for r in range(rounds):
    t0 = start + r * 0.3
    while time.time() < t0:
        pass
    f = os.path.join(repo, "src", f"shared_{r}.py")
    believes = False
    if arm == "none":
        believes = True
    elif arm == "advisory":
        lease = os.path.join(repo, ".leases", f"{r}.json")
        if not os.path.exists(lease):
            time.sleep(random.uniform(0, 0.004))   # the gap between looking and writing
            with open(lease, "w") as fh:
                fh.write(name)
            believes = True
    else:
        with Claims(repo) as c:
            believes, _, _ = c.take(me, f"round {r}", [f"src/shared_{r}.py"])
    wrote = False
    if believes:
        if arm == "knos":
            payload = json.dumps({"session_id": "s-" + name, "cwd": repo,
                                  "tool_name": "Edit", "tool_input": {"file_path": f}})
            _, code = guard.run("claude", payload)
            allowed = code == 0
        else:
            allowed = True
        if allowed:
            with open(f, "a") as fh:
                fh.write(name + "\n")
            wrote = True
    out.append(wrote)
print(json.dumps(out))
"""

# (decision as it was said, where it was said, question asked later in other words)
HISTORY = [
    ("We dropped Redis because the cache was never the bottleneck; Postgres handles it.", "claude", "why is there no redis cache"),
    ("Auth tokens expire after 15 minutes and refresh silently via the refresh cookie.", "claude", "how long do login tokens last"),
    ("The payments webhook retries 5 times with exponential backoff, then pages on-call.", "codex", "what happens when the payment webhook fails"),
    ("We pinned numpy below 2.0 because the image pipeline breaks on the new dtype rules.", "commit", "why is numpy held back"),
    ("Feature flags live in flags.yaml, not the database, so a deploy can roll them back.", "codex", "where are feature flags stored"),
    ("The mobile app talks to /v2 only; /v1 stays until the last Android 9 users upgrade.", "claude", "can we delete the v1 api"),
    ("Rate limit is 100 requests per minute per API key, enforced at the gateway.", "commit", "what is the api rate limit"),
    ("We chose SQLite for the CLI's local cache because users must not install a server.", "codex", "why sqlite for the local cache"),
    ("Timestamps are stored as UTC and converted only in the UI layer.", "claude", "what timezone are dates saved in"),
    ("The nightly export runs at 02:00 UTC so it finishes before the EU morning.", "commit", "when does the nightly export run"),
    ("Never log request bodies: they can contain card numbers; log the request id instead.", "codex", "can I log the request body"),
    ("The search index is rebuilt from scratch on schema change; there is no migration path.", "claude", "how do we migrate the search index"),
    ("Images over 10 MB are rejected at upload rather than resized, to keep workers small.", "commit", "what is the image upload size limit"),
    ("We use UUIDv7 primary keys so rows sort by creation time.", "codex", "why are ids uuid v7"),
    ("The staging database is wiped every Sunday; do not keep test fixtures there.", "claude", "is staging data persistent"),
    ("Emails go through Postmark; SES was dropped after the bounce-handling outage.", "commit", "which email provider do we use"),
    ("Background jobs must be idempotent because the queue delivers at least once.", "codex", "do jobs need to be idempotent"),
    ("CSS is Tailwind with a design-token layer; no new component library.", "claude", "can I add a component library"),
    ("The admin panel is internal only and sits behind the VPN, never public.", "commit", "is the admin panel exposed publicly"),
    ("Tests hit a real Postgres in Docker; mocks of the database are not accepted in review.", "codex", "can I mock the database in tests"),
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def _repo(root: Path, files: int = 80) -> Path:
    repo = root / "bench-repo"
    (repo / "src").mkdir(parents=True)
    (repo / ".leases").mkdir()
    per = max(files // 50, 1)
    for d in range(50):
        sub = repo / "src" / f"pkg{d:02d}"
        sub.mkdir()
        for i in range(per):
            (sub / f"mod_{i}.py").write_text(f"def handler_{d}_{i}():\n    return {i}\n", encoding="utf-8")
    for r in range(400):
        (repo / "src" / f"shared_{r}.py").write_text("", encoding="utf-8")
    (repo / "CLAUDE.md").write_text("# Working here\n\nRun the tests before you push.\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "bench@example.invalid")
    _git(repo, "config", "user.name", "bench")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "start")
    return repo


def collide(repo: Path, work: Path, rounds: int, agents: int = 3) -> dict:
    racer = work / "racer.py"
    racer.write_text(RACER, encoding="utf-8")
    src = str(Path(__file__).resolve().parents[1])
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([src] + [p for p in [os.environ.get("PYTHONPATH")] if p])}
    result: dict = {"rounds": rounds, "agents": agents}
    for arm in ("none", "advisory", "knos"):
        start = time.time() + 2.0 + agents * 0.3
        ps = [subprocess.Popen([sys.executable, str(racer), arm, str(repo), "", str(start), str(rounds), f"agent{i}"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
              for i in range(agents)]
        outs = []
        for p in ps:
            o, e = p.communicate(timeout=120 + rounds)
            if p.returncode != 0:
                raise RuntimeError(f"racer failed: {e.strip()[-400:]}")
            outs.append(json.loads(o.strip().splitlines()[-1]))
        writers = [sum(o[r] for o in outs) for r in range(rounds)]
        result[arm] = {"conflicts": sum(1 for w in writers if w > 1), "no_writer": sum(1 for w in writers if w == 0)}
        _git(repo, "checkout", "-q", "--", "src")
        shutil.rmtree(repo / ".leases", ignore_errors=True)
        (repo / ".leases").mkdir()
    return result


def _claude_log(home: Path, repo: Path, texts: list[str]) -> None:
    enc = "".join(c if c.isalnum() else "-" for c in str(repo.resolve()))
    d = home / ".claude" / "projects" / enc
    d.mkdir(parents=True, exist_ok=True)
    with (d / "bench-session.jsonl").open("w", encoding="utf-8") as fh:
        for i, t in enumerate(texts):
            fh.write(json.dumps({"type": "assistant", "sessionId": "claude-bench-01", "cwd": str(repo.resolve()),
                                 "timestamp": f"2026-09-{10 + i % 9:02d}T10:00:00Z",
                                 "message": {"role": "assistant", "content": t}}) + "\n")


def _codex_log(home: Path, repo: Path, texts: list[str]) -> None:
    d = home / ".codex" / "sessions" / "2026" / "09" / "20"
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"timestamp": "2026-09-20T10:00:00Z", "type": "session_meta",
             "payload": {"id": "codex-bench-01", "cwd": str(repo.resolve())}}]
    rows += [{"timestamp": "2026-09-20T10:01:00Z", "type": "response_item",
              "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": t}]}}
             for t in texts]
    (d / "rollout-2026-09-20T10-00-00-bench.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                                             encoding="utf-8")


def history(repo: Path, home: Path) -> dict:
    from . import answer, refresh
    from .memory import Memory

    by = {"claude": [], "codex": [], "commit": []}
    for said, where, _q in HISTORY:
        by[where].append(said)
    _claude_log(home, repo, by["claude"])
    _codex_log(home, repo, by["codex"])
    for msg in by["commit"]:
        (repo / "CHANGES.txt").open("a", encoding="utf-8").write(msg + "\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", msg)
    refresh.ensure(repo, force=True, index_code=False)
    source = {"claude": "Claude Code session", "codex": "Codex session", "commit": ""}
    hits = 0
    with Memory(repo) as mem:
        for said, where, q in HISTORY:
            found = answer.ask(repo, mem, q, limit=3)
            hits += any(said[:40] in p.text and source[where] in p.where for p in found)
    rules = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    base = sum(1 for said, _, _ in HISTORY if said[:40] in rules)
    return {"questions": len(HISTORY), "knos": hits, "baseline": base}


def speed(repo: Path, n: int) -> dict:
    from . import answer, guard, refresh
    from .claims import Claims
    from .identity import Agent
    from .memory import Memory

    refresh.ensure(repo, force=True, index_code=True)
    b = Agent("cursor", "sess-b")
    with Claims(repo) as c:
        for i in range(20):
            c.take(Agent(f"agent{i}", f"s{i}"), f"work {i}", [f"src/pkg{i:02d}/mod_0.py"])
        c.take(Agent("folder", "sf"), "a whole package", ["src/pkg40/**"])
    g = []
    for i in range(n):
        t = time.perf_counter()
        guard.check(repo, str(repo / f"src/pkg{20 + i % 20:02d}/mod_1.py"), b)
        g.append((time.perf_counter() - t) * 1000)
    s = []
    with Memory(repo) as mem:
        for i in range(max(20, n // 4)):
            t = time.perf_counter()
            answer.ask(repo, mem, ["why did we drop redis", "handler_12_3", "auth tokens", "nightly export"][i % 4])
            s.append((time.perf_counter() - t) * 1000)
    files = sum(1 for _ in (repo / "src").rglob("*.py"))

    def pct(xs, p):
        return round(statistics.quantiles(xs, n=100)[p - 1], 1) if len(xs) > 1 else round(xs[0], 1)

    return {"files": files, "guard_p50": pct(g, 50), "guard_p95": pct(g, 95), "search_p50": pct(s, 50),
            "search_p95": pct(s, 95), "guard_n": len(g), "search_n": len(s)}


def budget_bench(attempts: int = 200, cap: float = 5.0) -> dict:
    from .pro import agentpay, budget, wallets

    addr = wallets.create("bench-agent", "solana")
    budget.set_agent("bench-agent", "solana", "devnet", cap, addr)
    rng = random.Random(7)
    signed = refused = 0
    total = 0.0
    from .pro import solana

    for _ in range(attempts):
        amount = round(rng.uniform(0.01, 0.2), 2)
        try:
            agentpay.gate("bench-agent", "solana", "devnet", solana.USDC["devnet"], amount, "http://bench")
            signed += 1
            total += amount
        except agentpay.Refused:
            refused += 1
    return {"attempts": attempts, "cap": cap, "signed": signed, "refused": refused, "spent": round(total, 2),
            "overspend": round(max(0.0, total - cap), 6)}


def init_time(home: Path) -> dict:
    from . import init as setup

    for d in (".cursor", ".codex", ".config/opencode"):
        (home / d).mkdir(parents=True, exist_ok=True)
    (home / ".claude").mkdir(exist_ok=True)
    t = time.perf_counter()
    rep = setup.install(["claude", "codex", "cursor", "opencode"])
    problems = setup.selftest()
    took = time.perf_counter() - t
    return {"seconds": round(took, 1), "hosts": len(rep.done), "problems": rep.problems + problems}


def _ratio(base: int, knos: int) -> str:
    return f"{(base + 1) / (knos + 1):.1f}x"


def render(r: dict) -> str:
    c, f, h, s, b, i = r["collide"], r["friction"], r["history"], r["speed"], r["budget"], r["init"]
    lines = [
        "# Knos bench", "",
        f"Measured by `knos bench{' --quick' if r['quick'] else ''}` on {r['when']}: {r['machine']}, Python "
        f"{r['python']}, knos {r['version']}{', commit ' + r['commit'] if r.get('commit') else ''}.",
        "Re-run it to check every number. The method for each is in `src/knos/bench.py`.", "",
        "| vector | knos | without knos | ratio / target |", "|---|---|---|---|",
        f"| **Security**: rounds where a conflicting edit reached the file ({c['agents']} agents x {c['rounds']} "
        f"rounds) | {c['knos']['conflicts']} | advisory (simulation) {c['advisory']['conflicts']}; none "
        f"{c['none']['conflicts']} | (advisory+1)/(knos+1) = {_ratio(c['advisory']['conflicts'], c['knos']['conflicts'])} |",
        f"| **Capability**: questions answered from past sessions and commits, cited ({h['questions']}) | "
        f"{h['knos']} | {h['baseline']} (CLAUDE.md only) | (knos+1)/(base+1) = "
        f"{(h['knos'] + 1) / (h['baseline'] + 1):.1f}x |",
        f"| **Friction**: steps to three hosts sharing memory and claims | 1 | 8 (Sibyl Memory + MCP Agent Mail, "
        f"from their READMEs) | 8.0x |",
        f"| **Budget**: spend past the cap ({b['attempts']} attempted payments, cap {b['cap']:g}) | "
        f"{b['overspend']:g} | | 0 by construction |",
        f"| **Speed**: guard decision p50 / p95 ({s['files']:,} files, 21 live claims) | {s['guard_p50']} / "
        f"{s['guard_p95']} ms | | p95 <= 100 ms |",
        f"| **Speed**: search p50 / p95 ({s['files']:,} files) | {s['search_p50']} / {s['search_p95']} ms | | "
        f"p95 <= 300 ms |",
        f"| **UX**: `knos init` wiring {i['hosts']} hosts, self-test included | {i['seconds']} s | | <= 30 s |",
        "", "## Friction, counted from each README", "",
        "| tool | steps | what | source | read |", "|---|---|---|---|---|",
    ]
    lines += [f"| {n} | {st} | {what} | {url} | {when} |" for n, st, what, url, when in f]
    lines += ["", "Limits, said plainly: the advisory arm simulates a check-then-write lease; the history set is 20 "
                  "synthetic decisions asked in other words, not a public benchmark; the budget row measures Knos's "
                  "cap, and the agent wallet's balance is a second, on-chain ceiling this bench does not spend real "
                  "money to show.", ""]
    return "\n".join(lines)


def run(quick: bool = False) -> dict:
    from . import version

    home = Path(tempfile.mkdtemp(prefix="knos-bench-home-"))
    work = Path(tempfile.mkdtemp(prefix="knos-bench-"))
    saved = {k: os.environ.get(k) for k in ("KNOS_HOME", "HOME", "USERPROFILE", "CODEX_HOME", "CLAUDE_CONFIG_DIR",
                                             "XDG_CONFIG_HOME", "APPDATA", "KNOS_CLAUDE_HOME", "KNOS_CODEX_HOME",
                                             "KNOS_NO_CLAUDE_CLI", "OPENCODE_CONFIG")}
    os.environ.update({"KNOS_HOME": str(home / ".knos"), "HOME": str(home), "USERPROFILE": str(home),
                       "CODEX_HOME": str(home / ".codex"), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                       "XDG_CONFIG_HOME": str(home / ".config"), "APPDATA": str(home / "AppData"),
                       # the bench's init writes only inside this temporary home, never through the real Claude CLI
                       "KNOS_NO_CLAUDE_CLI": "1"})
    os.environ.pop("OPENCODE_CONFIG", None)
    for k in ("KNOS_CLAUDE_HOME", "KNOS_CODEX_HOME"):
        os.environ.pop(k, None)
    try:
        from . import paths

        paths.shared_root.cache_clear()
        here = Path(__file__).resolve().parent
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=here, capture_output=True,
                                text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=here, capture_output=True,
                               text=True).stdout.strip()
        if commit and dirty:
            commit += " plus uncommitted changes"
        r = {"quick": quick, "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "machine": f"{platform.system()} {platform.machine()}", "python": platform.python_version(),
             "version": version(), "commit": commit, "friction": FRICTION}
        repo = _repo(work, files=1000 if quick else 5000)
        r["collide"] = collide(repo, work, rounds=40 if quick else 200)
        r["history"] = history(repo, home)
        r["speed"] = speed(repo, n=60 if quick else 300)
        from .pro import licence

        licence.status(start_trial=True)
        r["budget"] = budget_bench()
        r["init"] = init_time(home)
        return r
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        from .paths import remove_tree

        remove_tree(work)
        remove_tree(home)


def main(out_file: str | None = None, quick: bool = False, say=print) -> int:
    say("Measuring (collide, history, speed, budget, init). A few minutes on a spinning disk...")
    r = run(quick)
    text = render(r)
    say(text)
    if out_file:
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        Path(out_file).write_text(text, encoding="utf-8")
        Path(out_file).with_suffix(".json").write_text(json.dumps(r, indent=2), encoding="utf-8")
        say(f"Wrote {out_file}")
    return 0
