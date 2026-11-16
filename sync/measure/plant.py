"""E9: plant 30 false statements in a copy of the repository, 6 of each kind, and count what knos-sync reports.

    python3 -I sync/measure/plant.py --bin PATH/knos-sync --repo . --out sync-measure.json [--markdown sync-measure.md]

(a) In a copy, each kind gets 6 false statements. A statement is planted first by changing the value at a place
    sync/facts.json links (one plant per line), and the rest as new sentences at the end of a document, where no
    entry links them. `knos-sync check` can report only linked places; `knos-sync scan` should list every plant as a
    candidate of its kind. Both counts are written, per kind.
(b) On the unchanged copy, every notice `knos-sync check` prints is listed: each is a false alarm unless a person
    finds the text really is stale. A kind whose notices on the unchanged copy are more than 10% of its notices is
    one to turn off by default (SYNC/P6.md strongest rule 2).

Standard library only. The copy is made in a temporary folder and removed at the end.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KINDS = ["version", "hash", "count", "price", "name"]
PER_KIND = 6
SKIP = ("repos/", "programs/", "programs-v2/", "programs-hook/", "node_modules/", ".git/")
NUMBER = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")


def copy_repo(repo: Path, dest: Path) -> None:
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    for rel in out.split("\0"):
        if not rel or rel.startswith(SKIP) or "/node_modules/" in rel:
            continue
        src = repo / rel
        if not src.is_file():
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)


def run_json(binary: str, args: list[str]) -> dict:
    r = subprocess.run([binary, *args], capture_output=True, text=True, encoding="utf-8")
    if not r.stdout.strip():
        raise SystemExit(f"knos-sync {' '.join(args)} printed nothing (exit {r.returncode}): {r.stderr[:500]}")
    return json.loads(r.stdout)


def false_value(kind: str, says: str, i: int) -> str:
    """A value that differs from what the text says, written the same way."""
    if kind in ("count", "price"):
        m = NUMBER.search(says)
        core = m.group(0)
        decimals = len(core.split(".")[1]) if "." in core else 0
        value = float(core.replace(",", "")) + 7 + i
        text = f"{value:,.{decimals}f}" if "," in core else f"{value:.{decimals}f}"
        return says[:m.start()] + text + says[m.end():]
    if kind == "hash":
        last = says[-1]
        return says[:-1] + ("0" if last != "0" else "1")
    if kind == "version":
        parts = says.split(".")
        parts[-1] = str(int(re.sub(r"\D.*", "", parts[-1]) or 0) + 1 + i)
        return ".".join(parts)
    stem, dot, ext = says.rpartition(".")
    return f"{stem}_missing{i}{dot}{ext}" if dot else says + f"_missing{i}"


def sentence(kind: str, i: int, rng: random.Random) -> str:
    """A new false statement of a kind, in words a document of Knos would use."""
    return {
        "count": f"Knos keeps {9_901 + i:,} servers in reserve for this tool.",
        "price": f"Each extra run costs ${i + 2}.47 in test money.",
        "version": f"The checker runs on release 9.{i}.3 of its own code.",
        "hash": f"The archive of this page has sha256 `{rng.getrandbits(256):064x}`.",
        "name": f"The full list is kept in docs/reference/missing_list_{i}.md for readers.",
    }[kind]


def plant(copy: Path, facts: dict, rng: random.Random) -> list[dict]:
    plants: list[dict] = []
    used_lines: set[tuple[str, int]] = set()
    for kind in KINDS:
        n = 0
        for e in facts.get("entries", []):
            if e["kind"] != kind:
                continue
            for p in e["places"]:
                if n >= PER_KIND or (p["file"], p["line"]) in used_lines:
                    continue
                path = copy / p["file"]
                lines = path.read_text(encoding="utf-8").split("\n")
                line = lines[p["line"] - 1]
                at = line.find(p["text"])
                at = at + p["text"].index(p["says"]) if at >= 0 else line.find(p["says"])
                if at < 0:
                    continue
                new = false_value(kind, p["says"], n)
                lines[p["line"] - 1] = line[:at] + new + line[at + len(p["says"]):]
                path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
                used_lines.add((p["file"], p["line"]))
                plants.append({"kind": kind, "file": p["file"], "line": p["line"], "linked": True, "entry": e["id"],
                               "was": p["says"], "now": new})
                n += 1
        target = "docs/reference/NEAR.md" if (copy / "docs/reference/NEAR.md").is_file() else "README.md"
        path = copy / target
        text = path.read_text(encoding="utf-8")
        while n < PER_KIND:
            if not text.endswith("\n"):
                text += "\n"
            s = sentence(kind, n, rng)
            text += "\n" + s + "\n"
            line_no = len(text.split("\n")) - 1     # the sentence is the last line before the final newline
            plants.append({"kind": kind, "file": target, "line": line_no, "linked": False, "entry": None, "now": s})
            n += 1
        path.write_text(text, encoding="utf-8", newline="\n")
    return plants


def notices(report: dict) -> list[dict]:
    out = []
    for e in report.get("entries") or []:
        for p in e.get("places") or []:
            if p.get("status") in ("stale", "broken"):
                out.append({"kind": e["kind"], "entry": e["id"], "file": p["file"], "line": p["line"], "status": p["status"],
                            "now": p.get("now", ""), "should": p.get("should", "")})
        if e.get("status") == "error":
            out.append({"kind": e["kind"], "entry": e["id"], "file": "", "line": 0, "status": "error", "now": e.get("error", ""), "should": ""})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown")
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args(argv)
    binary = str(Path(args.bin).resolve())
    repo = Path(args.repo).resolve()
    rng = random.Random(args.seed)
    tmp = Path(tempfile.mkdtemp(prefix="knos-sync-measure-"))
    try:
        unchanged, planted = tmp / "unchanged", tmp / "planted"
        copy_repo(repo, unchanged)
        copy_repo(repo, planted)
        base = run_json(binary, ["check", "--json", "--reread-wait", "0s", "--root", str(unchanged)])
        facts = json.loads((planted / "sync" / "facts.json").read_text(encoding="utf-8"))
        plants = plant(planted, facts, rng)
        after = run_json(binary, ["check", "--json", "--reread-wait", "0s", "--root", str(planted)])
        scan = run_json(binary, ["scan", "--json", "--full", "--root", str(planted)])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    reported = {(n["file"], n["line"]) for n in notices(after) if n["status"] == "stale"}
    listed = {(c["file"], c["line"], c["kind"]) for c in scan.get("candidates") or []}
    off = set(after.get("kinds_off") or [])
    false_alarms = notices(base)
    per_kind = {}
    for kind in KINDS:
        ps = [p for p in plants if p["kind"] == kind]
        hits = sum(1 for p in ps if (p["file"], p["line"]) in reported)
        fa = sum(1 for n in false_alarms if n["kind"] == kind)
        per_kind[kind] = {
            "planted": len(ps),
            "planted_at_linked_places": sum(1 for p in ps if p["linked"]),
            "reported_by_check": hits,
            "listed_by_scan": sum(1 for p in ps if (p["file"], p["line"], kind) in listed),
            "notices_on_unchanged_repository": fa,
            "false_alarm_share_upper_bound": round(fa / (fa + hits), 3) if fa + hits else None,
            "notices_off": kind in off,
        }
    result = {"per_kind": per_kind, "plants": plants, "notices_on_unchanged_repository": false_alarms,
              "check_exit_unchanged": base.get("exit"), "check_exit_planted": after.get("exit"),
              "entries": base.get("total"), "verified_unchanged": base.get("verified")}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    md = ["### knos-sync measure (E9)", "",
          "| kind | planted | at linked places | reported by check | listed by scan | notices on the unchanged repository | notices off |",
          "|---|---|---|---|---|---|---|"]
    for kind, r in per_kind.items():
        md.append(f"| {kind} | {r['planted']} | {r['planted_at_linked_places']} | {r['reported_by_check']} | {r['listed_by_scan']} "
                  f"| {r['notices_on_unchanged_repository']} | {'yes' if r['notices_off'] else 'no'} |")
    md += ["", f"check on the unchanged copy: exit {base.get('exit')}, {base.get('verified')} of {base.get('total')} entries verified.",
           f"check on the planted copy: exit {after.get('exit')}.", ""]
    if false_alarms:
        md.append("Notices on the unchanged repository (each a false alarm unless the text really is stale):")
        md += [f"- {n['kind']} {n['entry']} {n['file']}:{n['line']} {n['status']}: {n['now']} -> {n['should']}" for n in false_alarms]
    else:
        md.append("No notice on the unchanged repository.")
    text = "\n".join(md) + "\n"
    if args.markdown:
        Path(args.markdown).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
