"""Write, or check, the sha256 in the footer of docs/reference/CHARTER.md.

    python scripts/charter_hash.py           write the footer: the sha256 of every byte above it
    python scripts/charter_hash.py --check   exit 1 when the footer is not the sha256 of the text above it

The hashed bytes are every line above the footer's rule (`---`, the page's only line that is just that). Anyone
can check them with `sed` and `sha256sum`; the footer says how."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "docs" / "reference" / "CHARTER.md"
MARKER = "\n---\n\nsha256 of everything above this line: `"
TAIL = "`. Check it yourself: `sed '/^---$/,$d' docs/reference/CHARTER.md | sha256sum`. `tests/test_neutrality.py` checks it on every change.\n"


def split(text: str) -> tuple[str, str | None]:
    """(the text above the footer, the sha256 the footer states, or None when there is no footer)."""
    if MARKER not in text:
        return text.rstrip("\n"), None
    body, foot = text.split(MARKER, 1)
    return body, foot[:64]


def digest(body: str) -> str:
    return hashlib.sha256((body + "\n").encode("utf-8")).hexdigest()


def main(argv: list[str]) -> int:
    text = PAGE.read_text(encoding="utf-8")
    body, said = split(text)
    want = digest(body)
    if "--check" in argv:
        if said != want:
            print(f"docs/reference/CHARTER.md: the footer says {said}, the text above it hashes to {want}: run python scripts/charter_hash.py")
            return 1
        print(f"docs/reference/CHARTER.md: sha256 {want}")
        return 0
    PAGE.write_text(body + MARKER + want + TAIL, encoding="utf-8", newline="")
    print(f"docs/reference/CHARTER.md: sha256 {want}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
