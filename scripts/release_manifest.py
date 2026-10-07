"""docs/MANIFEST.md: one page that ties a release together.

    python scripts/release_manifest.py            # write docs/MANIFEST.md
    python scripts/release_manifest.py --check    # exit 1 when the page is not what its sources give

The page says, for the release this tree is: its version and tag; for each program its public id, the build that is
LIVE at that id, the proposal that would replace it with its verified build hash and source commit; every proposal that
is pending; the stage of every capability with the evidence of that stage; and the limits that are still open.

Nothing on it is typed and nothing is assumed. Each part is read from the file that owns it:

    pyproject.toml                the version, and so the tag
    programs-v2/program_ids.json  the public program ids
    docs/capabilities.json        the version each public id runs (`programs.*.on_chain`), every capability's stage
    docs/provenance.json          the hash at each public id, from one read of the cluster
    web/upgrades.json             the proposals: build hash, source commit, verified-build run, status
    docs/DISCLOSURE.md            the limits, one line each ("## Outstanding limits")

No time is printed: when a proposal can execute is in web/upgrades.json and on chain, and a page that named it would be
false after it ran (scripts/doc_claims.py refuses such a sentence). No count of capabilities is printed either: the
rows are the count.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capabilities as cap  # noqa: E402
import provenance as prov  # noqa: E402

DOC = "docs/MANIFEST.md"
SENTENCE = "The neutral meter for AI agent work: neither side keeps the count."
REPO = "https://github.com/drexthealpha/Knos"
LIMITS = "## Outstanding limits"
TX = "https://explorer.solana.com/tx/{}?cluster=devnet"


def version(root: Path = ROOT) -> str:
    m = re.search(r'(?m)^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("pyproject.toml names no version")
    return m.group(1)


def _short(h: str | None) -> str:
    return f"`{h}`" if h else "not recorded"


def programs(data: dict) -> list[str]:
    """One row for each program: what the public id runs, as the records say, and the build that would replace it."""
    lines = ["| program | public program id | LIVE at that id | hash at that id | its proposal | the proposal's verified build hash | built from |",
             "|---|---|---|---|---|---|---|"]
    listed = data["capabilities"].get("programs", {})
    for c in prov.chains(data):
        e, now = c["entry"], c["now"] or {}
        same = bool(c["links"]["hash on chain"].get("same"))
        live = f"{c['program']} {c['runs']}" if c["runs"] else "not recorded"
        if e is None:
            proposal, built, source = "none", "none", "none"
        else:
            proposal = f"{e.get('index')}: {e.get('status')}" + ("" if same or e.get("status") != "executed" else ", and the hash read is not its build")
            built = _short(e.get("build_hash"))
            run = f", run `{e['gate_run']}`" if e.get("gate_run") else ""
            source = f"[`{str(e.get('source_commit'))[:7]}`]({REPO}/commit/{e.get('source_commit')}){run}" if e.get("source_commit") else "not recorded"
        hash_now = _short(now.get("hash")) + (" (the proposal's build)" if same else " (not the proposal's build)" if e and now.get("hash") else "")
        lines.append(f"| {c['program']} | `{c['address']}` | {live} | {hash_now} | {proposal} | {built} | {source} |")
    for name, p in listed.items():                                     # a program with no upgrade chain (upgrade_gate)
        if name not in prov.PROGRAMS:
            lines.append(f"| {name} | `{p.get('id')}` | {name} {p.get('on_chain')} | not read | none | none | none |")
    return lines


def pending(data: dict) -> list[str]:
    entries = sorted((e for e in data["upgrades"].get("entries", []) if e.get("status") == "pending"), key=lambda e: int(e.get("index", 0)))
    if not entries:
        return ["None: web/upgrades.json lists no pending proposal."]
    lines = ["| proposal | program | would deploy build | approvals |", "|---|---|---|---|"]
    lines += [f"| {e.get('index')} (`{e.get('proposal')}`) | {e.get('program')} | `{e.get('build_hash')}` | {e.get('approved')} of {e.get('threshold')} |"
              for e in entries]
    return lines


def evidence(c: dict) -> str:
    """The evidence of a capability's own stage, and of no other: one link."""
    ev, stage = c.get("evidence") or {}, c["stage"]
    got = ev.get(stage) if stage else None
    if not got:
        return "none: not built"
    if stage == "implemented":
        return f"[`{got['path']}`](../{got['path']})"
    if stage == "tested":
        return f"[`{got['test']}`](../{got['test']})"
    if stage == "deployed":
        return f"`{got['program']} {got['version']}` at its public id"
    if stage == "exercised":
        return f"[{got['signature'][:8]}...]({TX.format(got['signature'])})"
    return f"[outside run]({got['url']})" if got.get("url") else f"[`{got['file']}`](../{got['file']})"


