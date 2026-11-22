"""Rules the repository keeps: private caches git-ignored, the framing stated, no JSON data file committed, no key
literal in code, and the demand check's sources asked only from the server."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cache_and_probe_are_git_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert ".cache/" in ignored and "probe.json" in ignored and ".env" in ignored and "node_modules/" in ignored


def test_readme_states_the_framing_and_the_rule():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Directional demand evidence, not a sales forecast." in text
    assert "OPEN when 2 of them count" in text and "no launch city" in text
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_no_json_data_files_in_repo():
    for p in ROOT.rglob("*.json"):
        if ".cache" in p.parts or ".venv" in p.parts or "node_modules" in p.parts:
            continue
        raise AssertionError(f"unexpected JSON file in the repository: {p.relative_to(ROOT)}")


def test_no_key_in_code_and_the_sources_are_asked_from_the_server_only():
    code = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "knos_wanted").rglob("*.py"))
    assert not re.search(r"(?i)api_key\s*=\s*['\"][A-Za-z0-9_-]{12,}", code)   # read from the environment, never written
    assert not re.search(r"hack_[0-9a-f]{20,}", code)                  # no hackathon key literal anywhere
    js = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "knos_wanted" / "static").rglob("*.js"))
    for host in ("wikimedia.org", "api.gdeltproject.org", "hn.algolia.com", "api.openalex.org"):
        assert host not in js, host                                    # the browser never asks the open sources itself
