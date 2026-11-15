"""The repository's secret scan: the files of the tree, or every blob ever committed (`--history`).

    python scripts/secret_scan.py                 the tracked files of the working tree
    python scripts/secret_scan.py --history       every blob reachable from any ref (`git rev-list --all --objects`, read
                                                  with `git cat-file --batch`), so a key committed and deleted later is found
    python scripts/secret_scan.py --history --json   the same, as JSON

It never prints a value. A hit is reported by its kind, the path the blob was first seen at, the blob's id (to find it
again with `git log --find-object`) and a verdict:

    test key        a key whose secret is public on purpose: under tests/, a fixtures folder, conformance/ or a vector
                    file, and not one of the addresses Knos operates with
    operational     a Solana keypair whose public key is one of the addresses in program_ids.json: it must be rotated
    reviewed        a blob a person has read, listed in REVIEWED below with what it is and why it is safe,
                    and not operational: the operational test runs first
    look            anything else: a person reads it, rotates the key if it is real, and adds it to REVIEWED with what was found

Exit 0 when every hit is a test key or reviewed, 1 otherwise, 2 when git cannot be read. Binary blobs (a NUL byte in the first
8,000) and blobs over 20 MB are skipped and counted. Standard library and git only; solders, when installed, checks that
a 64-byte array is a real Solana keypair (its second half is the public key of its first).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 20 * 1024 * 1024

# kind -> pattern. Each names a credential by its published format; none matches a hash, a signature or an address.
KINDS: dict[str, re.Pattern[bytes]] = {
    "private key (PEM)": re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "Solana keypair (64-byte array)": re.compile(rb"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})\b"),
    "npm token": re.compile(rb"\bnpm_[A-Za-z0-9]{36}\b"),
    "PyPI token": re.compile(rb"\bpypi-AgE[A-Za-z0-9_-]{50,}"),
    "AWS access key id": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Slack token": re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "API secret key (sk- prefix)": re.compile(rb"\bsk-(?:[a-z]{2,8}-)?[A-Za-z0-9_-]{32,}"),
    "Google API key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
}
# Blobs read by a person, by full blob id (content-addressed: a changed file is a new blob and is looked at again).
REVIEWED: dict[str, str] = {
    "4c6777be112f78e2d6d8ea324bc4afeace657484":
        "build output of examples/oidc_gate (target/deploy/oidc_gate-keypair.json); never on main or on any published "
        "tag. Its address is named nowhere in the repository and holds no role: treat the key as spent and never deploy "
        "at that address.",
}
TEST_PATH = re.compile(r"(^|/)(tests?|fixtures?|conformance|vectors?|testdata)(/|$)|_vectors?\.json$|(^|/)wycheproof", re.I)
B58 = re.compile(r"\A[1-9A-HJ-NP-Za-km-z]{32,44}\Z")


def operational(root: Path = ROOT) -> set[str]:
    """The addresses Knos operates with: every base58 value of the tree's program_ids.json files."""
    out: set[str] = set()
    for f in (root / "src/knos/settle/v2/program_ids.json", root / "programs-v2/program_ids.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out |= {v for v in doc.values() if isinstance(v, str) and B58.match(v)}
    return out


def _keypair_address(raw: bytes) -> str | None:
    """The public key of a 64-byte array when it is a real keypair; None when it is not one (or solders is absent)."""
    nums = [int(n) for n in re.findall(rb"\d+", raw)]
    if len(nums) != 64 or max(nums) > 255:
        return None
    try:
        from solders.keypair import Keypair
        return str(Keypair.from_bytes(bytes(nums)).pubkey())
    except Exception:  # not a keypair (its halves disagree), or solders is not installed
        return None


def scan_bytes(data: bytes) -> Iterator[tuple[str, bytes]]:
    for kind, pat in KINDS.items():
        for m in pat.finditer(data):
            yield kind, m.group(0)


def verdict(kind: str, raw: bytes, path: str, ops: set[str], oid: str = "") -> str:
    """The operational test comes first: a reviewed key whose address later becomes one Knos operates with must be
    rotated, whatever its review said."""
    if kind.startswith("Solana"):
        addr = _keypair_address(raw)
        if addr and addr in ops:
            return "operational"
    if oid and oid in REVIEWED:
        return "reviewed"
    return "test key" if TEST_PATH.search(path) else "look"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, encoding="utf-8").stdout


