"""Ceiling 3, local-only: a claim made on one machine (HOME A, Claude Code's hook) refuses an edit on another machine
(HOME B, a different vendor's hook), with no server anywhere, on a local validator running the devnet-deployed SAS.
And a simulated cloud sandbox (a fresh shallow clone, the member key only in an environment variable) is refused
the same way."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


from _devchain import URL, devchain, funded
from knos.team import config, service

FAST = {"KNOS_NO_MIRROR": "1", "KNOS_TEAM_READ_S": "20", "KNOS_TEAM_VERDICT_S": "30"}


def _home(base: Path, name: str) -> dict:
    h = base / name
    (h / ".knos").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("KNOS_")}
    env.update({"HOME": str(h), "USERPROFILE": str(h), "KNOS_HOME": str(h / ".knos"),
                "CLAUDE_CONFIG_DIR": str(h / ".claude"), "CODEX_HOME": str(h / ".codex"),
                "XDG_CONFIG_HOME": str(h / ".config"), "KNOS_SOLANA_RPC": URL, **FAST})
    return env


def _use(monkeypatch, env: dict) -> None:
    for k in ("HOME", "USERPROFILE", "KNOS_HOME", "KNOS_SOLANA_RPC", "KNOS_MEMBER_KEY"):
        if k in env:
            monkeypatch.setenv(k, env[k])
        else:
            monkeypatch.delenv(k, raising=False)


def _hook(client: str, env: dict, repo: Path, rel: str, session: str) -> subprocess.CompletedProcess:
    target = str(repo / rel)
    if client == "claude":
        payload = {"tool_name": "Edit", "tool_input": {"file_path": target}, "session_id": session, "cwd": str(repo)}
    elif client == "codex":
        payload = {"tool_name": "apply_patch", "session_id": session, "cwd": str(repo),
                   "tool_input": {"command": f"*** Begin Patch\n*** Update File: {rel}\n*** End Patch"}}
    elif client == "opencode":
        payload = {"session_id": session, "args": {"filePath": target}, "cwd": str(repo)}
    else:  # cursor
        payload = {"tool_name": "edit_file", "file_path": target, "conversation_id": session, "cwd": str(repo)}
    wrap = ("import faulthandler,sys;faulthandler.dump_traceback_later(170, exit=True);"
            "from knos.guard_hook import main;sys.exit(main(['--client', %r]))" % client)
    return subprocess.run([sys.executable, "-c", wrap], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, cwd=str(repo), timeout=120)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@devchain
def test_a_claim_on_one_machine_refuses_another_vendor_on_another_machine(tmp_path, monkeypatch):
    origin = tmp_path / "origin"
    (origin / "src" / "billing").mkdir(parents=True)
    (origin / "src" / "billing" / "tax.py").write_text("RATE = 0.2\n", encoding="utf-8")
    _git(origin, "init", "-q")
    _git(origin, "-c", "user.email=a@example.com", "-c", "user.name=A", "add", "-A")
    _git(origin, "-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-q", "-m", "tax")

    # machine A: alice creates the team (her owner key is a funded throwaway) and commits .knos/team.json
    a_env = _home(tmp_path, "alice")
    _use(monkeypatch, a_env)
    owner = funded(3)
    tf, _ = service.create(origin, "localnet", "alice", owner, URL)
    _git(origin, "-c", "user.email=a@example.com", "-c", "user.name=A", "add", ".knos/team.json")
    _git(origin, "-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-q", "-m", "team")

    # machine B: bob clones, gets his join code, alice adds him
    bob_repo = tmp_path / "bob-clone"
    _git(tmp_path, "clone", "-q", str(origin), str(bob_repo))
    b_env = _home(tmp_path, "bob")
    _use(monkeypatch, b_env)
    from knos.team.cli import join_hint
    said = join_hint(bob_repo)[0]  # what bob's `knos init` prints
    assert "send this join code to the team owner: knos-join:" in said and "fingerprint:" in said
    bob_key = config.member_key(create=True)
    code = said.split("owner: ", 1)[1].split(" ", 1)[0]
    assert service.parse_join_code(code)[0] == bob_key.pubkey()
    _use(monkeypatch, a_env)
    service.add(config.load(origin), owner, code)
    _use(monkeypatch, b_env)
    assert "joined team" in join_hint(bob_repo)[0]
    _use(monkeypatch, a_env)

    # alice's Claude Code edits the file: the hook claims it on chain and allows the edit
    a = _hook("claude", a_env, origin, "src/billing/tax.py", "alice-session")
    assert a.returncode == 0, a.stdout + a.stderr

    # bob's Cursor, on the other machine, is refused, naming alice and her agent
    b = _hook("cursor", b_env, bob_repo, "src/billing/tax.py", "bob-session")
    assert b.returncode == 2, b.stdout + b.stderr
    said = json.loads(b.stdout)["user_message"]
    assert "claimed by alice/claude-code" in said and "(Knos)" in said

    # every other vendor's hook on bob's machine is refused the same way
    for client, sess in (("codex", "bob-codex"), ("opencode", "bob-opencode")):
        got = _hook(client, b_env, bob_repo, "src/billing/tax.py", sess)
        assert got.returncode == 2, (client, got.stdout + got.stderr)

    # a file nobody claimed is fine for bob, and alice keeps editing hers: the holder is never refused
    assert _hook("cursor", b_env, bob_repo, "src/billing/new.py", "bob-session").returncode == 0
    assert _hook("claude", a_env, origin, "src/billing/tax.py", "alice-session").returncode == 0

    # a raw shell write on bob's machine is not seen by any edit hook; git's pre-commit stops it at commit time
    (bob_repo / "src" / "billing" / "tax.py").write_text("RATE = 0.25\n", encoding="utf-8")
    _git(bob_repo, "add", "src/billing/tax.py")
    c = subprocess.run([sys.executable, "-m", "knos", "hook", "commit", "--stage", "commit"], cwd=str(bob_repo),
                       env=b_env, capture_output=True, text=True, timeout=120)
    assert c.returncode == 1, c.stdout + c.stderr
    assert "claimed by alice/claude-code" in c.stderr

    # a simulated cloud sandbox: shallow clone, fresh home, the member key only in the environment
    _use(monkeypatch, a_env)
    added, key_file = service.add_cloud(config.load(origin), owner, "ci-sandbox")
    sandbox_repo = tmp_path / "sandbox"
    _git(tmp_path, "clone", "-q", "--depth", "1", f"file://{origin.as_posix()}", str(sandbox_repo))
    s_env = _home(tmp_path, "sandbox-home")
    s_env["KNOS_MEMBER_KEY"] = key_file.read_text(encoding="utf-8")
    s = _hook("claude", s_env, sandbox_repo, "src/billing/tax.py", "cloud-session")
    assert s.returncode == 2, s.stdout + s.stderr
    assert "claimed by alice" in json.loads(s.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


@devchain
def test_an_unreachable_chain_never_blocks_work(tmp_path, monkeypatch, repo):
    env = _home(tmp_path, "solo")
    _use(monkeypatch, env)
    owner = funded(3)
    service.create(repo, "localnet", "solo", owner, URL)
    env["KNOS_SOLANA_RPC"] = "http://127.0.0.1:9"  # nothing listens there
    env["KNOS_TEAM_READ_S"] = "1"
    got = _hook("claude", env, repo, "src/auth.py", "s")
    assert got.returncode == 0
    assert "local-only mode" in json.loads(got.stdout)["systemMessage"]
