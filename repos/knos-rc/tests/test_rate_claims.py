"""scripts/rate_claims.py: a latency or throughput figure without its sample size, its program ids and its date fails.
Each failure is planted; the documents the release checks pass."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("rate_claims", ROOT / "scripts" / "rate_claims.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rate_claims"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _script()

WHOLE = "Merge to paid on devnet, public program ids, 2026-10-07: p50 25 s, p95 65 s over 47 payments."


def test_a_figure_with_its_sample_ids_and_date_passes():
    assert rc.check(WHOLE) == []
    assert rc.check("Measured on 7 October 2026 on one machine, no network: 40 decisions, p50 1.6 ms, p95 2.3 ms.") == []


def test_each_missing_part_is_named():
    assert rc.check("Merge to paid on devnet, 2026-10-07: p50 25 s, p95 65 s over 47 payments.")[0]["missing"] == ["program ids"]
    assert rc.check("Merge to paid on devnet, public program ids: p50 25 s, p95 65 s over 47 payments.")[0]["missing"] == ["date"]
    assert rc.check("Merge to paid on devnet, public program ids, 2026-10-07: p50 25 s, p95 65 s.")[0]["missing"] == ["sample size"]
    assert rc.check("The worker carries 0.46 confirmed a second.")[0]["missing"] == ["sample size", "program ids", "date"]


def test_a_staging_run_must_say_staging_and_a_heading_carries_it_to_its_table():
    doc = ("### devnet, STAGING program ids (not the public ones), 2026-10-04: 200 orders\n\n"
           "| Stage | Transactions | Failures | p50 s | p95 |\n| --- | --- | --- | --- | --- |\n| fund | 200 | 0 of 200 | 38.35 | 97.18 |\n")
    assert rc.check(doc) == []
    assert rc.check(doc.replace("STAGING program ids (not the public ones), ", ""))[0]["missing"] == ["program ids"]


def test_the_lead_of_a_generated_block_covers_the_paragraphs_under_it_and_ends_with_it():
    lead = "<!-- x:time -->\nMeasured on 2026-10-07 on one machine, no network, 40 decisions a row.\n\n"
    body = "One process that stays up: p50 1.6 ms, p95 2.2 ms, slowest 2.3 ms.\n"
    assert rc.check(lead + body + "<!-- /x:time -->\n") == []
    assert rc.check(lead + "<!-- /x:time -->\n\n" + body)[0]["missing"] == ["sample size", "program ids", "date"]


def test_derived_figures_and_targets_are_not_measurements_and_words_that_only_look_like_rates_are_not_read():
    assert rc.check("Derived: 8.46 orders a second per fee payer.") == []
    assert rc.check("## 3. What that allows (derived)\n\nAt most 164.6 payments a second through the fee account.\n") == []
    assert rc.check("The target is 100 ms at p95.") == []
    assert rc.check("Every 10th pay token was sent a second time at once.") == []
    assert rc.check("<!-- p50 25 s -->\n`p50 25 s`\n") == []


def test_the_documents_the_release_checks_have_every_figure_with_its_sample_ids_and_date(capsys):
    assert rc.main([]) == 0, capsys.readouterr().out
    for doc, figures in rc.PENDING.items():          # a pending figure that is fixed leaves the list
        found = {b["figure"] for b in rc.check((ROOT / doc).read_text(encoding="utf-8"))}
        assert set(figures) <= found, f"{doc}: fixed, remove from PENDING: {set(figures) - found}"
