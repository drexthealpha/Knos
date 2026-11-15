"""scripts/diagrams.py: a picture of every Mermaid diagram in README.md and docs/, drawn once per text, and a check
that reads files only. The drawing program is a stand-in here (the real one needs Node and a browser)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAKE_MMDC = '''
import hashlib, json, sys
from pathlib import Path
a = sys.argv[1:]
src, dst = Path(a[a.index("-i") + 1]), Path(a[a.index("-o") + 1])
text = src.read_text(encoding="utf-8")
with Path(__file__).with_name("calls.txt").open("a", encoding="utf-8") as log:
    log.write(text.splitlines()[1].strip() + "\\n")
if "BROKEN" in text:
    sys.stderr.write("Parse error on line 2")
    sys.exit(1)
assert a[a.index("-b") + 1] == "white"
assert json.loads(Path(a[a.index("-c") + 1]).read_text(encoding="utf-8"))["flowchart"] == {"htmlLabels": False}
dst.write_text('<svg id="my-svg" width="100%" xmlns="http://www.w3.org/2000/svg" class="flowchart" '
               'style="max-width: 120.5px; background-color: white;" viewBox="0 0 120.5 40.2"><text>'
               + hashlib.sha256(text.encode("utf-8")).hexdigest() + "</text></svg>", encoding="utf-8")
'''

README = """# Sample

```mermaid
flowchart TB
    A[You put money aside] --> B[The work is checked]
```

*The money waits for the check.*

````markdown
How to write one:
```mermaid
flowchart TB
    X[Not a diagram of this page]
```
````

```python
print("not a diagram")
```

~~~mermaid
flowchart LR
    C[Second] --> D[Diagram]
~~~
_The second diagram, with [a link](docs/A.md)._
"""

DOC = """# A

```mermaid
flowchart TB
    E[Third] --> F[Diagram]
```

