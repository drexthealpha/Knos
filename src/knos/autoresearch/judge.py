"""The referee for a metric task: the only thing in the loop that decides. Locked: its own code is hashed into the
sealed spec, and graduation refuses if that hash moved (judge_drift).

For each candidate (a dict of files the agent submits):

  static rules, before any of its code runs (each a named rule; category = the Knos Record `cheat` field)
    AR-SCOPE    out_of_scope     a file other than the task's one editable file
    AR-NOCHANGE no_change        the editable file is byte-identical to the current best
    AR-IMPORT   runner_tampering an import outside the allowlist, or __import__/importlib/eval/exec/compile/open of a
                                 literal path (the candidate reads only the files it is handed on the command line)
    AR-SEALED   data_tampering   a string that reaches for the referee's side: "sealed", "hidden", "..", an absolute path
    + knos.cheats.scan(base, pr, scope=[editable]) when knos.cheats is installed (the shared cheat library)
    AR-IMPORT also refuses getattr/setattr, any private attribute (x._os), any dunder name but __name__, and attributes
    that lead to the operating system (x.sys, x.modules, x.os, ...): sys is not importable, so sys.modules["o"+"s"] and
    statistics.sys.modules are refused.
    AR-FILE   runner_tampering  any file or OS access at all: open (called, aliased or as an attribute),
                                 io / os / pathlib (not importable), argparse.FileType, read_text/write_text, and the
                                 tools that build a string the rules cannot read: chr, bytes, bytearray, .decode,
                                 .fromhex. The candidate reads data only through `knos_io` (rows, output), which the
                                 referee's runner hands it (sandbox.py). An outside judge read the sealed seed through a
                                 path built with chr(); this rule refuses that, and the namespace mask hides the file.

LIMIT: these rules are a static filter, not an OS sandbox. The candidate runs as
the referee's own user; a determined candidate may still find a path the filter misses and read any file that user can
(for example the demo's sealed seed). Labels are never on disk in the sandbox, but for real money the referee must run
candidates on a machine or account that holds neither the sealed file nor the hidden labels.
  dynamic
    two runs, seeds[0] and seeds[1], each on the sealed hidden set's features with a fixed time budget
    AR-RERUN    rerun_mismatch   the two scores differ by more than rerun_tolerance (absolute)
    the score is the mean of the two runs; a run that fails or overruns its budget fails the candidate (not a cheat)

final(): baseline and best on hidden_final (used nowhere else), both seeds; graduates when the best's lift over the
baseline is >= min_lift on EACH seed, both re-runs agree, and the judging code still hashes as sealed.
"""
from __future__ import annotations

import ast
import hashlib
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import sandbox
from .task import Task

ALLOWED_IMPORTS = frozenset({"argparse", "bisect", "collections", "csv", "functools", "heapq", "itertools", "json",
                             "knos_io", "math", "random", "statistics", "time"})
FORBIDDEN_CALLS = frozenset({"__import__", "eval", "exec", "compile", "breakpoint", "globals", "locals", "vars", "getattr", "setattr",
                             "delattr", "memoryview"})
# names that lead from an allowed module to the operating system: statistics.sys, a module's _os, sys.modules, ...
FORBIDDEN_ATTRS = frozenset({"sys", "os", "modules", "builtins", "subprocess", "system", "popen", "spawn", "fork", "exec",
                             "import_module", "loader", "socket", "ctypes", "environ", "f_globals", "f_back", "gi_frame"})
FILE_NAMES = frozenset({"open", "chr", "bytes", "bytearray", "input", "exec", "eval", "compile", "__import__", "getattr",
                        "setattr", "delattr", "globals", "locals", "vars", "breakpoint", "memoryview"})
FILE_ATTRS = frozenset({"open", "FileType", "read_text", "write_text", "read_bytes", "write_bytes", "decode", "fromhex",
                        "b64decode", "a2b_hex", "unhexlify", "fdopen", "popen"})
SEALED_WORDS = ("sealed", "hidden", "..")
LOCKED_FILES = ("judge.py", "sandbox.py", "synth.py", "task.py")


@dataclass
class Finding:
    rule: str
    category: str
    path: str
    detail: str
    severity: str = "refuse"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Verdict:
    passed: bool
    score: float | None = None
    isolation: str = ""
    scores: list[float] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    cheats: list[Finding] = field(default_factory=list)
    reported: dict = field(default_factory=dict)
    wall_s: float = 0.0

    @property
    def refused(self) -> bool:
        return any(c.severity == "refuse" for c in self.cheats)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cheats"] = [c.to_dict() for c in self.cheats]
        return d


