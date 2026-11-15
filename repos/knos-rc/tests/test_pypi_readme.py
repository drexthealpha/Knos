"""PyPI shows the package's description alone: every link in it must be whole and name the release's tag, while
README.md stays relative for GitHub (scripts/bump_version.py writes README.pypi.md from it)."""
from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bump():
    spec = importlib.util.spec_from_file_location("bump_version_for_pypi", ROOT / "scripts" / "bump_version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _version() -> str:
    return re.search(r'(?m)^version = "([\d.]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)


def test_the_package_description_is_the_pinned_readme_and_no_relative_link_remains():
    b = _bump()
    assert re.search(r'(?m)^readme = "README\.pypi\.md"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    text = (ROOT / "README.pypi.md").read_text(encoding="utf-8")
    assert b.relative_left(text) == []
    assert text == b.pypi_readme((ROOT / "README.md").read_text(encoding="utf-8"), _version())
    assert not b.pypi_stale(_version())
    # README.md itself keeps the relative links GitHub follows
    assert b.relative_left((ROOT / "README.md").read_text(encoding="utf-8"))
    for url in re.findall(r"https://github\.com/drexthealpha/Knos/(?:blob|tree)/[^)\s\"#]+", text):
        assert f"/v{_version()}/" in url, url


def test_each_kind_of_link_becomes_whole_at_the_tag(tmp_path):
    b = _bump()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "A.md").write_text("a\n", encoding="utf-8")
    page = ("[a](docs/A.md) [b](./docs/A.md#part) [folder](docs) [top](#limits) ![logo](web/brand/x.svg)\n"
            "[ext](https://example.org/x) [mail](mailto:a@b.c) [t](docs/A.md \"title\")\n"
            '<img src="web/logo.png"> <a href="docs/A.md">a</a>\n'
            "[ref]: docs/A.md\n")
    out = b.pypi_readme(page, "9.8.7", tmp_path)
    blob, raw = "https://github.com/drexthealpha/Knos/blob/v9.8.7", "https://raw.githubusercontent.com/drexthealpha/Knos/v9.8.7"
    for want in (f"[a]({blob}/docs/A.md)", f"[b]({blob}/docs/A.md#part)",
                 "[folder](https://github.com/drexthealpha/Knos/tree/v9.8.7/docs)", f"[top]({blob}/README.md#limits)",
                 f"![logo]({raw}/web/brand/x.svg)", "[ext](https://example.org/x)", "[mail](mailto:a@b.c)",
                 f'[t]({blob}/docs/A.md "title")', f'<img src="{raw}/web/logo.png">', f'<a href="{blob}/docs/A.md">',
                 f"[ref]: {blob}/docs/A.md"):
        assert want in out, want
    assert b.relative_left(out) == []


def test_a_bump_rewrites_it_and_check_fails_when_it_is_stale(tmp_path):
    b = _bump()
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    assert b.pypi_stale("1.2.3", tmp_path)
    assert b.pypi_stale("1.2.3", tmp_path, write=True)
    assert not b.pypi_stale("1.2.3", tmp_path)
    assert "/blob/v1.2.3/" in (tmp_path / "README.pypi.md").read_text(encoding="utf-8")
    (tmp_path / "README.md").write_text("[x](docs/NEW.md)\n", encoding="utf-8")
    assert b.pypi_stale("1.2.3", tmp_path)


def test_a_diagram_is_its_picture_at_the_tag_on_pypi(tmp_path):
    """PyPI does not draw Mermaid: each of README.md's diagrams is its picture (scripts/diagrams.py draws them), and its
    italic caption is the picture's text and stays under it."""
    b = _bump()
    page = ("# Page\n\n```mermaid\nflowchart TB\n    A[You] --> B[Them]\n```\n\n*The money moves on a [check](docs/A.md).*\n\n"
            "```python\nprint(1)\n```\n\n~~~mermaid\nflowchart LR\n    C --> D\n~~~\n")
    out = b.pypi_readme(page, "9.8.7", tmp_path)
    raw = "https://raw.githubusercontent.com/drexthealpha/Knos/v9.8.7" + "/docs/diagrams"     # split: a whole one is a pin a bump moves
    assert "mermaid" not in out and "flowchart" not in out and "```python\nprint(1)\n```" in out
    assert f"![The money moves on a check.]({raw}/readme-1.svg)\n\n*The money moves on a [check](" in out
    assert f"![Diagram]({raw}/readme-2.svg)\n" in out
    assert b.relative_left(out) == []
    (tmp_path / "README.md").write_text(page, encoding="utf-8")
    assert b.missing_pictures(tmp_path) == [f"README.md, diagram {n}: no docs/diagrams/readme-{n}.svg (python scripts/diagrams.py render)"
                                            for n in (1, 2)]
    (tmp_path / "docs" / "diagrams").mkdir(parents=True)
    for n in (1, 2):
        (tmp_path / "docs" / "diagrams" / f"readme-{n}.svg").write_text("<svg/>", encoding="utf-8")
    assert b.missing_pictures(tmp_path) == []


def test_the_package_description_draws_no_mermaid_and_each_picture_is_at_the_tag_and_exists():
    b = _bump()
    text = (ROOT / "README.pypi.md").read_text(encoding="utf-8")
    assert "```mermaid" not in text and "~~~mermaid" not in text
    pictures = re.findall(r"https://raw\.githubusercontent\.com/drexthealpha/Knos/([^/\s)]+)/(docs/diagrams/[^)\s\"]+)", text)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(pictures) == readme.count("```mermaid") + readme.count("~~~mermaid")
    for ref, path in pictures:
        assert ref == f"v{_version()}" and (ROOT / path).is_file(), (ref, path)
    assert b.missing_pictures() == []
