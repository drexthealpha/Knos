"""The registry of published terms, read: which published template and version some terms are, and the sentence a
contract carries (docs/TERMS.md, "Knos Terms 1"). scripts/terms_registry.py builds the registry from
knos.terms_templates; this module only reads it, so `knos terms cite` and `knos terms verify` work from an installed
package (the wheel carries the registry as knos/_terms) as they do in a checkout (terms/ at the root).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import terms

STANDARD = "Knos Terms 1"
SITE = "https://drexthealpha.github.io/Knos"
NOT_PUBLISHED = "not a published template"
_HASH = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,39}")
_HERE = Path(__file__).resolve().parent
PLACES = (_HERE / "_terms", _HERE.parents[1] / "terms")      # in a wheel; in a checkout


class Absent(ValueError):
    """No registry beside this package: neither the wheel's copy nor a checkout's terms/."""


def where() -> Path:
    """The registry's folder. Raises Absent, in plain words, when this installation has none."""
    for place in PLACES:
        if (place / "index.json").is_file():
            return place
    raise Absent("The registry of published terms is not in this installation. It is the folder terms/ of the Knos repository: "
                 "run this from a checkout, or read " + SITE + "/terms/index.json")


def is_hash(text: str) -> bool:
    return bool(_HASH.fullmatch(text.strip().lower()))


class Changed(ValueError):
    """The registry is not what its index says: a published file was edited, removed, or added by hand."""


def sentence(name: str, version: int, digest: str) -> str:
    """The sentence a contract carries."""
    return f"Acceptance is governed by {STANDARD}, template {name} version {version}, sha256 {digest}"


def load(root: Path | None = None) -> list[dict]:
    """The index's rows, oldest version first within a name. An absent index is an empty registry."""
    path = (root or where()) / "index.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))["templates"]
    return sorted(rows, key=lambda r: (r["name"], r["version"]))


def check(root: Path | None = None) -> list[dict]:
    """The index's rows, after every file it lists was read and held to it. Raises Changed with what differs."""
    root = root or where()
    rows = load(root)
    listed = set()
    for r in rows:
        if not _NAME.fullmatch(str(r.get("name"))) or type(r.get("version")) is not int or r["version"] < 1:
            raise Changed(f"terms/index.json lists a template with no usable name or version: {r.get('name')!r} {r.get('version')!r}")
        rel = f"{r['name']}/{r['version']}.json"
        path = root / r["name"] / f"{r['version']}.json"
        if (r["name"], r["version"]) in listed:
            raise Changed(f"terms/index.json lists terms/{rel} twice")
        listed.add((r["name"], r["version"]))
        if not path.exists():
            raise Changed(f"terms/{rel} is listed and missing: a published version is never removed")
        text = path.read_bytes().decode("utf-8")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != r["file_sha256"]:
            raise Changed(f"terms/{rel} changed after it was published: restore it, and publish the change as version {r['version'] + 1}")
        body = json.loads(text)
        raw = body["terms_json"].encode("ascii")
        if (terms.terms_hash(raw) != r["hash"] or body["terms_hash"] != r["hash"] or terms.canonical(terms.parse(raw)) != raw
                or body["terms"] != json.loads(raw) or (body["name"], body["version"], body["sentence"]) != (r["name"], r["version"], r["sentence"])):
            raise Changed(f"terms/{rel} does not say what terms/index.json lists for it")
    for name in sorted({n for n, _v in listed}):
        have = sorted(v for n, v in listed if n == name)
        if have != list(range(1, len(have) + 1)):
            raise Changed(f"the versions of {name} are {have}: versions are 1, 2, 3 and so on, with none left out")
    for path in sorted(root.glob("*/*.json")) if root.exists() else []:
        if not path.stem.isdigit() or (path.parent.name, int(path.stem)) not in listed:
            raise Changed(f"terms/{path.parent.name}/{path.name} is not listed in terms/index.json: `build` publishes a version, nothing else does")
    return rows


