"""List each tracked top-level entry of the repository with the workflows, tests, pages and build files that name it.

    python scripts/top_level.py            # every entry, its reference count and up to three referring files
    python scripts/top_level.py --orphans  # only the entries nothing names; exits 1 when there is one

An entry counts as used when a tracked file outside itself (and outside the copies in repos/) writes a path that starts
with it, or the file's whole name: a workflow, a test, a script, the
package, the site, the app, the NEAR code, the build and packaging files, or a document a reader is sent to. The
repository's own files that GitHub, git, pip or a licence reader look for by name are used by definition (KNOWN).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Read by a tool by its name, not named in another file: GitHub, git, pip, the licence and security readers.
KNOWN = {".github", ".gitignore", ".gitattributes", "LICENSE", "README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
         "SECURITY.md", "CODEOWNERS", "pyproject.toml", "uv.lock", "CHANGELOG.md", "CLAUDE.md", "action.yml"}


# folders of copies (the small repositories and their fixtures): a name they write is not a use by this repository
ARCHIVE = {"repos"}


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p and (ROOT / p).exists()]


def entries(files: list[str]) -> list[str]:
    return sorted({f.split("/", 1)[0] for f in files})


def references(files: list[str]) -> dict[str, list[str]]:
    tops = entries(files)
    dirs = {f.split("/", 1)[0] for f in files if "/" in f}
    names = sorted(tops, key=len, reverse=True)
    # a folder counts when a path starts with it ("near/", "./near/"); a file when its whole name is written
    alts = [re.escape(t) + ("/" if t in dirs else r"(?![\w.-])") for t in names]
    pat = re.compile(r"(?:(?<![\w./-])|(?<=\./))(" + "|".join(alts) + ")")
    refs: dict[str, list[str]] = {t: [] for t in tops}
    for f in files:
        own = f.split("/", 1)[0]
        if own in ARCHIVE:
            continue
        p = ROOT / f
        try:
            if p.stat().st_size > 2_000_000:
                continue
            text = p.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for t in {m.rstrip("/") for m in pat.findall(text)}:
            if t != own:
                refs[t].append(f)
    return refs


def main(argv: list[str]) -> int:
    files = tracked()
    refs = references(files)
    orphans = [t for t, r in refs.items() if not r and t not in KNOWN]
    print(f"top-level entries: {len(refs)}")
    if "--orphans" in argv:
        for t in orphans:
            print(t)
        return 1 if orphans else 0
    for t, r in refs.items():
        tag = "known" if t in KNOWN and not r else str(len(r))
        print(f"{t}\t{tag}\t{', '.join(r[:3])}")
    print(f"named by nothing: {len(orphans)}" + (f" ({', '.join(orphans)})" if orphans else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
