"""The judge of experiments/judge_proof, in plain Python: the same rule as guest/src/judge.rs, with no proof.

A stranger without the proving toolchain can still check that the journal a proof commits to is the one these checks
give for a submission: `python reference.py checks.txt fixtures/honest.txt` prints the 70 bytes as hex.

    journal = version (1) | sha256(submission) | sha256(checks) | verdict (1 passed, 0 not) | passed u16 | total u16
"""
from __future__ import annotations

import hashlib
import sys

VERSION = 1
JOURNAL_LEN = 70
MARK = b" => "


def _lines(data: bytes) -> list[bytes]:
    body = data[:-1] if data.endswith(b"\n") else data
    if not body and len(data) <= 1:
        return []
    return body.split(b"\n")


def _expected(case: bytes) -> bytes | None:
    at = case.rfind(MARK)
    return None if at < 0 else case[at + len(MARK):]


def judge(checks: bytes, submission: bytes) -> tuple[int, int]:
    """(cases passed, cases). A case passes when the submission's line is the expected output, byte for byte."""
    cases = _lines(checks)[1:]
    got = _lines(submission)
    passed = 0
    if len(got) == len(cases):
        passed = sum(1 for case, line in zip(cases, got) if _expected(case) == line)
    return passed, min(len(cases), 0xFFFF)


def journal(checks: bytes, submission: bytes) -> bytes:
    passed, total = judge(checks, submission)
    ok = total > 0 and passed == total
    out = (bytes([VERSION]) + hashlib.sha256(submission).digest() + hashlib.sha256(checks).digest()
           + bytes([int(ok)]) + passed.to_bytes(2, "little") + total.to_bytes(2, "little"))
    assert len(out) == JOURNAL_LEN
    return out


def read(journal_bytes: bytes) -> dict:
    """The fields of a journal; ValueError when it is not one."""
    if len(journal_bytes) != JOURNAL_LEN or journal_bytes[0] != VERSION or journal_bytes[65] > 1:
        raise ValueError("not a judge journal")
    return {
        "submission_sha256": journal_bytes[1:33].hex(),
        "checks_sha256": journal_bytes[33:65].hex(),
        "verdict": "passed" if journal_bytes[65] else "failed",
        "passed": int.from_bytes(journal_bytes[66:68], "little"),
        "total": int.from_bytes(journal_bytes[68:70], "little"),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: reference.py <checks> <submission>", file=sys.stderr)
        return 2
    with open(argv[1], "rb") as f:
        checks = f.read()
    with open(argv[2], "rb") as f:
        submission = f.read()
    print(journal(checks, submission).hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