def latest(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        if r["name"] not in out or r["version"] > out[r["name"]]["version"]:
            out[r["name"]] = r
    return out


def verify(what, root: Path | None = None) -> list[dict]:
    """The published versions `what` is: a sha256 in hex, a terms JSON (object, or its text), or a published file's
    content. Every match, oldest first; [] when it is not a published template. Terms are put in canonical form
    first, so the same terms with other spacing or key order are found; terms the format refuses match nothing."""
    digest = None
    if isinstance(what, str) and _HASH.fullmatch(what.strip().lower()):
        digest = what.strip().lower()
    else:
        try:
            data = json.loads(what) if isinstance(what, (str, bytes, bytearray)) else what
            if isinstance(data, dict) and isinstance(data.get("terms"), dict):
                data = data["terms"]
            digest = terms.terms_hash(terms.canonical(data))
        except (ValueError, RecursionError, UnicodeDecodeError):
            return []
    return [r for r in check(root) if r["hash"] == digest]


def said(found: list[dict]) -> str:
    if not found:
        return NOT_PUBLISHED
    return "\n".join(f"{STANDARD}, template {r['name']} version {r['version']}, sha256 {r['hash']}\n    {r['sentence']}" for r in found)


def cite(name: str, version: int | None = None, root: Path | None = None) -> tuple[str, str]:
    """(the sentence a contract carries, the address of the published file on the site). `version` None: the newest.
    Raises KeyError, with what is published, for a name or version that is not."""
    rows = [r for r in check(root) if r["name"] == name]
    if not rows:
        raise KeyError(f"no template named {name} is published: the published ones are {', '.join(latest(check(root))) or 'none'}")
    row = rows[-1] if version is None else next((r for r in rows if r["version"] == version), None)
    if row is None:
        raise KeyError(f"{name} has no version {version}: its versions are {', '.join(str(r['version']) for r in rows)}")
    return sentence(name, row["version"], row["hash"]), f"{SITE}/terms/{name}/{row['version']}.json"


# ---- Knos Terms 3: documents that answer ten questions (knos.terms3), published beside the older templates -----------

STANDARD3 = "Knos Terms 3"
DIR3 = "3"            # terms/3/<name>/<version>.json; the index lists them under "terms3"


def sentence3(name: str, version: int, digest: str) -> str:
    return f"Acceptance is governed by {STANDARD3}, {name} version {version}, sha256 {digest}"


def load3(root: Path | None = None) -> list[dict]:
    """The index's terms 3 rows, oldest version first within a name. An index with none lists none."""
    path = (root or where()) / "index.json"
    if not path.exists():
        return []
    rows = (json.loads(path.read_text(encoding="utf-8")).get("terms3") or {}).get("documents") or []
    return sorted(rows, key=lambda r: (r["name"], r["version"]))


def check3(root: Path | None = None) -> list[dict]:
    """The terms 3 rows, after every file they list was read and held to them. Raises Changed with what differs."""
    from . import terms3
    root = root or where()
    rows, listed = load3(root), set()
    for r in rows:
        if not _NAME.fullmatch(str(r.get("name"))) or type(r.get("version")) is not int or r["version"] < 1 or (r["name"], r["version"]) in listed:
            raise Changed(f"terms/index.json lists a terms 3 document with no usable name or version, or twice: {r.get('name')!r} {r.get('version')!r}")
        listed.add((r["name"], r["version"]))
        rel = f"{DIR3}/{r['name']}/{r['version']}.json"
        path = root / DIR3 / r["name"] / f"{r['version']}.json"
        if not path.exists():
            raise Changed(f"terms/{rel} is listed and missing: a published version is never removed")
        text = path.read_bytes().decode("utf-8")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != r["file_sha256"]:
            raise Changed(f"terms/{rel} changed after it was published: restore it, and publish the change as version {r['version'] + 1}")
        try:
            doc = json.loads(text)
            same = (terms3.digest(doc) == r["hash"] and terms3.dumps(doc) == text and (doc["name"], doc["version"]) == (r["name"], r["version"])
                    and terms3.built(doc) == r["built"])
        except ValueError as why:
            raise Changed(f"terms/{rel} is not a terms 3 document: {why}") from None
        if not same:
            raise Changed(f"terms/{rel} does not say what terms/index.json lists for it")
    for name in sorted({n for n, _v in listed}):
        have = sorted(v for n, v in listed if n == name)
        if have != list(range(1, len(have) + 1)):
            raise Changed(f"the versions of {name} are {have}: versions are 1, 2, 3 and so on, with none left out")
    for path in sorted((root / DIR3).glob("*/*.json")) if (root / DIR3).exists() else []:
        if not path.stem.isdigit() or (path.parent.name, int(path.stem)) not in listed:
            raise Changed(f"terms/{DIR3}/{path.parent.name}/{path.name} is not listed in terms/index.json: `build` publishes a version, nothing else does")
    return rows


def read3(name: str, version: int | None = None, root: Path | None = None) -> dict:
    """A published terms 3 document. `version` None: the newest. Raises KeyError with what is published."""
    root = root or where()
    rows = [r for r in check3(root) if r["name"] == name]
    if not rows:
        raise KeyError(f"no terms 3 document named {name} is published: the published ones are {', '.join(latest(check3(root))) or 'none'}")
    row = rows[-1] if version is None else next((r for r in rows if r["version"] == version), None)
    if row is None:
        raise KeyError(f"{name} has no version {version}: its versions are {', '.join(str(r['version']) for r in rows)}")
    return json.loads((root / DIR3 / name / f"{row['version']}.json").read_text(encoding="utf-8"))


def verify3(doc: dict, root: Path | None = None) -> tuple[str, list[dict]]:
    """(the document's sha256, the published versions it is). Raises knos.terms3.Missing with the absent fields, or
    knos.terms3.Refused with the one that is wrong: a terms 3 file that does not answer all ten questions is refused."""
    from . import terms3
    digest = terms3.digest(doc)
    try:
        rows = check3(root)
    except Absent:
        rows = []
    return digest, [r for r in rows if r["hash"] == digest]


def said3(doc: dict, digest: str, found: list[dict]) -> str:
    """What `knos terms verify` prints for a terms 3 file that answers all ten questions."""
    from . import terms3
    got = terms3.validate(doc)
    head = (("\n".join(f"{STANDARD3}, {r['name']} version {r['version']}, sha256 {r['hash']}" for r in found)) if found else
            f"{STANDARD3}, {got['name']} version {got['version']}, sha256 {digest}\n    Complete: all ten fields are there. It is not one of the published templates, which is usual for a repository's own terms.")
    lines = "".join(f"\n    {q['question']} {q['answer']}" for q in terms3.questions(got))
    return head + lines + ("" if terms3.built(got) else f"\n    This template cannot fund an order: {terms3.NOT_BUILT}.")
