"""terms/: the published terms templates, each a file a contract can cite by hash (docs/TERMS.md, "Knos Terms 1").

    python scripts/terms_registry.py build             publish what src/knos/terms_templates.py holds and terms/ does not
    python scripts/terms_registry.py build --check     exit 1 when terms/ is not what `build` would leave, or a published file changed
    python scripts/terms_registry.py verify <file|hash>   which published template and version it is, or "not a published template"
    python scripts/terms_registry.py cite <name> [version]   the sentence a contract carries, and the file's address

    terms/<name>/<version>.json    one published version: the comment, the terms, their canonical bytes and sha256
    terms/index.json               every version: name, version, hash, the one sentence, and the sha256 of its file

A published version never changes. `build` never writes a file that terms/index.json already lists: when a template in
the code funds other terms, or is posted with another comment, than its newest published version, `build` adds the
next version beside it. `check` reads every listed file again and holds its bytes to the sha256 the index recorded
when it was published, so an edit to a published file fails the tests instead of passing as the same version.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knos import terms, terms_templates as tt  # noqa: E402
from knos.terms_registry import (  # noqa: E402,F401  (what reads the registry lives in the package: `knos terms cite` needs it)
    NOT_PUBLISHED, SITE, STANDARD, Changed, check, cite, is_hash, latest, load, said, sentence, verify,
)

DIR = ROOT / "terms"


def _dump(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=True) + "\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def trust(name: str) -> dict:
    """What a template's acceptance rests on: how the work is judged and how many judges must agree.
    `judge` is "merge" (a maintainer's merge, after the named checks), or one of knos.terms.ASSURANCE's three:
    "hermetic" when the terms pin an image, else "black-box", the suite the template's own sentence names."""
    t = tt.get(name)
    cmd, tm = tt.command(t), tt.terms_of(t)
    judge = "merge" if tm["mode"] == "merge" else terms.assurance(tm, black_box=True)
    return {"judge": judge, "quorum": int(getattr(cmd, "quorum", None) or 1), "checks": [c["name"] for c in tm["checks"]]}


def instance(name: str, version: int) -> dict:
    """What terms/<name>/<version>.json holds when the code's template is published as that version."""
    got = tt.export(name)
    return {"standard": STANDARD, "name": name, "version": version, "sentence": got["sentence"], "comment": got["comment"],
            "where": got["where"], "trust": trust(name), "terms": got["terms"], "terms_json": got["terms_json"],
            "terms_hash": got["terms_hash"], "assumes": got["assumes"], "cite": sentence(name, version, got["terms_hash"])}


def plan(root: Path = DIR) -> tuple[list[dict], dict[str, str]]:
    """(the index's rows after a build, {relative path: text} of the files that build would add). A template is
    published again, as the next version, when its terms or its comment are not its newest published version's."""
    rows = check(root)
    new: dict[str, str] = {}
    newest = latest(rows)
    for name in tt.TEMPLATES:
        got = tt.export(name)
        have = newest.get(name)
        if have and (have["hash"], have["comment"]) == (got["terms_hash"], got["comment"]):
            continue
        version = have["version"] + 1 if have else 1
        text = _dump(instance(name, version))
        new[f"{name}/{version}.json"] = text
        rows.append({"name": name, "version": version, "hash": got["terms_hash"], "sentence": got["sentence"],
                     "comment": got["comment"], "trust": trust(name), "file_sha256": _sha(text)})
    return sorted(rows, key=lambda r: (r["name"], r["version"])), new


def index_text(rows: list[dict]) -> str:
    return _dump({"standard": STANDARD, "site": SITE, "templates": rows})


def build(root: Path = DIR, write: bool = True) -> list[str]:
    """Publish what the code holds and the registry does not. Returns the files a build adds or rewrites (the index
    among them when it differs); with write=False nothing is written, which is `--check`."""
    rows, new = plan(root)
    index = index_text(rows)
    path = root / "index.json"
    stale = sorted(new) + ([] if path.exists() and path.read_text(encoding="utf-8") == index else ["index.json"])
    if write:
        for rel, text in new.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8", newline="")
        if "index.json" in stale:
            root.mkdir(parents=True, exist_ok=True)
            path.write_text(index, encoding="utf-8", newline="")
    return stale


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["build"] and argv[1:] in ([], ["--check"]):
            stale = build(write=argv[1:] == [])
            if argv[1:] and stale:
                print("terms/ is not what the templates in the code publish: run python scripts/terms_registry.py build (" + ", ".join(stale) + ")")
                return 1
            print("\n".join(f"wrote terms/{rel}" for rel in stale) if stale and not argv[1:] else "terms/ is up to date")
            return 0
        if argv[:1] == ["verify"] and len(argv) == 2:
            path = Path(argv[1])
            found = verify(argv[1] if is_hash(argv[1]) or not path.is_file() else path.read_text(encoding="utf-8"), DIR)
            print(said(found))
            return 0 if found else 1
        if argv[:1] == ["cite"] and len(argv) in (2, 3):
            line, url = cite(argv[1], int(argv[2]) if len(argv) == 3 else None, DIR)
            print(f"{line}\n{url}")
            return 0
    except Changed as why:
        print(str(why))
        return 1
    except KeyError as why:
        print(str(why.args[0]))
        return 1
    print(__doc__.split("\n\n")[1])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
