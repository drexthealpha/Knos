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
          "docs/DISCLOSURE.md", "docs/facts.json", "CHANGELOG.md", "docs/MANIFEST.md", "examples/upgrade_gate/src/lib.rs",
          "docs/load.json")


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


def test_every_recorded_order_names_the_fee_schedule_that_applied_and_how_it_is_known():
    """A stored fee decides it; else the build live at the transaction's slot; else what its date rules out."""
    rm = _tool()
    data = rm.prov.load()
    page = (ROOT / "docs" / "MANIFEST.md").read_text(encoding="utf-8")
    body = page.split("## Fee schedule of each recorded order", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in body.splitlines() if line.startswith("| ") and not line.startswith("| order |")]
    assert len(rows) == len(rm.orders(data)) and rows
    public = next(r for r in rows if "public round" in r)
    assert "knos_pay 2.1: orders 2.5% of the first 1,000" in public and "the order's stored fee: 0.40 on 5.00" in public
    # a stored fee that only 2.2 gives is 2.2; the same order with no fee and no slot is not decided
    o = {"what": "x", "tx": "sig", "date": None, "amount": "100.00", "fee": "0.30", "from": "t"}
    assert rm.schedule(o, data, {})[0].startswith("knos_pay 2.2: jobs and orders 0.30%")
    assert rm.schedule({**o, "fee": None}, data, {})[0] == "not decided"
    # a slot: before 2.1 went live nothing this tree knows; from its live slot on, 2.1; from 2.2's live slot, 2.2. Proposal 8
    # executed on 9 October 2026: the cluster read finds 2.2, and 2.1's live slot is kept with the build before it
    rec = data["record"]["programs"]["knos_pay"]
    assert (rec["before"]["proposal"], rec["proposal"]) == (4, 8)
    live, new = rec["before"]["live_slot"], rec["live_slot"]
    assert live < new
    assert rm.schedule({**o, "fee": None}, data, {"sig": {"slot": live - 1}})[0] == "not decided"
    assert rm.schedule({**o, "fee": None}, data, {"sig": {"slot": live}})[0].startswith("knos_pay 2.1")
    assert rm.schedule({**o, "fee": None}, data, {"sig": {"slot": new - 1}})[0].startswith("knos_pay 2.1")
    assert rm.schedule({**o, "fee": None}, data, {"sig": {"slot": new}})[0].startswith("knos_pay 2.2")
    # without the build before, a slot of 2.1's time is decided by nothing this tree knows: never guessed
    alone = copy.deepcopy(data)
    alone["record"]["programs"]["knos_pay"].pop("before")
    assert rm.schedule({**o, "fee": None}, alone, {"sig": {"slot": new - 1}})[0] == "not decided"
    # a slot the feed gives for an execution is taken over the read
    later = copy.deepcopy(data)
    for e in later["upgrades"]["entries"]:
        if e["index"] == 8:
            e.update(status="executed", executed_slot=new + 1000)
    assert rm.schedule({**o, "fee": None}, later, {"sig": {"slot": new + 1000}})[0].startswith("knos_pay 2.2")
    assert rm.schedule({**o, "fee": None}, later, {"sig": {"slot": new + 999}})[0].startswith("knos_pay 2.1")
    # a date before 2.2 could execute, with 2.1 read live the day before: 2.1; the same day as that read: not 2.2 only
    assert rm.schedule({**o, "fee": None, "tx": None, "date": "2026-10-08"}, data, {})[0].startswith("knos_pay 2.1")
    assert rm.schedule({**o, "fee": None, "tx": None, "date": "2026-10-07"}, data, {})[0] == "knos_pay 2.0 or 2.1, not 2.2"


def test_start_here_gives_each_payment_program_one_line_from_source_to_fee_schedule():
    page = (ROOT / "docs" / "MANIFEST.md").read_text(encoding="utf-8")
    start = page.split("## Start here", 1)[1].split("\n## ", 1)[0]
    pay = next(line for line in start.splitlines() if line.startswith("- **knos_pay**"))
    # knos_pay 2.2 runs at the public id since proposal 8 executed: its line ends with 2.2's schedule
    assert pay.count(" -> ") == 4 and "/commit/" in pay and "build `" in pay and "knos_pay 2.2 at `" in pay
    assert "recorded transactions" in pay and "fee schedule: knos_pay 2.2: jobs and orders 0.30% of the amount, at least 0.05" in pay and "pending" not in pay
    assert any(line.startswith("- **knos_oidc**") and "no fee" in line for line in start.splitlines())


def test_read_slots_keeps_each_transactions_slot_and_the_page_then_decides_by_it(tmp_path):
    rm = _tool()
    for rel in COPIED:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    rec = json.loads((ROOT / "docs" / "provenance.json").read_text(encoding="utf-8"))["programs"]["knos_pay"]
    live = rec["live_slot"]
    asked = []
    rm.read_slots(tmp_path, say=lambda _l: None, call=lambda method, params: asked.append(params[0]) or {"slot": live + 5, "blockTime": 1})
    kept = json.loads((tmp_path / "docs" / "fee_slots.json").read_text(encoding="utf-8"))
    assert set(kept) == set(asked) and asked and all(v["slot"] == live + 5 for v in kept.values())
    page = rm.render(tmp_path)
    assert f"the build live at slot {live + 5}: proposal {rec['proposal']}'s, live from slot {live}" in page
