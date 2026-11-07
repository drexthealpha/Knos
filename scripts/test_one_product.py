"""test_one_product, live and in the tree: one app, one front door, one line.

    python scripts/test_one_product.py <commit sha under test> <out file>

A crawl from the front door (same-site links, two levels, both hosts) finds exactly one app shell, knos.onrender.com/app/:
github.io/Knos/app.html sends an old link on, Render's /index.html and /paid answer 301. git grep finds the one line in all
8 places (front door, README's first line, the MCP server's instructions, the CLI's header, llms.txt, server.json, the agent
skill, pyproject.toml), and no older one-line description anywhere. `knos --help` shows the one flow's 4 headings in order.
git grep finds no run name or operator note in a tracked file (a pre-registered plan, fixed by its sha256, is named apart).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
ONE = "Knos carries research across the valley of death."
SITE, APP = "https://drexthealpha.github.io/Knos/", "https://knos.onrender.com"
PLACES = ("web/home.html", "README.md", "apps/wanted/knos_wanted/agent.py", "src/knos/cli.py", "web/llms.txt", "server.json",
          "web/.well-known/skills/knos/SKILL.md", "pyproject.toml")
OLDER = ("each step is paid only on verified proof", "Research to products people want", "neutral meter for AI agent work",
         "Checks who wants a product with Qloo taste data", "Run Knos before opening a pull request", "Pay AI agents only when your checks pass")
NOTES = r"CHAMPION[0-9]|TASK-CHAMPION|knos-goal|founder's account only|hackathon API|goal routine|TASK-ONE-KNOS"
FIXED = ("docs/reference/taste_truth_plan.md", "docs/reference/where_truth_plan.md")      # pre-registered, fixed by sha256
SHELL = re.compile(r'id="(v-home|view-home)"')
lines: list[str] = []
fails = 0


def ok(c: bool, what: str) -> None:
    global fails
    lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
    fails += not c


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            h = dict(attrs).get("href")
            if h:
                self.hrefs.append(h)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def get(url: str, follow: bool = True) -> tuple[int, str, str]:
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (one product crawl)"}), timeout=60) as r:
            return r.status, r.headers.get("Location") or "", r.read(3_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location") or "", ""
    except Exception:  # noqa: BLE001 - a page that does not answer is said as 0
        return 0, "", ""


def main(sha: str, out: str) -> int:
    dep = json.loads(subprocess.run(["gh", "api", "repos/drexthealpha/Knos/deployments?environment=github-pages&per_page=1"], capture_output=True, text=True).stdout)[0]
    ok(dep["sha"] == sha, f"Pages deployed at {dep['sha'][:7]} (commit under test {sha[:7]})")
    # the crawl
    seen, shells, queue = set(), [], [(SITE, 0), (APP + "/app/", 0)]
    while queue:
        url, depth = queue.pop(0)
        key = url.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        code, _loc, body = get(key)
        if SHELL.search(body):
            shells.append(key)
        if depth >= 2:
            continue
        p = Links()
        p.feed(body)
        for h in p.hrefs:
            u = urljoin(key, h).split("#")[0]
            host = urlparse(u).netloc
            if host in ("drexthealpha.github.io", "knos.onrender.com") and (host != "drexthealpha.github.io" or urlparse(u).path.startswith("/Knos/")) \
                    and not re.search(r"\.(json|csv|pdf|svg|png|xml|txt|js|css)$", urlparse(u).path) and "/auth/" not in u:
                queue.append((u, depth + 1))
    one = sorted(set(s.split("?")[0] for s in shells))
    ok(one == [APP + "/app/"], f"crawl of {len(seen)} pages: app shells at {one}")
    code, _l, body = get(SITE + "app.html")
    ok(code == 200 and "url=https://knos.onrender.com/app/" in body and not SHELL.search(body), f"github.io/Knos/app.html: {code}, a link on to the app")
    for path, to in (("/index.html", "/app/"), ("/paid", "/app/?all=1")):
        code, loc, _b = get(APP + path, follow=False)
        ok(code == 301 and loc == to, f"Render {path}: {code} to {loc}")
    # the one line, in the 8 places, and no older description
    for f in PLACES:
        text = (ROOT / f).read_text(encoding="utf-8")
        first = text.split("\n")[8] if f == "README.md" else text
        ok(ONE in first, f"the one line in {f}" + (" (its first line under the heading)" if f == "README.md" else ""))
    older = subprocess.run(["git", "-C", str(ROOT), "grep", "-nF", *sum((["-e", o] for o in OLDER), []), "--", ".", ":!CHANGELOG.md", ":!scripts/test_one_product.py"],
                           capture_output=True, text=True).stdout.strip()
    ok(not older, f"older one-line descriptions in the tree: {len(older.splitlines()) if older else 0}")
    # the live answers carry it too
    req = urllib.request.Request(APP + "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18",
                                 "capabilities": {}, "clientInfo": {"name": "test_one_product", "version": "1"}}}).encode(),
                                 {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    body = urllib.request.urlopen(req, timeout=60).read().decode()
    ok(json.loads(body[body.index("{"):])["result"]["instructions"].startswith(ONE), "the live MCP server's instructions open with the one line")
    # knos --help
    exe = ROOT / ".venv" / ("Scripts/knos.exe" if sys.platform == "win32" else "bin/knos")
    said = subprocess.run([str(exe), "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    at = [said.find(h) for h in ("Check demand", "Hold money", "Paid on proof", "Run Knos")]
    ok(all(a > 0 for a in at) and at == sorted(at) and ONE in " ".join(said.replace("│", " ").split()), f"knos --help: headings at {at}, the one line in its header")
    notes = subprocess.run(["git", "-C", str(ROOT), "grep", "-nE", NOTES, "--", ".", ":!scripts/test_one_product.py"], capture_output=True, text=True).stdout.strip().splitlines()
    loose = [n for n in notes if not n.startswith(FIXED)]
    ok(not loose, f"run names or operator notes in tracked files: {len(loose)}" + (f" ({loose[:3]})" if loose else "")
       + (f"; apart: {len(notes) - len(loose)} in a pre-registered plan fixed by its sha256 ({', '.join(sorted(set(n.split(':')[0] for n in notes if n.startswith(FIXED))))})" if len(notes) > len(loose) else ""))
    lines.append(f"FAIL test_one_product: {fails} check(s) failed" if fails else
                 f"PASS test_one_product: one app shell in a crawl of {len(seen)} pages, the one line in 8 of 8 places and 0 older descriptions, 4 headings in order, 0 run names")
    print("\n".join(lines))
    with open(out, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