def stage_of(c: dict, root: Path = ROOT) -> str:
    return cap.WORDS[c["stage"]] + (", on staging program ids" if c["stage"] == "exercised" and cap.ids_of(c, root) == "staging" else "")


def capabilities(data: dict, root: Path = ROOT) -> list[str]:
    lines = ["| capability | stage | evidence of that stage |", "|---|---|---|"]
    lines += [f"| `{c['id']}` | {stage_of(c, root)} | {evidence(c)} |" for c in data["capabilities"].get("capabilities", [])]
    return lines


def limits(root: Path = ROOT) -> list[str]:
    """The lines of docs/DISCLOSURE.md's "Outstanding limits": each is one list item on one line."""
    text = (root / "docs" / "DISCLOSURE.md").read_text(encoding="utf-8")
    if LIMITS not in text:
        raise SystemExit(f'docs/DISCLOSURE.md has no "{LIMITS}" section')
    body = text.split(LIMITS, 1)[1].split("\n## ", 1)[0]
    got = [line for line in body.splitlines() if line.startswith("- ")]
    if not got:
        raise SystemExit(f'"{LIMITS}" in docs/DISCLOSURE.md lists nothing')
    return got


def render(root: Path = ROOT) -> str:
    data, v = prov.load(root), version(root)
    feed = data["upgrades"]
    parts = [
        f"# Release manifest: Knos {v}", "", f"**{SENTENCE}**", "",
        "One page for this release: the source, the bytes each public program id runs, every capability's stage, and the",
        "limits still open. `python scripts/release_manifest.py` writes it from the files named under each heading, and",
        "`--check` fails when it differs from them. Nothing here is typed by hand, and no time is printed.", "",
        "## Source", "",
        f"- Release: Knos {v} (`pyproject.toml`). Tag: [`v{v}`]({REPO}/tree/v{v}); `git rev-list -n 1 v{v}` prints its commit. A file",
        "  cannot hold the hash of the commit that holds it.",
        "- Cluster: Solana devnet. The money is test USDC. Mainnet is not touched.", "",
        "## Programs: what is live at each public id", "",
        "Read from `docs/capabilities.json` (`programs`), `docs/provenance.json` (one read of the cluster; its `read` says",
        "when) and `web/upgrades.json` (the multisig's accounts; its `generated` says when). A proposal that is pending has",
        "not run: the public id runs the build in the third column until it does.", "",
        *programs(data), "",
        "A program whose source changed after its proposal's commit has no verified build hash on this page until the",
        "`verified-build` job has built it and a new proposal names it: `git diff <built from> -- programs-v2/<program>`",
        "shows whether it changed. Each link of each chain is in [PROVENANCE.md](PROVENANCE.md).", "",
        "## Pending proposals", "",
        f"Upgrade multisig `{feed.get('multisig', 'not recorded')}`, {feed.get('threshold', '?')} of {feed.get('members', '?')}. From `web/upgrades.json`; when each can",
        "execute is its `earliest_execution_utc` there.", "",
        *pending(data), "",
        "## Capabilities: the stage of each, with its evidence", "",
        "From `docs/capabilities.json`. A stage is the highest that has evidence; deployed and exercised count only at the",
        "public program ids. The note of each capability and every lower stage's evidence are in",
        "[CAPABILITIES.md](CAPABILITIES.md).", "",
        *capabilities(data, root), "",
        "## Outstanding limits", "",
        "From [DISCLOSURE.md](DISCLOSURE.md), one line each.", "",
        *limits(root), "",
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None, say: Callable[[str], None] = print, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when docs/MANIFEST.md is not what its sources give")
    a = ap.parse_args(argv)
    page, want = root / DOC, render(root)
    if a.check:
        if not page.is_file() or page.read_text(encoding="utf-8") != want:
            say(f"{DOC} is stale: run python scripts/release_manifest.py")
            return 1
        say(f"{DOC} is what its sources give")
        return 0
    page.write_text(want, encoding="utf-8", newline="")
    say(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
