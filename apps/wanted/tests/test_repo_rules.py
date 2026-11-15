"""Rules the repository keeps: Qloo data never committed, MOCK labelled, the framing stated, the Qloo part explained,
the key never in code, Qloo reached only from the server (the REST client and the harness)."""
import re
from pathlib import Path

from knos_wanted import mock_mcp
from knos_wanted.qloo_mcp import MOCK_LABEL, InProcess, Qloo

ROOT = Path(__file__).resolve().parents[1]


def test_cache_and_probe_are_git_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert ".cache/" in ignored and "probe.json" in ignored and ".env" in ignored and "node_modules/" in ignored


def test_readme_states_framing_and_qloo_part():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Directional demand evidence, not a sales forecast." in text
    assert "aggregate taste, not a prediction about one person" in text
    assert "## What is Qloo-powered" in text
    assert "MOCK (synthetic, not real Qloo data)" in text
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_every_mock_answer_is_labelled():
    q = Qloo(InProcess(), mode="mock")
    assert q.label == MOCK_LABEL
    for name in mock_mcp.TOOLS:
        if name != "qloo_capabilities":
            assert mock_mcp.call(name, {})["_mock"] == MOCK_LABEL


def test_mock_names_are_marked_synthetic():
    body = mock_mcp.call("qloo_recommend", {"target_type": "brand", "signals": ["mock-brand-x-a"]})
    assert all("(synthetic)" in e["name"] for e in body["results"])


def test_no_recorded_qloo_bodies_in_repo():
    for p in ROOT.rglob("*.json"):
        if ".cache" in p.parts or ".venv" in p.parts or "node_modules" in p.parts:
            continue
        if p.relative_to(ROOT).as_posix() == "knos_wanted/data/cbsa_msa_2023.json":     # Census metro boundaries (metros.py), no Qloo data
            continue
        if p.relative_to(ROOT).as_posix() == "knos_wanted/data/qloo_ablation.json":    # the published table's copy: labels, metro names, numbers
            continue
        raise AssertionError(f"unexpected JSON file in the repository: {p.relative_to(ROOT)}")


def test_qloo_is_reached_only_from_the_server_client_and_no_key_in_code():
    # Qloo is reached server side only: the REST client qloo_rest.py (Qloo's API, key from the environment)
    # and the official harness bridge. No other module names the endpoint or the key header, no code assigns a key,
    # and the browser never talks to Qloo.
    rest = ROOT / "knos_wanted" / "qloo_rest.py"
    others = [p for p in (ROOT / "knos_wanted").rglob("*.py") if p != rest]
    code = "\n".join(p.read_text(encoding="utf-8") for p in others) + (ROOT / "bridge" / "qloo_bridge.mjs").read_text(encoding="utf-8")
    assert "api.qloo.com" not in code.lower() and "x-api-key" not in code.lower()
    every = code + rest.read_text(encoding="utf-8")
    assert not re.search(r"QLOO_API_KEY\s*=\s*['\"]", every)          # read from the environment, never written
    assert not re.search(r"hack_[0-9a-f]{20,}", every)                  # no hackathon key literal anywhere
    assert "os.environ" in rest.read_text(encoding="utf-8") and "QLOO_API_KEY" in rest.read_text(encoding="utf-8")
    js = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "knos_wanted" / "static").glob("*.js"))
    assert "qloo.com" not in js.lower() and "QLOO" not in js          # the browser never talks to Qloo