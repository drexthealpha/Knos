"""docs/README.md is the map of the documents: every file in docs/*.md is on it once, under one of six questions, and
every link on it leads to a file. docs/STORY.md and web/story.js tell the three-minute demonstration in seven beats, each
with evidence that exists in the repository; what follows the last beat is an invitation and claims nobody. docs/MANIFEST.md
is what scripts/release_manifest.py writes from its sources.

Everything here reads files; the one subprocess is node on tests/web/story.mjs, and it opens no network.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
QUESTIONS = ["Does it work?", "Why does it matter?", "What is new?", "How do I use it?", "How do I build on it?", "How is it run and paid for?"]
STEPS = 7
WORDS = re.compile(r"[A-Za-z0-9][\w'%.,/-]*")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def links(text: str) -> list[str]:
    return re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text)


def test_every_document_is_on_the_map_once_under_one_of_six_questions():
    page = read("docs/README.md")
    heads = re.findall(r"(?m)^## (\d)\. (.+)$", page)
    assert [h[1] for h in heads] == QUESTIONS and [int(h[0]) for h in heads] == list(range(1, 7))
    mapped = page.split("\n## What is in this repository")[0]
    rows = re.findall(r"(?m)^\| \[([^\]]+)\]\(([^)]+)\) \| (.+) \|$", mapped)
    listed = [target for _name, target, _what in rows]
    here = sorted(p.name for p in DOCS.glob("*.md") if p.name != "README.md")
    assert sorted(set(here) - set(listed)) == [], "a document in docs/ is missing from docs/README.md: add one row for it"
    assert sorted(t for t in listed if listed.count(t) > 1 and t != "STORY.md") == []      # STORY.md is also the first row
    assert all(len(WORDS.findall(what)) <= 22 for _n, _t, what in rows), [w for _n, _t, w in rows if len(WORDS.findall(w)) > 22]
    for target in links(page):                                                              # every link leads somewhere
        assert target.startswith("https://") or (DOCS / target).exists(), target


def test_the_front_page_has_seven_parts_above_the_line_and_three_links_onward():
    readme = read("README.md")
    above, below = readme.split("\n---\n", 1)
    # the claim and the meter lead; the bounty is the smallest example of the money; a judge's one entry (tests/test_judges.py);
    # the table of today's numbers is lower
    assert re.findall(r"(?m)^## (.+)$", above) == ["The claim", "The meter: two ledgers, one bill", "The money: released on a signature", "The number",
                                                    "For a judge", "What is real today", "Read more"]
    more = above.split("## Read more")[1]
    assert links(more) == ["docs/STORY.md", "docs/MANIFEST.md", "docs/README.md"]
    claim = [line for line in above.split("## The claim")[1].split("\n## ")[0].splitlines() if line.strip()]
    assert claim[:2] == ["Two parties who distrust each other compute the same bill from evidence a third party signed.",
                         "The program releases the money on that signature, with no company and no oracle in the middle."]
    assert len(claim) == 3 and claim[2].startswith("Limits, in one line: ") and links(claim[2]) == ["docs/DISCLOSURE.md"]      # ONE line of limits
    for said in ("devnet", "test USDC", "no outside users yet"):
        assert said in claim[2], said
    assert above.index("## The claim") < above.index("<!-- bench:today -->") and "smallest example is a bounty" in above
    table = above[above.index("<!-- bench:today -->"):above.index("<!-- /bench:today -->")]
    numbers = read("docs/submission/NUMBERS.md")
    printed = re.findall(r"(?m)^\| \d \| ([^:|]+)[^|]*\| (\d+) \|", numbers)
    assert len(printed) == 9
    for what, value in printed:                                                             # every number that page prints, zeros included
        assert re.search(rf"(?m)^\| {re.escape(what.strip())} \| {value}\b", table), what
    assert "<!-- programs:start -->" in below and "<!-- capabilities:start -->" in below and "## " not in below
    for rel in links(readme):
        assert rel.startswith("https://") or (ROOT / rel).exists(), rel


def test_the_story_is_seven_beats_each_with_evidence_that_exists_and_asks_for_three_things():
    story = read("docs/STORY.md")
    lines = [line for line in story.splitlines() if line.strip()]
    assert lines[1] == "**The neutral meter for AI agent work: neither side keeps the count.**"
    assert lines[2] == "Of 241 merged agent pull requests that claimed passing tests, 30 had a failed check."
    steps = re.findall(r"(?m)^(\d)\. \*\*(.+?)\*\* (.+)\n   Evidence: \[([^\]]+)\]\(([^)]+)\)", story)
    assert [int(s[0]) for s in steps] == list(range(1, STEPS + 1))
    for _n, title, said, _name, target in steps:
        assert len(WORDS.findall(f"{title} {said}")) <= 12, (title, said)
        assert target.startswith("https://") or (DOCS / target.split("#")[0]).exists(), target
    assert [s[1] for s in steps] == ["Buyer and supplier agree one task.", "A claimed success fails the condition.", "Valid work passes.",
                                     "Both sides make the same statement.", "A replay pays nothing.", "The payment executes.",
                                     "A verifier checks it offline."]            # Agree, Fails, Passes, Statement, Replay, Pay, Verify
    assert "Agree, Fails, Passes, Statement, Replay, Pay, Verify" in story and "](../web/demo.js)" in story
    after = story.split(steps[-1][4])[1].split("\n## ")[0]                                  # what follows the last beat claims nobody
    assert "Then your own invoice: [check it](https://drexthealpha.github.io/Knos/). Nobody has paid for this yet." in after
    for _n, title, said, _name, _target in steps:
        for word in ("customer", "paid us", "pilot"):
            assert word not in f"{title} {said}".lower()
    # a link to a run on staging program ids says so in its own words, and the page says which beats
    staged = [int(n) for n, _t, _s, name, _target in steps if "staging program ids" in name]
    assert staged == [] and "The transactions of steps 1, 5 and 6 are one round on the public program ids" in " ".join(story.split())
    assert "](MANIFEST.md)" in story and "](submission/demo_script.md)" in story
    ask = story.split("## The ask")[1].split("\n## ")[0]
    needs = re.findall(r"(?m)^\d\. (.+)$", ask)
    assert len(needs) == 3 and all(n.startswith("Needed: ") for n in needs)
    assert "outside key holder" in needs[0] and "shadow count" in needs[1] and "outside review" in needs[2]


def test_the_page_tells_the_same_seven_beats_and_stands_still_under_reduced_motion():
    source = read("web/story.js")
    assert "export function renderStory(el, ctx" in source and "prefersReduced" in source
    assert not re.search(r"https?://(?!drexthealpha\.github\.io|github\.com/drexthealpha|explorer\.solana\.com)", source)
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "web" / "story.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def _manifest():
    spec = importlib.util.spec_from_file_location("release_manifest", ROOT / "scripts" / "release_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_program_whose_proposal_ran_and_a_newer_one_is_pending_names_the_pending_one_in_its_row():
    import copy
    rm = _manifest()
    data = copy.deepcopy(rm.prov.load())
    ran = {"index": 4, "program": "knos_pay", "status": "executed", "build_hash": "a" * 64, "source_commit": "1" * 40, "gate_run": 1}
    later = {"index": 8, "program": "knos_pay", "status": "pending", "build_hash": "b" * 64, "source_commit": "2" * 40, "gate_run": 2}
    data["upgrades"] = {**data["upgrades"], "entries": [later, ran]}
    seen = data["record"].setdefault("programs", {})
    seen["knos_pay"] = {**seen.get("knos_pay", {}), "on_chain_hash": "a" * 64}
    row = next(line for line in rm.programs(data) if line.startswith("| knos_pay | `"))
    # what is live is the build that ran; the row's proposal is the one that would replace it, and it has not run
    assert "| 8: pending |" in row and f"`{'b' * 64}`" in row and "(not the proposal's build)" in row and f"`{'a' * 64}`" in row
    assert "| 4: executed |" not in row
    # with nothing pending after it, the row is the proposal that ran, and the hash at the id is its build
    data["upgrades"]["entries"] = [ran]
    row = next(line for line in rm.programs(data) if line.startswith("| knos_pay | `"))
    assert "| 4: executed |" in row and "(the proposal's build)" in row


def test_the_release_manifest_is_what_its_sources_give_and_states_what_is_live_from_the_records():
    rm = _manifest()
    said = []
    assert rm.main(["--check"], say=said.append) == 0, said
    page = read("docs/MANIFEST.md")
    assert page == rm.render() and page.splitlines()[0] == f"# Release manifest: Knos {rm.version()}"
    for head in ("## Source", "## Programs: what is live at each public id", "## Pending proposals", "## Capabilities: the stage of each, with its evidence",
                 "## Outstanding limits"):
        assert f"\n{head}\n" in page, head
    # what is LIVE is the version the capability manifest records and the hash the last read of the cluster found: never the proposal's
    import json
    caps, seen = json.loads(read("docs/capabilities.json")), json.loads(read("docs/provenance.json"))["programs"]
    feed = json.loads(read("web/upgrades.json"))
    for name, program in caps["programs"].items():
        row = next(line for line in page.splitlines() if line.startswith(f"| {name} | `{program['id']}` |"))
        assert f"| {name} {program['on_chain']} |" in row, name
        if name in seen:
            assert f"`{seen[name]['on_chain_hash']}`" in row, name
    for entry in feed["entries"]:
        if entry["status"] == "pending":                                                  # a pending proposal is listed, and is not called live
            assert f"| {entry['index']} (`{entry['proposal']}`) | {entry['program']} | `{entry['build_hash']}` |" in page
            row = next(line for line in page.splitlines() if line.startswith(f"| {entry['program']} | `"))
            assert f"| {entry['index']}: pending |" in row and "(not the proposal's build)" in row
    # every capability is a row with its stage; every limit of DISCLOSURE.md is a line, once
    for c in caps["capabilities"]:
        assert page.count(f"| `{c['id']}` | ") == 1, c["id"]
    limits = rm.limits()
    assert len(limits) == len(set(limits)) >= 10 and all(page.count(line) == 1 for line in limits)
    assert all("\n" not in line and line.startswith("- **") for line in limits)             # one line each
    assert not re.search(r"\b20\d\d-\d\d-\d\d", page)                                       # no time is printed
    for rel in ("README.md", "docs/README.md", "docs/STORY.md"):
        assert "MANIFEST.md" in read(rel), rel


def test_the_release_manifest_check_fails_when_a_source_moves(tmp_path):
    rm = _manifest()
    for rel in ("pyproject.toml", "programs-v2/program_ids.json", "docs/capabilities.json", "docs/provenance.json", "web/upgrades.json",
                "docs/DISCLOSURE.md", "docs/facts.json", "CHANGELOG.md", "docs/MANIFEST.md", "examples/upgrade_gate/src/lib.rs",
                "docs/load.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    assert rm.main(["--check"], say=lambda _line: None, root=tmp_path) == 0
    page = tmp_path / "docs" / "DISCLOSURE.md"
    page.write_text(page.read_text(encoding="utf-8").replace("- **No letter of intent.**", "- **One letter of intent.**"), encoding="utf-8")
    said = []
    assert rm.main(["--check"], say=said.append, root=tmp_path) == 1 and "stale" in said[0]
    assert rm.main([], say=said.append, root=tmp_path) == 0 and "- **One letter of intent.**" in (tmp_path / "docs" / "MANIFEST.md").read_text(encoding="utf-8")
