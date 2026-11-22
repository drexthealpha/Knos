"""IQ L49: GET /api/tools lists through scripts/tool_manifest.py listed(), and publicly only the limit check."""
from __future__ import annotations

import re

from knos_wanted import tool_run

DOCKER = (tool_run.REPO / "apps" / "wanted" / "Dockerfile").read_text(encoding="utf-8")


def test_the_list_is_what_the_manifest_runner_lists(monkeypatch):
    tool_run._listed.clear()
    assert tool_run.manifest_ids() == ["limit-check"]          # its locked test passed in an empty folder
    assert [t["id"] for t in tool_run.tools_doc()["tools"]] == ["limit-check"]
    monkeypatch.setitem(tool_run._listed, "ids", ["limit-check", "count-distinct"])
    assert [t["id"] for t in tool_run.tools_doc()["tools"]] == ["limit-check"]   # another listed check is not public here
    monkeypatch.setitem(tool_run._listed, "ids", [])
    assert tool_run.tools_doc() == {"tools": []}                                 # refused by its manifest: not listed


def test_a_missing_manifest_runner_lists_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(tool_run, "REPO", tmp_path)
    monkeypatch.setattr(tool_run, "_listed", {})
    assert tool_run.tools_doc() == {"tools": []}


def test_the_image_carries_the_runner_and_the_manifest():
    assert re.search(r"^COPY\b.*\bscripts/tool_manifest\.py\b", DOCKER, re.M)
    assert re.search(r"^COPY\b.*\btools/limit-check/manifest\.json\b", DOCKER, re.M)
