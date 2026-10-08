#!/usr/bin/env python3
"""docs/archive_verify.json: one recorded run of the stand-alone verifier, on an archive of this repository's samples.

    python scripts/archive_verify.py            make the archive, run its own verify.py, write the record
    python scripts/archive_verify.py --check    run it again; fail when the record is not what the run says
    python scripts/archive_verify.py --real ARCHIVE.zip --source TEXT
                                                also run the verify.py of an archive of a real period and keep what it
                                                printed under `real` (kept as written by every later run and --check)

The archive holds the sample ledger (examples/meter/buyer.jsonl) and the statement the site shows
(web/statement_sample.json). It is unpacked into an empty folder and the verify.py INSIDE it is run with
`python -I -S`: no site-packages and no PYTHONPATH, so no Knos can be imported, and the file opens no socket. The
samples carry no signed token, and the verifier says so in a note; the record keeps the count of notes.

    {"says": one sentence, "link": a path of this repository, "sealed", "evidence_root", "made_from": [...], "lines": [...]}

web/demo_data.json takes `says` and `link` (scripts/demo_data.py), for the last beat of the demonstration.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "archive_verify.json"
LEDGER, STATEMENT = "examples/meter/buyer.jsonl", "web/statement_sample.json"
SEALED = "2026-10-07"          # the day of the recorded run: one date, so the archive is the same bytes every time
LINK = "docs/RETENTION.md"


def held_run(blob: bytes, what: str) -> tuple[list[str], re.Match[str], dict]:
    """Unpack an archive into an empty folder and run the verify.py inside it with `python -I -S`."""
    with tempfile.TemporaryDirectory() as tmp:
        zipped = Path(tmp) / "archive.zip"
        zipped.write_bytes(blob)
        with zipfile.ZipFile(zipped) as z:
            z.extractall(Path(tmp) / "held")
        done = subprocess.run([sys.executable, "-I", "-S", "verify.py"], cwd=Path(tmp) / "held", capture_output=True,
                              text=True, encoding="utf-8", timeout=120)
        manifest = json.loads((Path(tmp) / "held" / "MANIFEST.json").read_text(encoding="utf-8"))
    lines = done.stdout.strip().splitlines()
    last = re.fullmatch(r"VERIFIED: (\d+) checks hold, (\d+) notes?\. No network, no Knos\.", lines[-1] if lines else "")
    if done.returncode != 0 or not last:
        raise SystemExit(f"the stand-alone verifier did not pass {what}:\n" + done.stdout + done.stderr)
    return lines, last, manifest


def run() -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from knos import archive
    blob = archive.make(ledgers={Path(LEDGER).name: (ROOT / LEDGER).read_bytes()},
                        statements={Path(STATEMENT).name: (ROOT / STATEMENT).read_bytes()}, sealed=SEALED)
    lines, last, manifest = held_run(blob, "the sample archive")
    return {"says": f"Stand-alone verifier on the sample archive: {last[1]} checks hold, {last[2]} notes.", "link": LINK,
            "sealed": SEALED, "evidence_root": manifest["evidence_root"], "made_from": [LEDGER, STATEMENT], "lines": lines}


def real(path: Path, source: str) -> dict:
    """One run on an archive of a real period (`knos archive make` on the public programs' records). The archive is
    not in this repository, so this part of the record is kept as written and `--check` does not make it again."""
    blob = path.read_bytes()
    lines, last, manifest = held_run(blob, str(path))
    return {"says": f"Stand-alone verifier on a real period's archive: {last[1]} checks hold, {last[2]} notes.",
            "source": " ".join(source.split()), "archive_sha256": hashlib.sha256(blob).hexdigest(),
            "sealed": manifest.get("sealed", ""), "evidence_root": manifest["evidence_root"], "lines": lines}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    kept = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    doc = run()
    if "--real" in args:
        at = args.index("--real")
        source = args[args.index("--source") + 1] if "--source" in args else ""
        if at + 1 >= len(args) or not source:
            raise SystemExit("--real ARCHIVE.zip needs --source \"what the archive holds, and where it was made\"")
        doc["real"] = real(Path(args[at + 1]), source)
    elif "real" in kept:
        doc["real"] = kept["real"]
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if "--check" in args:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == text
        print("docs/archive_verify.json is what the run says." if same else "docs/archive_verify.json is not what the run says: python scripts/archive_verify.py")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="")
    print("wrote docs/archive_verify.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
