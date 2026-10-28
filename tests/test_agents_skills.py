"""The agent skills: Claude Code (plugin/skills/, loaded with the Knos plugin), OpenClaw (integrations/skills/openclaw/) and the site's
/.well-known/skills/ copy. Each says the same three things: run knos verify before a pull request,
never open one where the AI policy bans it, disclose AI use."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CLAUDE = ROOT / "plugin" / "skills" / "knos-verify" / "SKILL.md"      # the Claude Code plugin (plugin/) loads its skills/
OPENCLAW = ROOT / "integrations" / "skills" / "openclaw" / "knos-verify" / "SKILL.md"


def _front(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, f"{path} has no front matter"
    return yaml.safe_load(m.group(1)), m.group(2)


@pytest.mark.parametrize("path", [CLAUDE, OPENCLAW])
def test_every_skill_says_verify_obey_the_policy_and_disclose(path):
    fm, body = _front(path)
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", fm["name"]) and len(fm["name"]) <= 64          # Hermes skill_linter, Agent Skills
    assert 20 <= len(fm["description"]) <= 1024
    low = " ".join(body.lower().split())
    assert "knos verify" in low and "banned" in low and "ai-use line" in low.replace("ai use line", "ai-use line")
    assert "do not open the pull request" in low or "never open a pull request" in low
    assert "never edit" in low or "never weaken" in low


def test_the_claude_code_skill_allows_only_the_commands_it_needs():
    fm, _ = _front(CLAUDE)
    assert fm["name"] == CLAUDE.parent.name and fm["allowed-tools"].startswith("Bash(knos verify:*)")


def test_the_openclaw_skill_carries_its_metadata_as_one_line_of_json():
    text = OPENCLAW.read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("metadata:"))
    meta = json.loads(line.split(":", 1)[1])
    assert meta["openclaw"]["requires"]["bins"] == ["knos", "git"] and set(meta["openclaw"]["os"]) <= {"darwin", "linux", "win32"}