def judge_hash() -> str:
    """sha256 of the locked judging code of the RUNNING install: this package's judge, sandbox, synth and task
    modules, plus knos.referee.judge_hash() when the shared referee is installed."""
    here = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in LOCKED_FILES:
        h.update(name.encode() + b"\0" + (here / name).read_bytes().replace(b"\r\n", b"\n") + b"\0")
    try:
        from knos import referee  # type: ignore[attr-defined]
        h.update(b"referee\0" + str(referee.judge_hash()).encode())
    except (ImportError, AttributeError):
        pass
    return h.hexdigest()


def accuracy(preds: list[int], rows: list) -> float:
    return sum(1 for p, (_x, y) in zip(preds, rows) if p == y) / len(rows)


def static_findings(files: dict[str, str], editable: str, current: str | None) -> list[Finding]:
    out = [Finding("AR-SCOPE", "out_of_scope", name, f"only {editable} may change")
           for name in sorted(files) if name != editable]
    src = files.get(editable)
    if src is None:
        return out + [Finding("AR-SCOPE", "out_of_scope", editable, "the editable file is missing")]
    if current is not None and src == current:
        out.append(Finding("AR-NOCHANGE", "no_change", editable, "identical to the current best"))
    try:
        tree = ast.parse(src)
    except SyntaxError as why:
        return out + [Finding("AR-SYNTAX", "no_change", editable, f"does not parse: {why.msg} (line {why.lineno})", "flag")]
    prose = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    for node in ast.walk(tree):
        if id(node) in prose:                     # a docstring or bare string: words, not a path the code opens
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                if n.split(".")[0] not in ALLOWED_IMPORTS or (isinstance(node, ast.ImportFrom) and node.level):
                    out.append(Finding("AR-IMPORT", "runner_tampering", editable, f"line {node.lineno}: import {n or '.'}"))
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in FORBIDDEN_CALLS or name.startswith("importlib"):
                out.append(Finding("AR-IMPORT", "runner_tampering", editable, f"line {node.lineno}: {name}()"))
            if name == "open" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                out.append(Finding("AR-IMPORT", "runner_tampering", editable, f"line {node.lineno}: open() of a literal path"))
        elif isinstance(node, ast.Attribute) and node.attr in FILE_ATTRS:
            out.append(Finding("AR-FILE", "runner_tampering", editable, f"line {node.lineno}: .{node.attr} (file access or a built string)"))
        elif isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in FORBIDDEN_ATTRS):
            out.append(Finding("AR-IMPORT", "runner_tampering", editable, f"line {node.lineno}: .{node.attr}"))
        elif isinstance(node, ast.Name) and node.id in FILE_NAMES:
            out.append(Finding("AR-FILE", "runner_tampering", editable, f"line {node.lineno}: {node.id} (file access or a built string)"))
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id != "__name__":
            out.append(Finding("AR-IMPORT", "runner_tampering", editable, f"line {node.lineno}: {node.id}"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.lower()
            if any(w in v for w in SEALED_WORDS) or v.startswith(("/", "\\")) or (len(v) > 2 and v[1] == ":" and v[2] in "/\\"):
                out.append(Finding("AR-SEALED", "data_tampering", editable, f"line {getattr(node, 'lineno', 0)}: {node.value[:40]!r}"))
    return out


def shared_findings(files: dict[str, str], editable: str, current: str) -> list[Finding]:
    """The shared cheat library (knos.cheats, REFEREE) on base vs candidate trees, when it is installed."""
    try:
        from knos import cheats  # type: ignore[attr-defined]
        scan = cheats.scan
    except (ImportError, AttributeError):
        return []
    with tempfile.TemporaryDirectory(prefix="knos-ar-scan-") as d:
        base, pr = Path(d) / "base", Path(d) / "pr"
        base.mkdir()
        pr.mkdir()
        (base / editable).write_text(current, encoding="utf-8")
        for name, text in files.items():
            if "/" not in name and "\\" not in name and not name.startswith("."):
                (pr / name).write_text(text, encoding="utf-8")
        got = scan(base, pr, scope=[editable])
    return [Finding(str(f.rule), str(f.category), str(f.path), str(f.detail), str(f.severity)) for f in got]


class LocalJudge:
    backend = "knos.autoresearch.judge"

    def __init__(self, task: Task, python: str | None = None, mask=()):
        """`mask`: more paths no candidate may read (a game's folder, say); the task's sealed file, its folder and the
        hidden data files are always masked where the OS gives the candidate its own namespace (sandbox.py)."""
        self.task = task
        self.python = python
        sealed = Path(task.sealed_path).resolve()
        hidden = [sealed.parent / str(v) for k, v in (task.sealed or {}).items() if k in ("dev", "final") and isinstance(v, str)]
        self.mask = [str(sealed), str(sealed.parent), *[str(h) for h in hidden], *[str(m) for m in mask]]
        self.isolation = ""
        self.sealed_contents = task.hidden_sha256()
        self.public = task.public()
        self.hidden = task.hidden()
        self.sealed_judge = judge_hash()

    def seal(self) -> dict:
        t = self.task.spec
        return {"spec_hash": self.task.spec_hash(self.sealed_judge), "judge_hash": self.sealed_judge,
                "editable": t["editable"], "seeds": t["seeds"][:2], "tolerance": {"abs": t["rerun_tolerance"]},
                "sealed_at": int(time.time()), "backend": self.backend, "hidden_sha256": self.sealed_contents}

    def sealed_changed(self) -> str | None:
        """Why the hidden data on disk is not what was sealed (its contents' hash moved), or None."""
        now = self.task.hidden_sha256()
        return None if now == self.sealed_contents else (f"sealed_changed: the hidden data hashes {now[:16]}, it was sealed as "
                                                         f"{self.sealed_contents[:16]}")

    def _runs(self, source: str, rows: list) -> tuple[list[float], list[str], dict, float]:
        t = self.task.spec
        scores: list[float] = []
        reasons: list[str] = []
        reported: dict = {}
        wall = 0.0
        for seed in t["seeds"][:2]:
            r = sandbox.run(source, t["editable"], self.public, [(x, 0) for x, _y in rows], seed, float(t["time_budget_s"]), self.python,
                            mask=self.mask)
            self.isolation = r.isolation
            wall += r.wall_s
            if not r.ok:
                reasons.append(f"seed {seed}: {r.error}")
                break
            reported = reported or r.reported
            scores.append(accuracy(r.predictions, rows))
        return scores, reasons, reported, wall

    def judge(self, files: dict[str, str], current: str | None, stage: str = "dev") -> Verdict:
        t = self.task.spec
        found = static_findings(files, t["editable"], current)
        if current is not None:
            found += shared_findings(files, t["editable"], current)
        if any(f.severity == "refuse" for f in found):
            return Verdict(False, reasons=[f"refused: {f.rule} {f.detail}" for f in found if f.severity == "refuse"], cheats=found)
        if any(f.rule == "AR-SYNTAX" for f in found):
            return Verdict(False, reasons=[f.detail for f in found], cheats=found)
        scores, reasons, reported, wall = self._runs(files[t["editable"]], self.hidden[stage])
        if reasons:
            return Verdict(False, scores=scores, reasons=reasons, cheats=found, reported=reported, wall_s=wall, isolation=self.isolation)
        if abs(scores[0] - scores[1]) > t["rerun_tolerance"]:
            found.append(Finding("AR-RERUN", "rerun_mismatch", t["editable"],
                                 f"seed scores {scores[0]:.4f} vs {scores[1]:.4f} differ by more than {t['rerun_tolerance']}"))
            return Verdict(False, scores=scores, reasons=["re-run mismatch"], cheats=found, reported=reported, wall_s=wall,
                           isolation=self.isolation)
        return Verdict(True, score=sum(scores) / len(scores), scores=scores, cheats=found, reported=reported, wall_s=wall,
                       isolation=self.isolation)

    def final(self, baseline: str, best: str) -> dict:
        """Graduation: baseline and best on hidden_final, both seeds, judging code unchanged since sealing."""
        t = self.task
        now = judge_hash()
        base_v = self.judge({t.editable: baseline}, None, stage="final")
        best_v = self.judge({t.editable: best}, None, stage="final")
        reasons = []
        if now != self.sealed_judge:
            reasons.append("judge_drift: the judging code changed since the spec was sealed")
        moved = self.sealed_changed()
        if moved:
            reasons.append(moved)
        for name, v in (("baseline", base_v), ("best", best_v)):
            if not v.passed:
                reasons.append(f"{name}: " + "; ".join(v.reasons))
        lifts = [t.lift(b, a) for a, b in zip(base_v.scores, best_v.scores)] if base_v.passed and best_v.passed else []
        if lifts and min(lifts) < t.spec["min_lift"]:
            reasons.append(f"lift {min(lifts):.4f} on the worse seed is below the agreed {t.spec['min_lift']}")
        if best == baseline:
            reasons.append("no change was kept")
        return {"graduated": not reasons, "reasons": reasons, "baseline": base_v.to_dict(), "best": best_v.to_dict(),
                "lift_per_seed": lifts, "lift": (sum(lifts) / len(lifts)) if lifts else None,
                "min_lift": t.spec["min_lift"], "judge_hash": now, "judge_unchanged": now == self.sealed_judge}
