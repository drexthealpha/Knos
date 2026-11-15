"""examples/upgrade_gate/adopt.py `init --link`: the gate as one pull request. The whole workflow it writes builds the
program and records that build; the link opens GitHub's page adding it, built as web/install.js builds its own. No network."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gate_adopt_link", ROOT / "examples" / "upgrade_gate" / "adopt.py")
adopt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adopt)
ME = "11111111111111111111111111111112"
FLOW = "acme/vault/.github/workflows/knos-gate.yml"


def test_init_with_a_link_writes_the_whole_workflow_and_prints_the_link_to_add_it(tmp_path):
    said: list[str] = []
    out = tmp_path / "my_gate"
    assert adopt.main(["init", "--repo-id", "7", "--workflow", FLOW, "--gate-id", ME, "--out", str(out), "--link", "acme/vault@dev"], said.append) == 0
    whole = (out / ".github" / "workflows" / "knos-gate.yml").read_text(encoding="utf-8")
    link = next(s for s in said if s.startswith("install: "))[len("install: "):]
    parts = urlsplit(link)
    assert parts.netloc == "github.com" and parts.path == "/acme/vault/new/dev"
    q = parse_qs(parts.query)
    assert q["filename"] == [".github/workflows/knos-gate.yml"] and q["value"] == [whole]
    assert said[-1].startswith("Next: cd ")
    # what the workflow does: builds on main and release tags, signs the hash of that build, has this gate record it
    assert "branches: [main]" in whole and "tags: ['v*']" in whole and "cargo build-sbf" in whole
    assert "audience=gate:$PROGRAM:$hash" in whole and f"adopt.py record --gate {ME} --token-file gate.jwt" in whole
    assert f"SOLANA_VERSION: {adopt.solana_version()}" in whole and f"ref: {adopt.tag()}" in whole
    used = re.findall(r"uses: ([\w/-]+)@([0-9a-f]{40})", whole)
    assert [a for a, _ in used] == ["actions/checkout", "actions/checkout", "actions/upload-artifact"] and whole.count("uses:") == 3
    # the workflow file the gate names is the file the link adds
    lib = (out / "src" / "lib.rs").read_text(encoding="utf-8")
    assert f'b"{FLOW}@"' in lib


def test_the_link_is_encoded_as_encode_uri_component_and_a_wrong_repository_is_refused(tmp_path):
    url = adopt.install_link("acme/vault", FLOW, "a b&c/d'(e)")
    assert url.endswith("&value=a%20b%26c%2Fd'(e)") and "/new/main?" in url
    said: list[str] = []
    assert adopt.main(["init", "--repo-id", "7", "--workflow", FLOW, "--gate-id", ME, "--out", str(tmp_path / "x"), "--link", "not a repo"], said.append) == 1
    assert said[0].startswith("refused: --link") and not (tmp_path / "x").exists()
    with pytest.raises(adopt.Refused):
        adopt.install_link("acme/vault", FLOW, "x" * 9000)


def test_the_whole_workflow_passes_actionlint(tmp_path):
    lint = os.environ.get("ACTIONLINT") or shutil.which("actionlint")
    if not lint:
        pytest.skip("actionlint is not installed")
    flows = tmp_path / ".github" / "workflows"
    flows.mkdir(parents=True)
    (flows / "knos-gate.yml").write_text(adopt.whole(FLOW, ME), encoding="utf-8")
    run = subprocess.run([lint, str(flows / "knos-gate.yml")], capture_output=True, text=True, encoding="utf-8", cwd=tmp_path, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_page_opens_with_the_three_lines_the_link_and_what_it_proves():
    page = (ROOT / "docs" / "reference" / "GATE.md").read_text(encoding="utf-8")
    head = page.split("## Three commands")[0]
    three = re.search(r"```rust\n(.*?)```", head, flags=re.S).group(1).splitlines()
    assert [line.split("(")[0].split("=")[0].strip() for line in three] == [
        "solana_program::declare_id!", "pub const KNOS_REPO_ID: u64", "pub const WORKFLOW: &[u8]"]
    assert "--link OWNER/REPO" in head and "installLink" in head and "What each record proves" in head
