"""A picture of every Mermaid diagram, for the pages that cannot draw Mermaid.

    python scripts/diagrams.py render [--mmdc PATH] [--puppeteer-config FILE]
        draw each diagram whose text changed; delete the pictures of diagrams that are gone
    python scripts/diagrams.py --check
        change nothing; exit 1 when a diagram has no picture of its text, or a picture has no diagram

GitHub draws a ```mermaid block itself. PyPI does not: the package's page (README.pypi.md, written by
scripts/bump_version.py) shows each of README.md's diagrams as its picture at the release's tag instead.

A diagram is a ```mermaid block in README.md or in a document under docs/. Its picture is
docs/diagrams/<the file's path as a slug>-<n>.svg, n counting the file's diagrams from 1: README.md's second diagram is
docs/diagrams/readme-2.svg, docs/METER.md's first is docs/diagrams/docs-meter-1.svg. docs/diagrams/index.json lists
each one: the file, n, the sha256 of the block's text (the lines between the fences, each ending in a newline) and the
picture. `render` draws a block again only when that sha256 changed, so a second run draws nothing. `--check` reads
files only: it needs no Node and no network, and the test suite runs it on the tree (tests/test_diagrams.py).

The pictures come from mermaid-cli (mmdc) on a white background, with labels as SVG text (no HTML inside the SVG, which
some image viewers do not draw), and each says its own size, so a small diagram is not stretched across a page. No
colour and no theme is set here or in the blocks: GitHub draws them in light and dark itself.

Every diagram also needs its caption: one line in italics under the block (`*What the picture shows.*`). The PyPI page
uses it as the picture's text; `--check` fails without it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
OUT = "docs/diagrams"
INDEX = f"{OUT}/index.json"
ABOUT = ("Written by scripts/diagrams.py render: a picture of every Mermaid diagram in README.md and docs/, "
         "for pages that cannot draw Mermaid (PyPI). Do not edit.")
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
CAPTION = re.compile(r"^\s*(?:\*(?!\*)(?P<a>.*\S)\*|_(?!_)(?P<b>.*\S)_)\s*$")
CONFIG = {"htmlLabels": False, "flowchart": {"htmlLabels": False}}       # labels as SVG text; no colour, no theme


class Block(NamedTuple):
    """One ```mermaid block: its file, its number in that file (from 1), its text, its caption, its lines. (A tuple, not a
    dataclass: scripts and tests load this file by its path, without a module of its name.)"""
    source: str
    n: int
    text: str
    caption: str | None
    first: int          # the line of the opening fence, from 0
    last: int           # the line of the closing fence (the last line, when the block is never closed)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def svg(self) -> str:
        return f"{OUT}/{slug(self.source)}-{self.n}.svg"


def slug(source: str) -> str:
    """A file's path as part of a file name: README.md -> readme, docs/submission/NUMBERS.md -> docs-submission-numbers."""
    return re.sub(r"[^a-z0-9]+", "-", source.lower().removesuffix(".md")).strip("-")


def parse(text: str, source: str) -> list[Block]:
    """The ```mermaid blocks of a Markdown page, in order. A block inside another fence (a page that shows how to write
    one) is not a diagram; neither is a fence of another language."""
    lines = text.splitlines(keepends=True)
    bare = [line.rstrip("\r\n") for line in lines]
    out: list[Block] = []
    i = 0
    while i < len(bare):
        m = FENCE.match(bare[i])
        if not m or (m.group(2)[0] == "`" and "`" in m.group(3)):
            i += 1
            continue
        mark, info = m.group(2), m.group(3).strip()
        j = i + 1
        while j < len(bare):
            c = FENCE.match(bare[j])
            if c and c.group(2)[0] == mark[0] and len(c.group(2)) >= len(mark) and not c.group(3).strip():
                break
            j += 1
        if info.split()[:1] == ["mermaid"]:
            k = j + 1
            while k < len(bare) and not bare[k].strip():
                k += 1
            cap = CAPTION.match(bare[k]) if k < len(bare) and j < len(bare) else None
            body = "".join(line + "\n" for line in bare[i + 1:j])
            out.append(Block(source, len(out) + 1, body, (cap.group("a") or cap.group("b")).strip() if cap else None,
                             i, min(j, len(bare) - 1)))
        i = j + 1
    return out


def swap(text: str, source: str, picture: Callable[[Block], str]) -> str:
    """The page with each ```mermaid block (its fences included) replaced by the line picture(block) gives."""
    lines = text.splitlines(keepends=True)
    for b in reversed(parse(text, source)):
        end = "\r\n" if lines[b.last].endswith("\r\n") else "\n"
        lines[b.first:b.last + 1] = [picture(b) + end]
    return "".join(lines)


def pages(root: Path = ROOT) -> list[str]:
    """README.md and every Markdown document under docs/, by their paths from the root."""
    found = ["README.md"] if (root / "README.md").is_file() else []
    if (root / "docs").is_dir():
        found += sorted(p.relative_to(root).as_posix() for p in (root / "docs").rglob("*.md") if p.is_file())
    return found


def blocks(root: Path = ROOT) -> list[Block]:
    return [b for rel in pages(root) for b in parse((root / rel).read_text(encoding="utf-8"), rel)]


def index(root: Path = ROOT) -> list[dict]:
    path = root / INDEX
    return json.loads(path.read_text(encoding="utf-8"))["diagrams"] if path.is_file() else []


def _entry(b: Block) -> dict:
    return {"source": b.source, "block": b.n, "sha256": b.sha256, "svg": b.svg}


def sized(svg: str) -> str:
    """mmdc's picture says width="100%" and a max-width: in an image tag that stretches a small diagram across the page.
    Its root element is given its viewBox's size instead."""
    m = re.search(r"<svg\b[^>]*>", svg)
    box = re.search(r'viewBox="\s*[-\d.e]+[\s,]+[-\d.e]+[\s,]+([\d.e]+)[\s,]+([\d.e]+)\s*"', m.group(0)) if m else None
    if not m or not box:
        return svg
    w, h = (math.ceil(float(x)) for x in box.groups())
    tag = re.sub(r'\s(?:width|height)="[^"]*"', "", m.group(0))
    tag = re.sub(r"max-width:\s*[\d.]+px;?\s*", "", tag)
    tag = tag.replace("<svg", f'<svg width="{w}" height="{h}"', 1)
    return svg[:m.start()] + tag + svg[m.end():]


def _write(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return True


def render(root: Path = ROOT, mmdc: Sequence[str] | None = None, puppeteer: str | None = None) -> tuple[list[str], list[str], list[str]]:
    """Draw every diagram whose text has no picture yet, delete the pictures of diagrams that are gone, write the index.
    Returns (pictures drawn, pictures deleted, diagrams mmdc could not draw). mmdc is looked for only when a diagram
    needs drawing."""
    want = blocks(root)
    old = {(e["source"], e["block"]): e for e in index(root)}
    drawn: list[str] = []
    failed: list[str] = []
    done: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for b in want:
            e = old.get((b.source, b.n))
            if e == _entry(b) and (root / b.svg).is_file():
                done.append(e)
                continue
            if mmdc is None:
                found = shutil.which("mmdc")
                if not found:
                    raise SystemExit("mmdc is not installed: npm install @mermaid-js/mermaid-cli, or pass --mmdc PATH")
                mmdc = [found]
            (work / "config.json").write_text(json.dumps(CONFIG), encoding="utf-8")
            (work / "in.mmd").write_text(b.text, encoding="utf-8")
            (work / "out.svg").unlink(missing_ok=True)
            cmd = [*mmdc, "-i", str(work / "in.mmd"), "-o", str(work / "out.svg"), "-b", "white", "-c", str(work / "config.json"), "-q"]
            ran = subprocess.run([*cmd, *(["-p", puppeteer] if puppeteer else [])], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            if ran.returncode or not (work / "out.svg").is_file():
                failed.append(f"{b.source}, diagram {b.n}: mmdc could not draw it: {(ran.stderr or ran.stdout).strip()[-400:]}")
                continue
            _write(root / b.svg, sized((work / "out.svg").read_text(encoding="utf-8")))
            drawn.append(b.svg)
            done.append(_entry(b))
    keep = {b.svg for b in want}
    gone = []
    for p in sorted((root / OUT).glob("*.svg")) if (root / OUT).is_dir() else []:
        if p.relative_to(root).as_posix() not in keep:
            p.unlink()
            gone.append(p.relative_to(root).as_posix())
    _write(root / INDEX, json.dumps({"about": ABOUT, "diagrams": done}, indent=1, ensure_ascii=False) + "\n")
    return drawn, gone, failed


def check(root: Path = ROOT) -> list[str]:
    """Every way the pictures disagree with the diagrams, one line each (none: they agree). Reads files only."""
    want = blocks(root)
    said = []
    have = {(e.get("source"), e.get("block")): e for e in index(root)}
    seen: dict[str, str] = {}
    for b in want:
        if b.svg in seen:
            said.append(f"{b.source} and {seen[b.svg]} have the same picture name {b.svg}: rename one of the files")
        seen[b.svg] = b.source
        if not b.caption:
            said.append(f"{b.source}, diagram {b.n}: no caption (one line in italics under the block)")
        if have.get((b.source, b.n)) != _entry(b):
            said.append(f"{b.source}, diagram {b.n}: no picture of this text (python scripts/diagrams.py render)")
        elif not (root / b.svg).is_file():
            said.append(f"{b.svg}: missing (python scripts/diagrams.py render)")
    now = {(b.source, b.n) for b in want}
    said += [f"{INDEX}: {e.get('svg')} is the picture of a diagram that is gone (python scripts/diagrams.py render)"
             for key, e in have.items() if key not in now]
    listed = {b.svg for b in want}                  # a picture of an older text of a diagram is said above
    if (root / OUT).is_dir():
        said += [f"{rel}: the picture of no diagram (python scripts/diagrams.py render deletes it)"
                 for rel in sorted(p.relative_to(root).as_posix() for p in (root / OUT).glob("*.svg")) if rel not in listed]
    return said


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A picture of every Mermaid diagram in README.md and docs/.")
    ap.add_argument("command", nargs="?", choices=["render", "check"], help="render: draw what changed; check: change nothing")
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 unless every diagram has its picture")
    ap.add_argument("--mmdc", help="the mermaid-cli program (default: mmdc on the PATH)")
    ap.add_argument("--puppeteer-config", help="a browser settings file, passed to mmdc as -p")
    a = ap.parse_args(argv)
    if a.check or a.command == "check":
        said = check()
        for line in said:
            print(line)
        print(f"{len(said)} problem(s)." if said else f"{len(blocks())} diagram(s), each with its picture.")
        return 1 if said else 0
    if a.command != "render":
        ap.error("say render or --check")
    drawn, gone, failed = render(mmdc=[a.mmdc] if a.mmdc else None, puppeteer=a.puppeteer_config)
    for line in failed:
        print(line)
    print(f"Drew {len(drawn)}, deleted {len(gone)}, left {len(blocks()) - len(drawn) - len(failed)} as they were"
          + (f", could not draw {len(failed)}." if failed else "."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
