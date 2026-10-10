"""Every description of Knos that leaves the repository says one sentence, from one source.

    python scripts/public_face.py --check     # exit 1 when a file describes the product in any other words
    python scripts/public_face.py --write     # rewrite each description this script can write from the source
    python scripts/public_face.py --remote    # needs the network: what a logged-out reader is served, and the fix for each

The source is `sentence` in docs/facts.json. The places (`FACES`):

    pyproject.toml                          `description`: what PyPI shows as the summary        exactly the sentence
    server.json, gemini-extension.json      what the MCP registry and Gemini CLI list            exactly the sentence
    plugin manifests, the marketplace file  what Claude Code and Codex list                      begins with the sentence
    web/index.html                          <title>, meta description, og:title, og:description  the title; begins with it
    README.md                               the first line of text                               the sentence, in bold
    action.yml, the SDK, the crates         a description of a PART (the check, a client)        names no older product
    sdk/*/README.md                         what npm shows on the client's page                  names no older product

A place that describes a part of Knos keeps its own words, and may not carry a sentence of an older product (`STALE`),
nor a word no Knos document uses (scripts/truth_check.py `ALWAYS`, `MONEY_WORDS`, `MONEY_ABBR`). Every `version` a
manifest gives a registry (server.json twice, gemini-extension.json, the plugin manifests, sdk/*/package.json) is
pyproject.toml's, and an SDK README that names a release to install names that one (`v0.3.21`, `knos-settle-0.3.21`):
a registry or a cached page that shows an older number is an old copy. The crates are left out: they stay at 0.3.14.
`--remote` reads the repository's About (description, homepage, topics), PyPI's summary of `knos` and of the old
package `knos-hermes`, the MCP registry and glama.ai, and prints the command or the step that corrects each one. It
changes nothing: it has no credentials and asks for none.
"""

from __future__ import annotations

import argparse
import functools
import glob
import html as _html
import importlib.util
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "docs/facts.json"
KEY = "sentence"
REPO = "drexthealpha/Knos"
SITE = "https://drexthealpha.github.io/Knos/"
SERVER = "io.github.drexthealpha/knos"
# the repository's topics as GitHub lists them: what Knos is and what it serves (docs/X402.md, server.json)
TOPICS = ("ai-agents", "coding-agents", "metering", "invoice-reconciliation", "oidc", "github-actions", "solana", "escrow", "mcp",
          "mcp-server", "x402")
STALE = ("Bounties that pay", "Paid GitHub bounties", "Hire any AI agent", "shared memory", "local memory", "memory every coding agent",
         "memory for every coding agent", "memory for coding agents")

EXACT, BEGINS, PART = "exactly the sentence", "begins with the sentence", "names no older product"
JSON_FACES: tuple[tuple[str, str], ...] = (
    ("server.json", EXACT), ("gemini-extension.json", EXACT),
    ("plugin/.claude-plugin/plugin.json", BEGINS), ("plugin/.codex-plugin/plugin.json", BEGINS), (".claude-plugin/marketplace.json", BEGINS),
    ("sdk/settle/package.json", PART),
)
TOML_FACES: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", EXACT), ("crates/knos-oidc-interface/Cargo.toml", PART), ("crates/knos-pay-interface/Cargo.toml", PART),
)
_TOML = re.compile(r'(?m)^description = "((?:[^"\\]|\\.)*)"')
_YAML = re.compile(r"(?m)^description: (.*)$")
_JSON = re.compile(r'(?m)^(\s*"description": )"((?:[^"\\]|\\.)*)"')


