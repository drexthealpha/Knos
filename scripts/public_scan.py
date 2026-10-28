"""The words no public text of Knos may carry, counted over what a reader reads.

    python scripts/public_scan.py files            every tracked public file of the repository
    python scripts/public_scan.py site <dir>       a built Pages site (scripts/build_site.sh)
    python scripts/public_scan.py live             the live answers of the front door, the app, /status/qloo, /mcp
                                                   tools/list, /api/check and /api/ready

What a reader reads: prose files (.md, .html, .txt) with their scripts and styles taken out, the text values of JSON,
and the string literals with a space in them inside the site's and the app's JavaScript (what such code shows; a bare
identifier or a path is never shown). A page's raw HTML is also read for an inlined Qloo answer. Counts and places
only: a matched passage is never printed. Exit 1 on any hit.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS = {
    "escrow": r"(?<![\w.])escrow(?:s|ed)?\b", "em dash": "—", "marketplace": r"market ?places?", "Kickstarter": r"kickstarter",
    "Upwork": r"upwork", "Algora": r"algora", "hackathon": r"hackathons?", "contest": r"\bcontests?\b",
    "Devpost": r"devpost", "Colosseum": r"colosseum", "prize": r"\bprizes?\b", "judge": r"\bjudg(?:e|es|ed|ing)\b",
    "demo": r"\bdemos?\b",
}
QLOO_RAW = {
    "Qloo affinity number": r'"affinity"\s*:\s*-?\d|affinity[^<\n]{0,12}\b0\.\d{3,}',
    "Qloo audience name": r"\((?:Hobbies And Interests|Lifestyle Preferences|Life Stage|Communities|Professional Area|"
                          r"Global Issues|Investing Interests|Leisure|Political Preferences|Spending Habits)\)|urn:audience:",
    "k-proof snapshot": r"id=.k-proof['\"]",
}
IDEA = "DPI-I-689"
PROSE = {".md", ".html", ".txt"}
# never shown to a reader: code, tests, build and machine files, the program interfaces and the record of releases
SKIP_DIRS = ("tests/", "scripts/", "programs/", "programs-v2/", "programs-hook/", "crates/", "zk/", "idl/", "schemas/",
             ".github/", ".knos/", "deploy/upgrades/", "bench/", "sdk/settle/test/", "apps/wanted/tests/", "src/knos/")
JS_DIRS = ("web/", "apps/wanted/knos_wanted/static/")
STR = re.compile(r"""(?:"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`)""")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for k, v in attrs:
            if k in ("title", "alt", "aria-label", "placeholder", "content") and v:
                self.out.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, d):
        if not self._skip:
            self.out.append(d)


# HTMLParser's own callbacks, named here so a dead-code reader sees them used
_CALLBACKS = (_Text.handle_starttag, _Text.handle_endtag, _Text.handle_data)


def html_text(s: str) -> str:
    p = _Text()
    p.feed(s)
    return " ".join(p.out)


def json_values(o) -> list[str]:
    if isinstance(o, str):
        return [o]
    if isinstance(o, list):
        return [v for x in o for v in json_values(x)]
    if isinstance(o, dict):
        return [v for x in o.values() for v in json_values(x)]
    return []


def js_text(s: str) -> str:
    # a template's ${...}, an attribute value (class, id, href, data-*) and a selector are code, never shown as text
    lits = (re.sub(r"""\$\{[^}]*\}|[\w-]+=\\?"[^"]*"|\[[^\]]*\]""", " ", a or b or c) for a, b, c in STR.findall(s))
    return " ".join(t for t in lits if " " in t.strip())


def readable(path: str, raw: str) -> tuple[str, str]:
    """(the text a reader reads, the raw text searched for an inlined Qloo answer)"""
    ext = Path(path).suffix.lower()
    if ext == ".html":
        return html_text(raw), raw
    if ext == ".json":
        try:
            return " ".join(v for v in json_values(json.loads(raw)) if " " in v.strip()), raw
        except ValueError:
            return raw, raw
    if ext in (".js", ".mjs"):
        return js_text(raw), ""
    return raw, ""