def history_blobs(repo: Path) -> Iterator[tuple[str, str, bytes | None]]:
    """(blob id, first path, bytes or None when skipped) for every blob reachable from any ref."""
    paths: dict[str, str] = {}
    for line in _git(repo, "rev-list", "--all", "--objects").splitlines():
        oid, _, path = line.partition(" ")
        if path and oid not in paths:
            paths[oid] = path
    # trees and commits carry a path too only when they are named; ask the type in the same batch and keep blobs
    proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert proc.stdin and proc.stdout
    try:
        for oid, path in paths.items():
            proc.stdin.write(oid.encode() + b"\n")
            proc.stdin.flush()
            head = proc.stdout.readline().split()
            if len(head) < 3:
                continue
            size = int(head[2])
            body = proc.stdout.read(size)
            proc.stdout.read(1)                     # the newline after the object
            if head[1] != b"blob":
                continue
            yield oid, path, (None if size > MAX_BYTES or b"\0" in body[:8000] else body)
    finally:
        proc.stdin.close()
        proc.wait()


def tree_blobs(repo: Path) -> Iterator[tuple[str, str, bytes | None]]:
    for path in _git(repo, "ls-files", "-z").split("\0"):
        f = repo / path
        if not path or not f.is_file():
            continue
        body = f.read_bytes()
        yield "", path, (None if len(body) > MAX_BYTES or b"\0" in body[:8000] else body)


def scan(blobs: Iterable[tuple[str, str, bytes | None]], ops: set[str]) -> dict:
    hits: list[dict] = []
    scanned = skipped = 0
    for oid, path, body in blobs:
        if body is None:
            skipped += 1
            continue
        scanned += 1
        seen: set[tuple[str, str]] = set()
        for kind, raw in scan_bytes(body):
            v = verdict(kind, raw, path, ops, oid)
            if (kind, v) in seen:                    # one row per kind and verdict in a blob
                continue
            seen.add((kind, v))
            hits.append({"kind": kind, "path": path, "blob": oid[:12], "verdict": v})
    by = Counter((h["kind"], h["verdict"]) for h in hits)
    return {"scanned": scanned, "skipped": skipped, "hits": hits,
            "by_kind": [{"kind": k, "verdict": v, "blobs": n} for (k, v), n in sorted(by.items())],
            "rotate": sorted({h["kind"] for h in hits if h["verdict"] in ("operational", "look")})}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--history", action="store_true", help="every blob ever committed, not only the tree")
    ap.add_argument("--repo", default=str(ROOT), help="the repository to scan (default: this one)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    try:
        out = scan(history_blobs(repo) if a.history else tree_blobs(repo), operational(ROOT) | operational(repo))
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"secret scan: git could not read {repo}: {type(e).__name__}", file=sys.stderr)
        return 2
    out["scope"] = "history" if a.history else "tree"
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"secret scan ({out['scope']}): {out['scanned']} blobs read, {out['skipped']} binary or large skipped")
        for row in out["by_kind"]:
            print(f"  {row['kind']}: {row['blobs']} blob(s), {row['verdict']}")
        for h in out["hits"]:
            if h["verdict"] != "test key":
                print(f"  {h['verdict']}: {h['kind']} in {h['path']}" + (f" (blob {h['blob']})" if h["blob"] else ""))
        print("nothing to rotate" if not out["rotate"] else "to read and rotate if real: " + ", ".join(out["rotate"]))
    return 1 if out["rotate"] else 0


if __name__ == "__main__":
    sys.exit(main())