@functools.lru_cache(maxsize=1)
def _truth() -> Any:
    """scripts/truth_check.py, for its list of words no document uses."""
    spec = importlib.util.spec_from_file_location("truth_check_words", Path(__file__).resolve().parent / "truth_check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                             # its dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


def banned(text: str) -> str | None:
    """The first word in `text` that no Knos description may use, or None."""
    tc = _truth()
    m = tc.ALWAYS.search(text) or tc.MONEY_WORDS.search(text) or tc.MONEY_ABBR.search(text)
    return m.group(0) if m else None


def release(root: Path = ROOT) -> str | None:
    m = re.search(r'(?m)^version = "([\d.]+)"', (root / "pyproject.toml").read_text(encoding="utf-8")) if (root / "pyproject.toml").is_file() else None
    return m.group(1) if m else None


def version_problems(root: Path = ROOT) -> list[str]:
    """A manifest's version, or a version an SDK README installs, that is not pyproject.toml's."""
    want, out = release(root), list[str]()
    if not want:
        return out
    for rel, _rule in JSON_FACES:
        path = root / rel
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        got = [("version", data.get("version"))] + [(f"packages[{i}].version", p.get("version")) for i, p in enumerate(data.get("packages") or [])]
        out += [f"{rel}: {key} is {v}, and pyproject.toml is {want}" for key, v in got if v is not None and v != want]
    for rel in _readmes(root):
        for m in re.finditer(r"(?:/v|@v|knos-settle-)(\d+\.\d+\.\d+)\b", (root / rel).read_text(encoding="utf-8")):
            if m.group(1) != want:
                out.append(f"{rel}: installs {m.group(0)}, and pyproject.toml is {want}")
    return out


def _readmes(root: Path) -> list[str]:
    return sorted(Path(p).relative_to(root).as_posix() for p in glob.glob(str(root / "sdk" / "*" / "README.md")))


def sentence(root: Path = ROOT) -> str:
    path = root / SOURCE
    got = json.loads(path.read_text(encoding="utf-8")).get(KEY) if path.is_file() else None
    if not isinstance(got, str) or not got.strip():
        raise SystemExit(f'{SOURCE} has no "{KEY}": the one sentence every description comes from')
    return got.strip()


# The line under the sentence on the site's first screen and the README's (tests/test_bench_docs.py): what a person
# searching reads first, so it is the title (60 characters at most: tests/test_seo.py).
OUTCOME = "Pay AI agents only when your checks pass."


def title(said: str) -> str:
    """The site's title: the name, then the line under the sentence on the first screen (tests/web/site.mjs holds the
    page to the same words). The descriptions begin with the sentence `said` itself."""
    return "Knos. " + OUTCOME


def _judge(where: str, got: str | None, rule: str, said: str) -> list[str]:
    if got is None:
        return [f"{where}: no description"]
    stale = [s for s in STALE if s.lower() in got.lower()]
    if stale:
        return [f'{where}: describes an older product ("{stale[0]}"): {got[:90]}']
    if word := banned(got):
        return [f'{where}: uses "{word}", which no Knos description uses: {got[:90]}']
    if rule == EXACT and got != said:
        return [f"{where}: is not the sentence: {got[:90]}"]
    if rule == BEGINS and not got.startswith(said):
        return [f"{where}: does not begin with the sentence: {got[:90]}"]
    return []


def _meta(html: str, attr: str, name: str) -> str | None:
    m = re.search(rf'<meta {attr}="{re.escape(name)}" content="([^"]*)"', html)
    return m.group(1) if m else None


def problems(root: Path = ROOT) -> list[str]:
    said, out = sentence(root), []
    for rel, rule in JSON_FACES:
        if (root / rel).is_file():
            out += _judge(rel, json.loads((root / rel).read_text(encoding="utf-8")).get("description"), rule, said)
    for rel, rule in TOML_FACES:
        if (root / rel).is_file():
            m = _TOML.search((root / rel).read_text(encoding="utf-8"))
            out += _judge(rel, m.group(1) if m else None, rule, said)
    if (root / "action.yml").is_file():
        m = _YAML.search((root / "action.yml").read_text(encoding="utf-8"))
        out += _judge("action.yml", m.group(1) if m else None, PART, said)
    page = root / "web" / "index.html"
    if page.is_file():
        html = page.read_text(encoding="utf-8")
        t = re.search(r"<title>([^<]*)</title>", html)
        for where, got, want in (("<title>", t.group(1) if t else None, title(said)), ("og:title", _meta(html, "property", "og:title"), title(said))):
            if got != want:
                out.append(f'web/index.html {where}: is "{got}", and the source gives "{want}"')
        for attr, name in (("name", "description"), ("property", "og:description"), ("name", "twitter:description")):
            got = _meta(html, attr, name)
            if got is not None or name != "twitter:description":
                out += _judge(f"web/index.html {name}", got, BEGINS, said)
    for rel in _readmes(root):
        out += _judge(rel, (root / rel).read_text(encoding="utf-8"), PART, said)
    out += version_problems(root)
    readme = root / "README.md"
    if readme.is_file():
        first = next((line.strip() for line in _prose(readme.read_text(encoding="utf-8"))), "")
        if first != f"**{said}**":
            out.append(f"README.md: the first line of text is not the sentence in bold: {first[:90]}")
    return out


def _prose(text: str):
    """The lines of a README a reader reads: not the HTML block that draws the wordmark, not a badge row, not a blank."""
    inside = 0
    for line in text.splitlines():
        s = line.strip()
        opened, closed = len(re.findall(r"<(?!/)(?:h1|picture|p|div)\b", s)), len(re.findall(r"</(?:h1|picture|p|div)>", s))
        if inside or opened or s.startswith(("<", "[![", "![")) or not s:
            inside += opened - closed
            continue
        yield s


def write(root: Path = ROOT) -> list[str]:
    """Rewrite what can be rewritten in place: the JSON and TOML descriptions that must be, or begin with, the sentence."""
    said, done = sentence(root), []
    for rel, rule in JSON_FACES + TOML_FACES:
        path = root / rel
        if rule == PART or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        rx = _JSON if rel.endswith(".json") else _TOML

        def put(m: re.Match[str], rule: str = rule, rel: str = rel) -> str:
            old = json.loads('"' + m.group(m.lastindex or 1) + '"')
            if rule == BEGINS and old.startswith(said):
                return m.group(0)
            new = said if rule == EXACT else (said + " " + _tail(old)).strip()
            text = json.dumps(new, ensure_ascii=False)
            return f"{m.group(1)}{text}" if rel.endswith(".json") else f"description = {text}"

        new_text = rx.sub(put, text, count=1)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8", newline="")
            done.append(rel)
    return done


def _tail(old: str) -> str:
    """What a longer description keeps after the sentence: its own sentences, without any that describe an older product."""
    kept = [s for s in re.split(r"(?<=[.!?])\s+", old) if s and not any(x.lower() in s.lower() for x in STALE)
            and not s.startswith("Attested by a GitHub-signed")]
    return " ".join(kept)


# ---- what a logged-out reader is served


def _get(url: str) -> Any:
    """JSON as parsed; a page served as HTML as {"_html": its text} (glama.ai's API asks for a key: its page does not)."""
    req = urllib.request.Request(url, headers={"Accept": "application/json, text/html;q=0.9", "User-Agent": "knos-public-face"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - fixed https hosts below
        body = r.read().decode("utf-8", "replace")
        if "html" in (r.headers.get("Content-Type") or ""):
            return {"_html": body}
        return json.loads(body)


def meta_description(page: str) -> str | None:
    """The <meta name="description"> of a page, its attributes in either order, entities decoded; None when it has none."""
    for tag in re.findall(r"<meta\b[^>]*>", page, flags=re.I):
        if re.search(r"""\bname\s*=\s*["']description["']""", tag, flags=re.I):
            m = re.search(r"""\bcontent\s*=\s*(?:"([^"]*)"|'([^']*)')""", tag, flags=re.I)
            if m:
                return _html.unescape(m.group(1) if m.group(1) is not None else m.group(2))
    return None


def remote(said: str, fetch: Callable[[str], Any] = _get) -> list[dict]:
    """One row for each place: where, what it says, whether that is the sentence, and how to correct it."""
    rows: list[dict] = []

    def ask(url: str) -> Any:
        try:
            return fetch(url)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {"_error": str(e)}

    def row(where: str, got: Any, fix: str, ok: bool | None = None) -> None:
        text = got if isinstance(got, str) or got is None else json.dumps(got)
        rows.append({"where": where, "says": text, "ok": (text == said) if ok is None else ok, "fix": fix})

    repo = ask(f"https://api.github.com/repos/{REPO}")
    if "_error" in repo:
        row("GitHub About", None, f"could not be read: {repo['_error']}", ok=False)
    else:
        topics = list(repo.get("topics") or [])
        adds = " ".join(f"--add-topic {t}" for t in TOPICS if t not in topics)
        drops = " ".join(f"--remove-topic {t}" for t in topics if t not in TOPICS)
        row("GitHub About: description", repo.get("description"), f'gh repo edit {REPO} --description "{said}"')
        row("GitHub About: homepage", repo.get("homepage") or None, f"gh repo edit {REPO} --homepage {SITE}", ok=repo.get("homepage") == SITE)
        row("GitHub About: topics", topics, f"gh repo edit {REPO} {adds} {drops}".strip(), ok=not adds and not drops)
    for package, fix in (("knos", "PyPI shows the summary of the newest upload and it cannot be edited: `python scripts/release.py publish` "
                                  "(docs/RELEASE.md) uploads this version, whose pyproject description is the sentence"),
                         ("knos-hermes", "the old package: upload one last version whose summary is \"Renamed: install knos. " + said
                                         + "\", or yank its releases at https://pypi.org/manage/project/knos-hermes/releases/")):
        got = ask(f"https://pypi.org/pypi/{package}/json")
        info = got.get("info") or {}
        if "_error" in got:
            row(f"PyPI: {package}", None, f"could not be read ({got['_error']}); {fix}", ok=False)
        else:
            summary = info.get("summary")
            row(f"PyPI: {package} {info.get('version')}", summary, fix, ok=summary == said or (package != "knos" and said in str(summary)))
    got = ask(f"https://registry.modelcontextprotocol.io/v0/servers?search={SERVER}")
    listed = got.get("servers", []) if "_error" not in got else []          # each: {"server": {...}, "_meta": {...}}
    fix = "the `registry` job of release.yml publishes server.json on the tag; by hand: `mcp-publisher login github && mcp-publisher publish`"
    if not listed:
        row("MCP registry", None, f"not listed or not read ({got.get('_error', 'no entry')}); {fix}", ok=False)
    for entry in listed:
        s = entry.get("server", entry)
        latest = (entry.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {}).get("isLatest")
        if latest is not False:                                           # an older version is not what a reader is served
            row(f"MCP registry: {s.get('name')} {s.get('version')}", s.get("description"), fix)
    # glama.ai's API answers 401 without a key (seen 7 October 2026), so the listing's own page is read, logged out
    got = ask(f"https://glama.ai/mcp/servers/{REPO}")
    desc = None if "_error" in got else meta_description(str(got.get("_html", "")))
    row("glama.ai", desc,
        "glama.ai indexes the repository's README by itself: the maintainer named in glama.json signs in at "
        f"https://glama.ai/mcp/servers/{REPO} and edits the description, or asks for a re-index",
        ok=desc is not None and said in desc)
    return rows


def main(argv: list[str] | None = None, say: Callable[[str], None] = print, root: Path = ROOT, fetch: Callable[[str], Any] = _get) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 when a file describes the product in other words (the default)")
    mode.add_argument("--write", action="store_true", help="rewrite the descriptions from docs/facts.json")
    mode.add_argument("--remote", action="store_true", help="read what a logged-out reader is served; needs the network")
    a = ap.parse_args(argv)
    said = sentence(root)
    if a.remote:
        rows = remote(said, fetch)
        for r in rows:
            say(f"{'same' if r['ok'] else 'STALE'}  {r['where']}: {r['says'] if r['says'] is not None else 'nothing'}")
            if not r["ok"]:
                say(f"      fix: {r['fix']}")
        stale = sum(1 for r in rows if not r["ok"])
        say(f"{stale} of {len(rows)} places do not say: {said}" if stale else f"all {len(rows)} places say: {said}")
        return 1 if stale else 0
    if a.write:
        for rel in write(root):
            say(f"wrote {rel}")
    found = problems(root)
    for p in found:
        say(p)
    say(f"{len(found)} description(s) are not the one sentence" if found else f"every description says: {said}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
