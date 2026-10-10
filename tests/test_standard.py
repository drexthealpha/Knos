"""docs/STANDARD.md says what the code holds: the supplier's menu is knos.terms_templates.MENU, the path codes are
the judge's, the schemas on the page are JSON, and the one tier no program holds says so."""
from __future__ import annotations

import json
import re
from pathlib import Path

from knos import judge, terms_templates

PAGE = (Path(__file__).resolve().parents[1] / "docs" / "STANDARD.md").read_text(encoding="utf-8")


def test_every_schema_on_the_page_is_json():
    blocks = re.findall(r"```json\n(.*?)```", PAGE, re.S)
    assert len(blocks) == 3
    signals, cause, log = (json.loads(b) for b in blocks)
    assert {s["class"] for s in signals["signals"]["list"]} == {"gate", "warranty", "advisory"}
    assert cause["cause"]["kind"] in ("reject", "revert")
    assert log["step"] in ("warning", "flag", "quarantine", "revoke", "lifted")


def test_the_menu_on_the_page_is_the_menu_in_the_code():
    rows = {m.group(1).lower(): m for m in re.finditer(r"^\| (Standard|Assured|Bonded) \| `([^`]+)` \| ([^|]+) \| ([^|]+) \|$", PAGE, re.M)}
    assert list(rows) == list(terms_templates.MENU)
    for name, row in rows.items():
        got = terms_templates.tier(name)
        assert row.group(2) == got["comment"], name
        assert ("Off chain only." in row.group(4)) == (not got["on_chain"]), name
    assured = terms_templates.tier("assured")
    assert assured["options"] == {"holdback": 10, "warranty_days": 14} and "10% waits 14 days" in rows["assured"].group(3)
    assert terms_templates.tier("standard")["options"] == {"holdback": 0, "warranty_days": 0}
    # the menu is not one of the published templates: examples/terms and the install page are untouched
    assert not set(terms_templates.MENU) & set(terms_templates.ALL)


def test_the_path_codes_are_the_judges():
    line = next(x for x in PAGE.splitlines() if x.startswith("| `path_refused` |"))
    assert sorted(line.split("codes today: ")[1].replace("`", "").rstrip(". |").split(", ")) == sorted(judge.REFUSALS)


def test_what_is_only_written_down_says_so():
    assert "Schema only. Nothing writes it yet." in PAGE and "Not built." in PAGE and "PROPOSAL-2.3.md" in PAGE
