"""The words no public text of Knos may carry, counted over what a reader reads.

    python scripts/public_scan.py files            every tracked public file of the repository
    python scripts/public_scan.py site <dir>       a built Pages site (scripts/build_site.sh)
    python scripts/public_scan.py live             the live answers of the front door, the app, /status/qloo, /mcp
                                                   tools/list, /api/check and /api/ready

What a reader reads: prose files (.md, .html, .txt) with their scripts and styles taken out, the text values of JSON,
and the string literals with a space in them inside the site's and the app's JavaScript (what such code shows; a bare
identifier or a path is never shown). A Markdown link's target is an address, never shown, so only its text is read.
A page's raw HTML is also read for an inlined Qloo answer. Counts and places only: a matched passage is never printed.
Exit 1 on any hit.

`files` skips the machine files of docs/MACHINE_FILES.txt (a line each: path, sha256, reason): signed receipt vectors,
JSON schemas, pinned plans and raw run files, whose text cannot change without breaking a signature, a hash or a pin.
A listed file that is missing or whose sha256 differs fails the scan. CHANGELOG.md's entries released before
2026-10-29 are the record of those releases and are skipped; its later entries are read.
"""
from __future__ import annotations

import datetime
import hashlib
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
MACHINE = "docs/MACHINE_FILES.txt"
CHANGELOG, EXEMPT_BEFORE = "CHANGELOG.md", datetime.date(2026, 10, 29)
# a Markdown link's target and a reference definition's address: where the link goes, not what a reader reads
MD_TARGET = re.compile(r"(\]\()[^)\n]*(\))|^(\s{0,3}\[[^\]\n]+\]:)\s*\S+", re.M)
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
    if ext == ".md":
        return MD_TARGET.sub(lambda m: (m.group(1) + m.group(2)) if m.group(1) else m.group(3), raw), ""
    return raw, ""


def machine_files() -> tuple[set[str], list[str]]:
    """(the paths docs/MACHINE_FILES.txt lists, a line for each listed file that is missing or whose sha256 differs)"""
    p = ROOT / MACHINE
    if not p.is_file():
        return set(), []
    listed, wrong = set(), []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 3 or not re.fullmatch(r"[0-9a-f]{64}", parts[1]):
            wrong.append(f"FAIL {MACHINE}:{n}: not `path sha256 reason`")
            continue
        rel, want = parts[0], parts[1]
        listed.add(rel)
        f = ROOT / rel
        if not f.is_file():
            wrong.append(f"FAIL {MACHINE}:{n}: {rel} is missing")
        elif hashlib.sha256(f.read_bytes()).hexdigest() != want:
            wrong.append(f"FAIL {MACHINE}:{n}: {rel} sha256 differs from the list")
    return listed, wrong


_DAY = re.compile(r"\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w* (\d{4})\b")


def _heading_days(path: str, rows: list[int]) -> dict[int, datetime.date]:
    """{line: the day the line was committed} for the given 1-based lines; a line not committed yet has no day."""
    out = subprocess.run(["git", "blame", "--line-porcelain", "--", path], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    days, line, want = {}, 0, set(rows)
    for row in out.stdout.split("\n") if out.returncode == 0 else []:
        head = re.match(r"([0-9a-f]{40}) \d+ (\d+)", row)
        if head:
            line = int(head.group(2)) if head.group(1).strip("0") else 0      # all zeros: not committed yet
        elif row.startswith("committer-time ") and line in want:
            days[line] = datetime.datetime.fromtimestamp(int(row.split()[1]), datetime.timezone.utc).date()
    return days


def changelog_new(raw: str, path: str = CHANGELOG) -> str:
    """CHANGELOG.md without its entries released before 2026-10-29. An entry is a `## ` heading and what follows; its day
    is the one its heading names (`0.3.11 (2 Oct 2026)`), else the day its heading was committed. The text above the
    first entry, and an entry not committed yet, are read."""
    lines = raw.split("\n")
    heads = [i for i, s in enumerate(lines) if s.startswith("## ")]
    if not heads:
        return raw
    blamed = _heading_days(path, [i + 1 for i in heads])
    keep = lines[:heads[0]]
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        m = _DAY.search(lines[i])
        day = (datetime.datetime.strptime(" ".join(m.groups()), "%d %b %Y").date() if m else blamed.get(i + 1))
        if day is None or day >= EXEMPT_BEFORE:
            keep += lines[i:end]
    return "\n".join(keep)


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
    skip = machine_files()[0]
    for f in tracked():
        p = ROOT / f
        if p.is_file() and f not in skip:
            raw = p.read_text(encoding="utf-8", errors="replace")
            yield f, (changelog_new(raw) if f == CHANGELOG else raw), f.startswith("web/")


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
    wrong = machine_files()[1] if mode == "files" else []
    for line in lines + wrong:
        print(line)
    ok = not total and not wrong
    print(f"{'PASS' if ok else 'FAIL'} public_scan {mode}: {total} hits in {len(lines)} places"
          + (f"; {len(wrong)} machine files do not match {MACHINE}" if wrong else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