*A diagram in a document.*
"""


def _tool():
    spec = importlib.util.spec_from_file_location("diagrams_under_test", ROOT / "scripts" / "diagrams.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path: Path) -> tuple[Path, list[str]]:
    root = tmp_path / "repo"
    (root / "docs" / "sub").mkdir(parents=True)
    (root / "README.md").write_text(README, encoding="utf-8")
    (root / "docs" / "sub" / "A.md").write_text(DOC, encoding="utf-8")
    (root / "docs" / "B.md").write_text("# B\n\nNo diagram.\n", encoding="utf-8")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "mmdc.py").write_text(FAKE_MMDC, encoding="utf-8")
    return root, [sys.executable, str(tools / "mmdc.py")]


def _calls(mmdc: list[str]) -> list[str]:
    log = Path(mmdc[1]).with_name("calls.txt")
    return log.read_text(encoding="utf-8").splitlines() if log.is_file() else []


def test_a_page_has_its_diagrams_and_their_captions_and_not_the_ones_it_shows():
    d = _tool()
    found = d.parse(README, "README.md")
    assert [(b.n, b.caption) for b in found] == [(1, "The money waits for the check."), (2, "The second diagram, with [a link](docs/A.md).")]
    assert found[0].text == "flowchart TB\n    A[You put money aside] --> B[The work is checked]\n"
    assert found[0].sha256 == hashlib.sha256(found[0].text.encode("utf-8")).hexdigest()
    assert [b.svg for b in found] == ["docs/diagrams/readme-1.svg", "docs/diagrams/readme-2.svg"]
    assert d.parse(README.replace("\n", "\r\n"), "README.md") == found          # a page saved on Windows is the same page
    assert d.slug("examples/witnessed/README.md") == "examples-witnessed-readme"
    assert [b.caption for b in d.parse("```mermaid\nflowchart TB\n  A\n```\n**Bold is not a caption**\n", "x.md")] == [None]


def test_each_diagram_is_drawn_once_and_a_second_run_draws_nothing(tmp_path):
    d = _tool()
    root, mmdc = _tree(tmp_path)
    assert d.check(root)                                                          # nothing drawn yet
    drawn, gone, failed = d.render(root, mmdc)
    assert drawn == ["docs/diagrams/readme-1.svg", "docs/diagrams/readme-2.svg", "docs/diagrams/docs-sub-a-1.svg"]
    assert gone == [] and failed == [] and len(_calls(mmdc)) == 3
    assert d.check(root) == []
    index = json.loads((root / "docs" / "diagrams" / "index.json").read_text(encoding="utf-8"))
    assert [(e["source"], e["block"], e["svg"]) for e in index["diagrams"]] == [
        ("README.md", 1, "docs/diagrams/readme-1.svg"), ("README.md", 2, "docs/diagrams/readme-2.svg"),
        ("docs/sub/A.md", 1, "docs/diagrams/docs-sub-a-1.svg")]
    assert index["diagrams"][0]["sha256"] == d.parse(README, "README.md")[0].sha256
    svg = (root / "docs" / "diagrams" / "readme-1.svg").read_text(encoding="utf-8")
    assert svg.startswith('<svg width="121" height="41" id="my-svg"') and "100%" not in svg and "max-width" not in svg
    assert "background-color: white" in svg
    before = {p.name: p.read_bytes() for p in (root / "docs" / "diagrams").iterdir()}
    assert d.render(root, mmdc) == ([], [], []) and len(_calls(mmdc)) == 3       # idempotent: mmdc is not run again
    assert {p.name: p.read_bytes() for p in (root / "docs" / "diagrams").iterdir()} == before
    assert d.render(root, ["no-such-mmdc-program"]) == ([], [], [])              # nothing to draw: the program is not needed


def test_a_changed_diagram_is_drawn_again_and_a_removed_one_is_deleted(tmp_path):
    d = _tool()
    root, mmdc = _tree(tmp_path)
    d.render(root, mmdc)
    page = root / "README.md"
    page.write_text(README.replace("C[Second]", "C[Second, changed]"), encoding="utf-8")
    assert d.check(root) == ["README.md, diagram 2: no picture of this text (python scripts/diagrams.py render)"]
    assert d.render(root, mmdc)[0] == ["docs/diagrams/readme-2.svg"] and _calls(mmdc)[-1] == "C[Second, changed] --> D[Diagram]"
    assert d.check(root) == []
    (root / "docs" / "sub" / "A.md").write_text("# A\n\nThe diagram went away.\n", encoding="utf-8")
    said = d.check(root)
    assert said == ["docs/diagrams/index.json: docs/diagrams/docs-sub-a-1.svg is the picture of a diagram that is gone (python scripts/diagrams.py render)",
                    "docs/diagrams/docs-sub-a-1.svg: the picture of no diagram (python scripts/diagrams.py render deletes it)"]
    assert d.render(root, mmdc) == ([], ["docs/diagrams/docs-sub-a-1.svg"], [])
    assert d.check(root) == [] and not (root / "docs" / "diagrams" / "docs-sub-a-1.svg").exists()


def test_check_reads_files_only_and_names_each_problem(tmp_path, monkeypatch):
    d = _tool()
    root, mmdc = _tree(tmp_path)
    d.render(root, mmdc)

    def refuse(*a, **k):
        raise AssertionError("--check runs no program")
    monkeypatch.setattr(d.subprocess, "run", refuse)
    monkeypatch.setattr(d.shutil, "which", refuse)
    assert d.check(root) == []
    (root / "docs" / "diagrams" / "readme-1.svg").unlink()
    (root / "docs" / "diagrams" / "stray.svg").write_text("<svg/>", encoding="utf-8")
    (root / "docs" / "sub" / "A.md").write_text(DOC.replace("*A diagram in a document.*\n", ""), encoding="utf-8")
    assert d.check(root) == ["docs/diagrams/readme-1.svg: missing (python scripts/diagrams.py render)",
                             "docs/sub/A.md, diagram 1: no caption (one line in italics under the block)",
                             "docs/diagrams/stray.svg: the picture of no diagram (python scripts/diagrams.py render deletes it)"]


def test_a_diagram_mmdc_cannot_draw_is_named_and_the_others_are_drawn(tmp_path):
    d = _tool()
    root, mmdc = _tree(tmp_path)
    (root / "docs" / "sub" / "A.md").write_text(DOC.replace("E[Third] --> F[Diagram]", "BROKEN"), encoding="utf-8")
    drawn, _gone, failed = d.render(root, mmdc)
    assert drawn == ["docs/diagrams/readme-1.svg", "docs/diagrams/readme-2.svg"]
    assert failed == ["docs/sub/A.md, diagram 1: mmdc could not draw it: Parse error on line 2"]
    assert d.check(root) == ["docs/sub/A.md, diagram 1: no picture of this text (python scripts/diagrams.py render)"]


def test_the_tree_has_a_picture_of_every_diagram():
    """After a diagram is added or changed, run `python scripts/diagrams.py render` (it needs mermaid-cli)."""
    d = _tool()
    assert d.check(ROOT) == []
    assert d.main(["--check"]) == 0
