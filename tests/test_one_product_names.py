"""Knos is one product: no tracked file names the database product that once carried an entry, its maker or its
language, or the taste-data service the demand check once called. Every line of every tracked file is read (UTF-8,
errors ignored; a binary file is skipped) and a match fails, naming the file and the line.

Two exceptions, each held to its exact lines: Circle's attestation service, which Circle names after the flower
(src/knos/money/cctp.py: its API host and the constant that holds it), and the word list whose 256 words are one byte
each (repos/knos-labs/src/knos/team/words.py), where the flower is one of the words and changing it changes every code.
A word that only contains the letters (Osiris, a file name in a recorded NASA page) is no mention: the match needs no
letter just before it."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# the names, spelled in pieces so this file does not match itself
BANNED = re.compile(r"inter" r"systems|object" r"script|ql" r"oo|(?<![a-z])i" r"ris", re.I)
CCTP = "src/knos/money/cctp.py"
WORD_LIST = "repos/knos-labs/src/knos/team/words.py"
CIRCLE = re.compile(r"i" r"ris-api(?:-sandbox)?\.circle\.com|\bI" r"RIS\b|\bI" r"ris\b")   # Circle's host, the constant, the service


def allowed(path: str, line: str) -> bool:
    if path == CCTP:
        return not BANNED.search(CIRCLE.sub("", line))
    if path == WORD_LIST:
        return re.fullmatch(r"[a-z ]+", line.strip()) is not None and re.search(r"\bi" r"ris\b", line) is not None \
            and not BANNED.search(re.sub(r"\bi" r"ris\b", "", line))
    return False


def hits() -> list[str]:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8", "replace").split("\0")
    found = []
    for rel in filter(None, files):
        p = ROOT / rel
        if not p.is_file():                          # deleted in the working tree: it is going away
            continue
        raw = p.read_bytes()
        if b"\0" in raw[:8192]:                      # binary
            continue
        text = raw.decode("utf-8", "ignore")
        if not BANNED.search(text):                  # the whole file first: most files have no match at all
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if BANNED.search(line) and not allowed(rel, line):
                found.append(f"{rel}:{n}: {line.strip()[:120]}")
    return found


def test_no_tracked_file_names_them():
    found = hits()
    assert not found, f"{len(found)} lines:\n" + "\n".join(found[:200])


def test_no_tracked_path_names_them():
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8", "replace").split("\0")
    found = [rel for rel in filter(None, files) if (ROOT / rel).is_file() and BANNED.search(rel)]
    assert not found, found[:50]


def test_the_exceptions_are_exact():
    big, small = "I" "RIS", "i" "ris"
    assert allowed(CCTP, f'{big} = {{"sandbox": "https://{small}-api-sandbox.circle.com", "mainnet": "https://{small}-api.circle.com"}}')
    assert not allowed(CCTP, "the " + "Ql" "oo key")
    assert not allowed("src/knos/other.py", "I" "ris")
    assert allowed(WORD_LIST, "hazel heart index ink " + "i" "ris" + " island ivory")
    assert not allowed(WORD_LIST, "knos_" + "i" "ris = 1")
    assert BANNED.search("knos_" + "i" "ris") and BANNED.search("Inter" "Systems") and not BANNED.search("Osi" "ris") and not BANNED.search("akroti" "risaltlake")
