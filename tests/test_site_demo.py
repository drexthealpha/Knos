"""The round a visitor drives on the first screen (web/demo.js) and the recorded data it replays (web/demo_data.json).

web/demo_data.json is what scripts/demo_data.py writes, and everything in it that is a transaction signature, an
address or a number is in the documents it names as its sources: the demo shows nothing the repository does not
record. tests/web/demo.mjs then drives the six steps in headless Chromium with the keyboard alone. No node, no
`playwright` package or no browser: that part is skipped, with the reason.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds
SHOTS = os.environ.get("KNOS_DEMO_SHOTS", "")      # a folder for screenshots, when someone wants to look
BASE58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,90}")


def _script():
    spec = importlib.util.spec_from_file_location("demo_data", ROOT / "scripts" / "demo_data.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _leaves(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, value


def test_the_data_file_is_what_the_script_writes():
    assert (ROOT / "web" / "demo_data.json").read_text(encoding="utf-8") == _script().build(), "run python scripts/demo_data.py"


def test_every_signature_and_number_of_the_demo_is_in_the_repositorys_records():
    doc = json.loads((ROOT / "web" / "demo_data.json").read_text(encoding="utf-8"))
    assert doc["sources"] == list(_script().SOURCES)
    recorded = "\n".join((ROOT / s).read_text(encoding="utf-8") for s in doc["sources"])
    held = 0
    for path, value in _leaves({k: v for k, v in doc.items() if k not in ("_about", "sources")}):
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            # a count is written with or without its comma; a share as the json holds it
            assert re.search(rf"(?<![\d.,]){re.escape(str(value))}(?![\d]|[.,]\d)|(?<![\d.,]){re.escape(f'{value:,}')}(?![\d]|[.,]\d)", recorded), path
            held += 1
            continue
        for sig in BASE58.findall(value):
            assert re.search(rf"(?<![1-9A-HJ-NP-Za-km-z]){sig}(?![1-9A-HJ-NP-Za-km-z])", recorded), path
            held += 1
        for number in re.findall(r"\d[\d,]*(?:\.\d+)?%?", value) if not BASE58.fullmatch(value) else []:
            assert re.search(rf"(?<![\d.]){re.escape(number)}(?!\d)", recorded), (path, number)
            held += 1
        assert " ".join(value.split()) in " ".join(recorded.split()), path        # and the words themselves are the documents'
    assert held >= 25
    assert doc["count"]["seller"] - doc["count"]["buyer"] == doc["count"]["apart"]
    assert len({doc["fund"]["tx"], doc["paid"]["tx"], doc["replay"]["tx"], *doc["count"]["buyer_tx"], *doc["count"]["seller_tx"]}) >= 5
    # the refusal shown is the single-use rule's own, by the number the program's source gives it
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert doc["replay"]["error"] == doc["replay"]["single_use_error"] == int(re.search(r"pub const E_REPLAY: u32 = (\d+);", lib)[1])
    assert doc["replay"]["means"] == doc["replay"]["single_use"] == "a token works once"
    if doc["ids"] == "staging":
        # the round is one order: funded, paid (the rehearsal's first table), and its fund token refused the second time (the second)
        table = recorded[recorded.index("**1. The double payment"):recorded.index("**2. The accepted token")]
        assert all(doc[k]["tx"] in table for k in ("fund", "paid")) and doc["fund"]["order"] in table
        row = next(line for line in recorded.splitlines() if line.startswith("| FundOrderBalance |"))
        assert doc["fund"]["tx"] in row.split("|")[2] and doc["replay"]["tx"] in row.split("|")[3] and row.rstrip(" |").endswith(": 91")
    else:
        # a round at the public program ids: each transaction is in the section scripts/exercise_public.py wrote, and is the manifest's evidence
        section = recorded[recorded.index("## The round on the public program ids"):recorded.index("## The 0.3.14 rehearsal on devnet")]
        assert all(doc[k]["tx"] in section for k in ("fund", "paid", "replay"))
        by = {c["id"]: c for c in json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]}
        assert by["work_orders"]["evidence"]["exercised"]["signature"] == doc["fund"]["tx"] and by["order_pay"]["evidence"]["exercised"]["signature"] == doc["paid"]["tx"]


def test_the_script_stops_when_a_document_no_longer_records_a_part(monkeypatch):
    mod = _script()
    real = mod._read
    monkeypatch.setattr(mod, "_read", lambda p: real(p).replace("The merged pull request's pay token is relayed", "x") if p.endswith("CAPABILITIES.md") else real(p))
    with pytest.raises(SystemExit, match="no longer record the payment"):
        mod.build()


def test_the_round_in_a_browser_by_keyboard_alone(tmp_path: Path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    site = tmp_path / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(site), "c" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    assert (site / "demo.js").is_file() and (site / "demo_data.json").read_bytes() == (ROOT / "web" / "demo_data.json").read_bytes()
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "demo.mjs"), str(site), *([SHOTS] if SHOTS else [])], env=env, capture_output=True, text=True,
                         encoding="utf-8", timeout=300)
    if run.returncode == 0 and run.stdout.startswith("SKIP"):
        pytest.skip(run.stdout.strip()[5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "the demo holds" in run.stdout
