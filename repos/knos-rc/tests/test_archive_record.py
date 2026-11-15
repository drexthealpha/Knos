"""docs/archive_verify.json is a run of the stand-alone verifier, made again here (scripts/archive_verify.py)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("archive_verify_script", ROOT / "scripts" / "archive_verify.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_recorded_run_is_what_the_verifier_says_today_and_the_demo_shows_that_line():
    kept = json.loads((ROOT / "docs" / "archive_verify.json").read_text(encoding="utf-8"))
    assert _script().run() == {k: v for k, v in kept.items() if k != "real"}
    assert kept["lines"][-1].startswith("VERIFIED: ") and kept["lines"][-1].endswith("No network, no Knos.")
    assert any(line.startswith("note: UNSIGNED:") for line in kept["lines"])          # the samples carry no token, and it is said
    assert len(kept["says"].split()) <= 12 and (ROOT / kept["link"]).is_file()
    shown = json.loads((ROOT / "web" / "demo_data.json").read_text(encoding="utf-8"))
    assert shown["verify"] == {"says": kept["says"], "link": kept["link"]} and shown["bank_file"] is True
    assert "archive_verify.json" in (ROOT / kept["link"]).read_text(encoding="utf-8")


def test_a_real_periods_run_is_kept_as_recorded_and_says_what_its_last_line_says():
    real = json.loads((ROOT / "docs" / "archive_verify.json").read_text(encoding="utf-8"))["real"]
    last = real["lines"][-1]
    assert last.startswith("VERIFIED: ") and last.endswith("No network, no Knos.")
    counts = last.split("VERIFIED: ")[1].split(". No network")[0]                     # "N checks hold, M notes"
    assert real["says"] == f"Stand-alone verifier on a real period's archive: {counts}."
    assert len(real["archive_sha256"]) == 64 and real["source"] and real["evidence_root"] in real["lines"][0]


def test_real_takes_an_archive_runs_its_own_verifier_and_check_keeps_it(tmp_path, monkeypatch):
    mod = _script()
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from knos import archive
    blob = archive.make(ledgers={"buyer.jsonl": (ROOT / mod.LEDGER).read_bytes()}, sealed="2026-10-07")
    zipped = tmp_path / "period.zip"
    zipped.write_bytes(blob)
    out = tmp_path / "archive_verify.json"
    monkeypatch.setattr(mod, "OUT", out)
    assert mod.main(["--real", str(zipped), "--source", "a test archive"]) == 0
    got = json.loads(out.read_text(encoding="utf-8"))["real"]
    assert got["lines"][-1].startswith("VERIFIED: ") and got["source"] == "a test archive"
    assert got["evidence_root"] in got["lines"][0]
    assert mod.main(["--check"]) == 0                                 # the real part is kept: the archive is not in the tree
    assert mod.main([]) == 0 and json.loads(out.read_text(encoding="utf-8"))["real"] == got
    zipped.write_bytes(b"not an archive")
    try:
        mod.main(["--real", str(zipped), "--source", "x"])
    except (SystemExit, Exception):
        pass
    else:
        raise AssertionError("a file that is not an archive was recorded")
