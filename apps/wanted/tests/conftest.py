import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """No network and no real key: the open sources are not asked (no RENDER, no KNOS_OPEN_SIGNALS) unless a test fakes
    them. Private folders go to tmp."""
    for k in ("RENDER", "KNOS_OPEN_SIGNALS", "KNOS_WANTED_LLM_BASE_URL", "KNOS_WANTED_LLM_API_KEY", "KNOS_WANTED_LLM_MODEL",
              "KNOS_WANTED_DEVNET_KEYPAIR", "KNOS_WANTED_MINT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("KNOS_WANTED_SEED", "0")          # no seed crosses behind a test's back (a test of the seeds turns them on)
    monkeypatch.setenv("KNOS_VISITS_OFF", "1")           # the saved visit ledger is not fetched from gh-pages in a test
    monkeypatch.setenv("KNOS_WANTED_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("KNOS_WANTED_RECORD", str(tmp_path / "record"))
    from knos_wanted import open_signals
    open_signals._answers.clear()                        # one test's answers are not carried into the next
