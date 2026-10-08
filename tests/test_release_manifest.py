"""docs/MANIFEST.md, the capability rows: one row for each capability, seven cells, none of them blank, each cell from
the file that owns it (docs/capabilities.json, docs/provenance.json)."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIED = ("pyproject.toml", "programs-v2/program_ids.json", "docs/capabilities.json", "docs/provenance.json", "web/upgrades.json",
          "docs/DISCLOSURE.md", "docs/facts.json", "CHANGELOG.md", "docs/MANIFEST.md", "examples/upgrade_gate/src/lib.rs")


def _tool():
    spec = importlib.util.spec_from_file_location("release_manifest_rows", ROOT / "scripts" / "release_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(page: str) -> dict[str, list[str]]:
    body = page.split("## Capabilities: the stage of each, with its evidence", 1)[1].split("\n## ", 1)[0]
    rows = [[cell.strip() for cell in line.replace("\\|", "\x00").strip().strip("|").split("|")] for line in body.splitlines() if line.startswith("| `")]
    return {r[0].strip("`"): [cell.replace("\x00", "|") for cell in r] for r in rows}


def test_every_capability_is_one_row_of_seven_cells_and_no_cell_is_blank():
    rm = _tool()
    page = (ROOT / "docs" / "MANIFEST.md").read_text(encoding="utf-8")
    assert "| capability | stage | source | test | deployed build | transaction | independent reproduction |" in page
    caps = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]
    rows = _rows(page)
    assert list(rows) == [c["id"] for c in caps]
    for c in caps:
        row = rows[c["id"]]
        assert len(row) == len(rm.HEAD) == 7 and all(row), c["id"]
        ev = c["evidence"]
        assert (row[2] == "none") == ("implemented" not in ev) and (row[3] == "none") == ("tested" not in ev), c["id"]
        assert (row[4] == "none") == ("deployed" not in ev) and (row[5] == "none") == ("exercised" not in ev), c["id"]
        assert (row[6] == "none") == ("reproduced" not in ev), c["id"]
        if "implemented" in ev:
            assert ev["implemented"]["path"] in row[2] and (ROOT / ev["implemented"]["path"]).exists()
        if "tested" in ev:
            assert ev["tested"]["test"] in row[3]
        if "exercised" in ev:
            assert f"https://explorer.solana.com/tx/{ev['exercised']['signature']}?cluster=devnet" in row[5]


def test_a_deployed_build_names_the_hash_read_at_the_public_id_and_says_when_the_id_has_moved_on():
    rm = _tool()
    data = rm.prov.load()
    seen, listed = data["record"]["programs"], data["capabilities"]["programs"]
    c = {"id": "x", "stage": "deployed", "evidence": {"deployed": {"program": "knos_meter", "id": listed["knos_meter"]["id"],
                                                                 "version": listed["knos_meter"]["on_chain"]}}}
    cell = rm.build_of(c, data)
    assert cell == f"`knos_meter {listed['knos_meter']['on_chain']}`, hash at its public id `{seen['knos_meter']['on_chain_hash'][:16]}`"
    older = copy.deepcopy(c)
    older["evidence"]["deployed"]["version"] = "0.9"
    assert "`knos_meter 0.9` and later; its public id runs " + listed["knos_meter"]["on_chain"] in rm.build_of(older, data)
    staged = copy.deepcopy(c)
    staged["evidence"]["deployed"]["id"] = "1" * 32                       # not a public id: nothing is deployed where it counts
    assert rm.build_of(staged, data).startswith("none at a public id")
    unread = copy.deepcopy(data)
    unread["record"] = {}
    assert rm.build_of(c, unread).endswith("hash at its public id not read")
    assert rm.build_of({"id": "y", "stage": "tested", "evidence": {}}, data) == "none"


def test_no_reproduction_is_said_as_none_and_one_that_is_recorded_is_linked():
    rm = _tool()
    assert rm.reproduction_of({"evidence": {}}) == "none"
    assert rm.reproduction_of({"evidence": {"reproduced": {"url": "https://example.org/run/1"}}}) == "[outside run](https://example.org/run/1)"
    assert rm.reproduction_of({"evidence": {"reproduced": {"file": "reproductions/a.json"}}}) == "[`reproductions/a.json`](../reproductions/a.json)"
    page = (ROOT / "docs" / "MANIFEST.md").read_text(encoding="utf-8")
    caps = json.loads((ROOT / "docs" / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]
    if not any("reproduced" in c["evidence"] for c in caps):
        assert all(row[6] == "none" for row in _rows(page).values())


def test_a_name_with_a_bar_in_it_does_not_break_its_row():
    rm = _tool()
    c = {"id": "z", "stage": "implemented", "evidence": {"implemented": {"path": "src/knos/cli.py", "names": "a | b"}}}
    line = "| " + " | ".join(rm.row(c, rm.prov.load())) + " |"
    assert _rows("## Capabilities: the stage of each, with its evidence\n" + line)["z"][2].endswith("`a | b`")


def test_the_check_fails_when_a_capability_gains_evidence_the_page_does_not_show(tmp_path):
    rm = _tool()
    for rel in COPIED:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    assert rm.main(["--check"], say=lambda _line: None, root=tmp_path) == 0
    path = tmp_path / "docs" / "capabilities.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["capabilities"][0]["evidence"]["tested"]["names"] = "test_another_name"
    path.write_text(json.dumps(data), encoding="utf-8")
    said: list[str] = []
    assert rm.main(["--check"], say=said.append, root=tmp_path) == 1 and "stale" in said[0]
    assert rm.main([], say=said.append, root=tmp_path) == 0
    assert "`test_another_name`" in (tmp_path / "docs" / "MANIFEST.md").read_text(encoding="utf-8")
