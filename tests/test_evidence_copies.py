"""One Knos: the evidence repositories (evidence/<repo>/) are folders of Knos. Each folder holds the files
of one commit of the old repository byte for byte, and its SOURCE.json names that repository, the commit, the git
tree id and every file with its git blob id. These tests recompute the blob of every file and the git tree of the
folder from the bytes in this checkout (SOURCE.json left out), so a copy that drifts by one byte fails, and the copies
stay inert: no workflow of theirs is one of Knos's own."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(ROOT.glob("evidence/*/SOURCE.json"))
EVIDENCE = ("knos-witness", "knos-load", "knos-v0329-gate", "knos-v0329-outcomes")


def _obj(kind: bytes, body: bytes) -> bytes:
    return hashlib.sha1(kind + b" " + str(len(body)).encode() + b"\0" + body).digest()


def tree_id(entries: dict[str, tuple[str, bytes]]) -> str:
    """The id git gives the tree holding these files: {path: (mode, blob id as 20 bytes)}. Modes 100644 and 100755."""
    def tree(prefix: str) -> bytes:
        found: dict[str, tuple[bytes, bytes]] = {}
        for rel, (mode, oid) in entries.items():
            if rel.startswith(prefix):
                name, _, rest = rel[len(prefix):].partition("/")
                found[name] = (b"40000", tree(prefix + name + "/")) if rest else (mode.encode(), oid)
        ordered = sorted(found.items(), key=lambda kv: (kv[0] + "/" if kv[1][0] == b"40000" else kv[0]).encode())
        return _obj(b"tree", b"".join(m + b" " + n.encode() + b"\0" + o for n, (m, o) in ordered))
    return tree("").hex()


def _load(source: Path) -> dict:
    return json.loads(source.read_text(encoding="utf-8"))


def test_every_repository_of_the_task_has_a_folder():
    names = {(_load(s)["repository"], s.parent.relative_to(ROOT).as_posix()) for s in SOURCES}
    for repo in EVIDENCE:
        assert (f"drexthealpha/{repo}", f"evidence/{repo}") in names, repo


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.parent.relative_to(ROOT).as_posix())
def test_the_folder_is_the_commit_byte_for_byte(source: Path):
    meta = _load(source)
    folder = source.parent
    assert re.fullmatch(r"[0-9a-f]{40}", meta["commit"]) and re.fullmatch(r"[0-9a-f]{40}", meta["tree"])
    changed = meta.get("changed_here", {})
    have = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p != source and "__pycache__" not in p.parts)
    assert have == sorted(f["path"] for f in meta["files"])
    entries = {}
    for f in meta["files"]:
        data = (folder / f["path"]).read_bytes()
        got = _obj(b"blob", data).hex()
        if f["path"] in changed:
            assert got != f["blob"] and changed[f["path"]]["blob"] == got, f["path"]
        else:
            assert got == f["blob"] and len(data) == f["size"], f["path"]
        entries[f["path"]] = (f["mode"], bytes.fromhex(f["blob"]))
    # with the original blob of a file changed here (named, with its reason), the folder is the tree of the commit
    assert tree_id(entries) == meta["tree"]


def test_their_workflows_are_inert_here():
    own = {p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")}
    for source in SOURCES:
        for wf in source.parent.glob(".github/workflows/*.yml"):
            # GitHub runs only the root .github/workflows/; a copy under a folder never runs
            assert wf.parent != ROOT / ".github" / "workflows", wf
    assert own, "Knos's own workflows are where they were"


def test_the_cited_witness_record_is_in_knos_and_the_documents_link_it():
    meta = _load(ROOT / "evidence" / "knos-witness-acaa854d" / "SOURCE.json")
    assert meta["commit"].startswith("acaa854d") and meta["repository"] == "drexthealpha/knos-witness"
    record = json.loads((ROOT / "evidence" / "knos-witness-acaa854d" / "witness.json").read_text(encoding="utf-8"))
    assert record
    rel = "evidence/knos-witness-acaa854d/witness.json"
    for doc in ("README.md", "docs/TRANSACTION.md", "docs/START.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert rel in text, doc
        assert "knos-witness/blob/" not in text, doc


def test_the_outcome_demo_names_its_commits_and_they_are_here():
    pinned = _load(ROOT / "evidence" / "knos-v0329-outcomes" / "SOURCE.json")
    data = _load(ROOT / "evidence" / "knos-v0329-outcomes-b59b30f3" / "SOURCE.json")
    demo = json.loads((ROOT / "examples" / "outcomes" / "measured-support" / "demo.json").read_text(encoding="utf-8"))
    assert demo["pinned_commit"] == pinned["commit"] and demo["data_commit"] == data["commit"]
    page = (ROOT / "docs" / "reference" / "OUTCOMES.md").read_text(encoding="utf-8")
    assert "evidence/knos-v0329-outcomes" in page and "evidence/knos-v0329-outcomes-b59b30f3" in page

