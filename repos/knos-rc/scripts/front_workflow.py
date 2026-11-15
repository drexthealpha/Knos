"""Keep the workflow files the site hands out identical to the examples.

    python scripts/front_workflow.py           # rewrite the templates in web/front.js from examples/
    python scripts/front_workflow.py --check   # exit 1 if they differ (the test suite runs this)

web/front.js carries examples/knos-workflow.yml (WORKFLOW) and examples/knos-check.yml (CHECK_WORKFLOW) as template
literals: what a repository installs from the site is the example, byte for byte, with the commit of
drexthealpha/knos-workflows the example names. Until a release the examples carry a placeholder in its place;
`python scripts/pinned_workflows.py stamp <sha>` puts the commit into the examples and writes the page again through
this script, so the site never names a commit the examples do not. web/install.js (install by pull request) carries
examples/knos-install.yml (INSTALL_WORKFLOW), examples/knos-attestor.yml without its comment lines (ATTESTOR_WORKFLOW:
with them the file does not fit in a link) and examples/terms/*.json (TERMS, one line), written the same way; after
`stamp`, run this script once more so that page names the new commit too. A page that declares
`export const KNOS_WORKFLOWS_SHA = "...";` is given the same value: the commit, for any other place the page shows it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "web" / "front.js"
TEMPLATES = {"WORKFLOW": "knos-workflow.yml", "CHECK_WORKFLOW": "knos-check.yml"}
INSTALL = ROOT / "web" / "install.js"
PIN = re.compile(r"drexthealpha/knos-workflows/\.github/workflows/[\w.-]+@(\S+)")


def literal(text: str) -> str:
    """The file as the body of a JavaScript template literal that evaluates to exactly the file."""
    return text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def pin(texts: list[str]) -> str:
    """The one commit of drexthealpha/knos-workflows (or the placeholder) every example names."""
    named = {ref for text in texts for ref in PIN.findall(text)}
    if len(named) != 1:
        raise SystemExit(f"the examples must name drexthealpha/knos-workflows at one commit; they name {sorted(named) or 'none'}")
    return named.pop()


def rewritten(js: str) -> str:
    texts = {name: (ROOT / "examples" / example).read_text(encoding="utf-8") for name, example in TEMPLATES.items()}
    for name, text in texts.items():
        pat = re.compile(r"(export const " + name + r" = `).*?(`;\n)", re.DOTALL)
        if not pat.search(js):
            raise SystemExit(f"web/front.js has no `export const {name}` template")
        js = pat.sub(lambda m, body=literal(text): m.group(1) + body + m.group(2), js, count=1)
    commit = pin(list(texts.values()))
    return re.sub(r'(export const KNOS_WORKFLOWS_SHA = ")[^"\n]*(";)', lambda m: m.group(1) + commit + m.group(2), js, count=1)


def bare(text: str) -> str:
    """A workflow file without its comment lines and blank lines, under one line that says where the comments are."""
    kept = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return "# .github/workflows/knos-attestor.yml, without its comments: read them in examples/knos-attestor.yml of drexthealpha/Knos\n" + "\n".join(kept) + "\n"


def install_rewritten(js: str) -> str:
    """web/install.js with its two files and the terms templates as the examples have them."""
    read = lambda rel: (ROOT / "examples" / rel).read_text(encoding="utf-8")      # noqa: E731
    for name, text in (("INSTALL_WORKFLOW", read("knos-install.yml")), ("ATTESTOR_WORKFLOW", bare(read("knos-attestor.yml")))):
        pat = re.compile(r"(export const " + name + r" = `).*?(`;\n)", re.DOTALL)
        if not pat.search(js):
            raise SystemExit(f"web/install.js has no `export const {name}` template")
        js = pat.sub(lambda m, body=literal(text): m.group(1) + body + m.group(2), js, count=1)
    terms = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "examples" / "terms").glob("*.json"))]
    line = json.dumps(terms, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    if not re.search(r"^export const TERMS = .*;$", js, re.M):
        raise SystemExit("web/install.js has no `export const TERMS` line")
    return re.sub(r"^export const TERMS = .*;$", lambda m: f"export const TERMS = {line};", js, count=1, flags=re.M)


def main(argv: list[str] | None = None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    stale = 0
    for page, make in ((FRONT, rewritten), (INSTALL, install_rewritten)):
        if not page.exists() and page != FRONT:
            continue
        js = page.read_text(encoding="utf-8")
        new = make(js)
        if new == js:
            continue
        if check:
            print(f"web/{page.name} does not match examples/: run python scripts/front_workflow.py")
            stale = 1
            continue
        page.write_text(new, encoding="utf-8", newline="\n")
        print(f"web/{page.name} updated from examples/")
    return stale


if __name__ == "__main__":
    sys.exit(main())