def count(text: str, raw: str, path: str, pages: bool) -> dict[str, int]:
    text = re.sub(r"```.*?```|`[^`\n]*`", " ", text, flags=re.S)      # code in backticks: a command or a name, never prose
    # an all-capitals word is a constant's name, never prose
    hits = {k: sum(1 for m in re.finditer(rx, text, re.I) if not (m.group(0).isupper() and len(m.group(0)) > 1)) for k, rx in WORDS.items()}
    if pages:
        hits.update({k: len(re.findall(rx, raw)) for k, rx in QLOO_RAW.items()})
    allowed = 1 if path.replace("\\", "/").endswith("iris/README.md") else 0
    hits[IDEA] = max(0, text.count(IDEA) - allowed)
    return {k: v for k, v in hits.items() if v}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    keep = []
    for f in filter(None, out):
        if f.startswith(SKIP_DIRS) or f.startswith(".cache/"):
            continue
        ext = Path(f).suffix.lower()
        if ext in PROSE or (ext == ".json" and f.startswith(("web/", "docs/"))) or (ext in (".js", ".mjs") and f.startswith(JS_DIRS)):
            keep.append(f)
    return keep


def scan(items) -> tuple[int, list[str]]:
    total, lines = 0, []
    for name, raw, pages in items:
        text, rawq = readable(name, raw)
        hits = count(text, rawq, name, pages)
        if hits:
            total += sum(hits.values())
            lines.append(f"FAIL {name}: " + ", ".join(f"{v} {k}" for k, v in sorted(hits.items())))
    return total, lines


def files_items():
    for f in tracked():
        p = ROOT / f
        if p.is_file():
            yield f, p.read_text(encoding="utf-8", errors="replace"), f.startswith("web/")


def site_items(d: Path):
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".html", ".json", ".txt", ".js", ".md", ".xml"):
            yield str(p.relative_to(d)), p.read_text(encoding="utf-8", errors="replace"), True


def _get(url: str, data: bytes | None = None, ctype: str = "application/json") -> str:
    req = urllib.request.Request(url, data, {"Content-Type": ctype, "Accept": "application/json, text/event-stream, text/html",
                                             "User-Agent": "knos-public-scan"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def live_items():
    app, front = "https://knos.onrender.com", "https://drexthealpha.github.io/Knos/"
    for name, url in (("front door", front), ("/app/", app + "/app/"), ("/status/qloo", app + "/status/qloo")):
        yield name + ".html", _get(url), True
    tl = _get(app + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())
    yield "/mcp tools/list.json", tl, False
    for idea in ("a vegan ramen food truck", "a late night ramen spot"):
        yield f"/api/check {idea}.json", _get(app + "/api/check", json.dumps({"idea": idea}).encode()), False
    brief = json.loads((ROOT / "bench/idt/ready_example.json").read_text(encoding="utf-8")) if (ROOT / "bench/idt/ready_example.json").exists() else {
        "title": "a vegan ramen food truck", "milestones": [{"name": "Pilot", "target": "40 bowls sold in a week", "verifier": {"check": "sales"}, "deadline_days": 30}]}
    yield "/api/ready.json", _get(app + "/api/ready", json.dumps({"brief": brief}).encode()), False


PLAIN = [(r"\bJudges\b", "Referees"), (r"\bjudges\b", "referees"), (r"\bJudged\b", "Checked"), (r"\bjudged\b", "checked"),
         (r"\bJudging\b", "Checking"), (r"\bjudging\b", "checking"), (r"\bJudge\b", "Referee"), (r"\bjudge\b", "referee"),
         (r"\bdemo\b", "sample"), (r"\bDemo\b", "Sample")]


def plain(o):
    """A generated public file's words for a reader: the role that checks work is the referee. Text with a space only,
    so a code such as `judge.protected-path`, a key or a command keeps its name."""
    if isinstance(o, str):
        if " " not in o.strip():
            return o
        parts = o.split("`")
        for i in range(0, len(parts), 2):
            for a, b in PLAIN:
                parts[i] = re.sub(a, b, parts[i])
        return "`".join(parts)
    if isinstance(o, list):
        return [plain(x) for x in o]
    if isinstance(o, dict):
        return {k: plain(v) for k, v in o.items()}
    return o


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "files"
    items = {"files": files_items, "live": live_items}.get(mode)
    items = items() if items else site_items(Path(argv[2]))
    total, lines = scan(items)
    for line in lines:
        print(line)
    print(f"{'PASS' if not total else 'FAIL'} public_scan {mode}: {total} hits in {len(lines)} places")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
