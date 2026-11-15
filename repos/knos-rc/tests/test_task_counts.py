"""outsiders.json `task_counts` (scripts/pages_data.py `playground_task_counts`): the counters the tasks that are not code
can move, read from the evidence files merged into the playground (outside/<kind>/<login>.json), each checked by
knos.tasks.accepts and held to the account its name says. Not read is None, never 0; no folder yet is a reading of 0."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pages_data  # noqa: E402
from test_tasks import GOOD  # noqa: E402

PG = pages_data.PLAYGROUND
OWN = frozenset({142920951})


class NotFound(Exception):
    code = 404


def forge(files: dict[str, object], users: dict[str, int]):
    folders = sorted({p.split("/")[1] for p in files})
    asked: list[str] = []

    def get(path: str):
        asked.append(path)
        if path == f"repos/{PG}/contents/outside":
            return [{"type": "dir", "name": f} for f in folders] + [{"type": "file", "name": "README.md"}]
        for f in folders:
            if path == f"repos/{PG}/contents/outside/{f}":
                return [{"type": "file", "name": p.split("/")[-1], "path": p} for p in files if p.split("/")[1] == f]
        for p, body in files.items():
            if path == f"repos/{PG}/contents/{p}":
                return {"content": base64.b64encode(json.dumps(body).encode()).decode()}
        if path.startswith("users/") and path[6:] in users:
            return {"id": users[path[6:]]}
        raise NotFound(path)
    return get, asked


def test_merged_evidence_moves_its_counter_once_and_only_for_the_account_its_file_names():
    files = {"outside/witness/stranger.json": GOOD["witness"], "outside/keyholder/stranger.json": GOOD["keyholder"],
             "outside/keyholder/mallory.json": GOOD["keyholder"],                         # mallory's file names the stranger's id
             "outside/compose/founder.json": {**GOOD["compose"], "actor_id": 142920951}}  # Knos's own account moves nothing
    get, _ = forge(files, {"stranger": 4242, "mallory": 666, "founder": 142920951})
    got = pages_data.playground_task_counts(get, OWN, frozenset())
    assert got["measured"] is True and got["files"] == 4 and got["label"] == "on tasks Knos funded itself"
    assert (got["witnessed"], got["key_offers"], got["programs"], got["gates"], got["outside_cheats"]) == (1, 1, 0, 0, 0)


def test_no_folder_yet_is_zero_and_github_not_answering_or_not_asked_is_none():
    def none(path):
        raise NotFound(path)
    zero = pages_data.playground_task_counts(none, OWN, frozenset())
    assert zero["measured"] is True and zero["witnessed"] == 0 and zero["files"] == 0

    def down(path):
        raise OSError("502")
    for get in (down, None):
        unread = pages_data.playground_task_counts(get, OWN, frozenset())
        assert unread["measured"] is False and unread["witnessed"] is None and unread["files"] is None
    empty = json.loads(pages_data.empty(1_790_000_000)["outsiders.json"])["task_counts"]
    assert empty["measured"] is False and all(empty[k] is None for k in ("programs", "gates", "key_offers", "outside_cheats", "witnessed"))
