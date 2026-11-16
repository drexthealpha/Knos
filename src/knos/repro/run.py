"""Re-run a research repository's claims: once as the authors ran it, on this (second) machine, and once on a held-out
split the authors never saw. Each run happens in a fresh copy of the repository, with an environment that carries no
token, key or secret of the machine.

A claim holds when the metric it names is within its tolerance of the expected value on BOTH runs. The result is:

    reproduced   every claim holds on both runs and no cheat rule fired. Only this result gets a badge or a public page.
    contested    a claim missed its tolerance, a metric was missing, or a cheat rule fired. Kept PRIVATE, with a notice
                 for the authors (knos.repro.publish.notice), and never published by Knos.
    failed       the entry or the data generator did not finish (error, or over the compute budget). Kept private too.
    incomplete   there was no held-out split to run (no generator and no --heldout folder). Kept private; no badge.

Cheat rules of a reproduction (each one makes the result contested):

    data_tamper        a file the spec protects (data.protected, knos.yml itself, every `reported` results file) changed
                       during a run
    reported_mismatch  the number the repository publishes for a claim (its `reported` file) is not the number knos.yml
                       claims: the README's table and the spec disagree
    metric_missing     the entry did not write the metric a claim names (or wrote something that is not a number)
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

FORMAT = "knos-research-reproduction/1"
STATUSES = ("reproduced", "contested", "failed", "incomplete")
RULES = ("data_tamper", "reported_mismatch", "metric_missing")
_SECRET = re.compile(r"(TOKEN|SECRET|KEY|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|SESSION|PRIVATE)", re.I)
_SKIP_COPY = {".git", ".knos-repro", "__pycache__", ".pytest_cache", ".venv", "node_modules"}


def canonical(doc: dict) -> bytes:
    """The one form of a result (the same rule as knos.reproduce.canonical)."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k != "digest"}
    return hashlib.sha256(canonical(body)).hexdigest()


def clean_env(base: dict | None = None, seed: int = 0) -> dict:
    """The environment a run gets: the machine's, minus anything that looks like a credential or a Knos/GitHub setting."""
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if not _SECRET.search(k) and not k.startswith(("KNOS_", "GITHUB_", "GH_", "AWS_", "AZURE_", "GOOGLE_", "SOLANA_", "ANTHROPIC_", "OPENAI_"))}
    env["PYTHONHASHSEED"] = str(seed)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["KNOS_REPRO"] = "1"
    return env


def _copy(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if n in _SKIP_COPY], symlinks=True)


def _hashes(root: Path, protected: list[str]) -> dict[str, str]:
    """sha256 of every file under each protected path (a file, or a folder: every file in it). A missing path: '-'."""
    out: dict[str, str] = {}
    for rel in protected:
        p = root / rel
        if p.is_file():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        elif p.is_dir():
            for f in sorted(x for x in p.rglob("*") if x.is_file() and "__pycache__" not in x.parts and x.suffix != ".pyc"):
                out[f.relative_to(root).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
        else:
            out[rel] = "-"
    return out


def _fill(parts: list[str], values: dict) -> list[str]:
    return [re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), p) for p in parts]


def _tail(text: str, n: int = 1500) -> str:
    return (text or "")[-n:]


def run_once(repo: Path, spec: dict, *, name: str, split: str, data_seed: int | None, heldout_dir: Path | None,
             work: Path, run=subprocess.run, clock: Callable[[], float] = time.monotonic, env: dict | None = None) -> dict:
    """One run in a fresh copy: make the data (or take the held-out folder), run the entry, read its metrics.
    Returns {name, split, exit, seconds, metrics, tampered, why, log} (the log stays private)."""
    copy = work / name
    _copy(repo, copy)
    budget = spec["compute"]["max_seconds"]
    data_dir = (copy / spec["data"]["path"]) if spec["data"]["path"] else (work / f"{name}-data")
    out_file = work / f"{name}-metrics.json"
    values = {"split": split, "seed": spec["seed"], "data": str(data_dir), "out": str(out_file), "data_seed": data_seed if data_seed is not None else ""}
    renv = clean_env(env, spec["seed"])
    renv["KNOS_METRICS_OUT"] = str(out_file)
    row: dict = {"name": name, "split": split, "exit": None, "seconds": 0.0, "metrics": {}, "tampered": [], "why": "", "log": ""}
    began = clock()
    protected = spec["data"]["protected"]
    at_start = _hashes(copy, protected)
    at_entry: dict[str, str] | None = None
    try:
        if heldout_dir is not None:
            if data_dir.exists():
                shutil.rmtree(data_dir)
            shutil.copytree(heldout_dir, data_dir)
        elif spec["data"]["generator"]:
            data_dir.mkdir(parents=True, exist_ok=True)
            got = run(_fill(spec["data"]["generator"], values), cwd=str(copy), env=renv, capture_output=True, text=True, timeout=budget)
            row["log"] += _tail(got.stdout) + _tail(got.stderr)
            if got.returncode != 0:
                row.update(exit=got.returncode, why=f"the data generator exited {got.returncode}")
                return row
        at_entry = _hashes(copy, protected)
        left = budget - (clock() - began)
        if left <= 0:
            row["why"] = f"over the compute budget of {budget:g} s before the entry started"
            return row
        got = run(_fill(spec["entry"], values), cwd=str(copy), env=renv, capture_output=True, text=True, timeout=left)
        row["exit"] = got.returncode
        row["log"] += _tail(got.stdout) + _tail(got.stderr)
        if got.returncode != 0:
            row["why"] = f"the entry exited {got.returncode}"
            return row
    except subprocess.TimeoutExpired:
        row["why"] = f"over the compute budget of {budget:g} s"
        return row
    except OSError as why:
        row["why"] = f"could not start: {why}"
        return row
    finally:
        row["seconds"] = round(clock() - began, 2)
        at_end = _hashes(copy, protected)
        # the data step may fill the data folder (that is its job) and nothing else that is protected; the entry may
        # change nothing that is protected
        moved = {k for k in set(at_start) | set(at_entry or at_end) if at_start.get(k) != (at_entry or at_end).get(k) and not _in_data(k, spec)}
        if at_entry is not None:
            moved |= {k for k in set(at_entry) | set(at_end) if at_entry.get(k) != at_end.get(k)}
        row["tampered"] = sorted(moved)
    try:
        metrics = json.loads(out_file.read_text(encoding="utf-8"))
        row["metrics"] = metrics if isinstance(metrics, dict) else {}
        if not isinstance(metrics, dict):
            row["why"] = "the entry's metrics file is not a JSON object"
    except (OSError, ValueError):
        row["why"] = f"the entry wrote no metrics file ({out_file}, also in KNOS_METRICS_OUT)"
    return row


def _in_data(rel: str, spec: dict) -> bool:
    """A path under the repository's data folder (data.path), which the data step fills."""
    path = spec["data"]["path"]
    return bool(path) and (rel == path or rel.startswith(path.rstrip("/") + "/"))


def reported(repo: Path, claim: dict) -> tuple[float | None, str]:
    """(the number the repository publishes for a claim, why it could not be read)."""
    rep = claim["reported"]
    if not rep:
        return None, ""
    try:
        doc = json.loads((repo / rep["file"]).read_text(encoding="utf-8"))
        v = doc
        for part in rep["key"].split("."):
            v = v[part]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None, f"{rep['file']}:{rep['key']} is not a number"
        return float(v), ""
    except (OSError, ValueError, KeyError, TypeError):
        return None, f"{rep['file']}:{rep['key']} could not be read"


def _metric(row: dict | None, name: str):
    v = row["metrics"].get(name) if row else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def judge(spec: dict, runs: dict[str, dict], repo: Path) -> tuple[list[dict], list[dict]]:
    """(one row per claim, the cheat rules that fired)."""
    cheats: list[dict] = []
    for r in runs.values():
        if r and r["tampered"]:
            cheats.append({"rule": "data_tamper", "run": r["name"], "paths": r["tampered"]})
    rows = []
    for c in spec["claims"]:
        rerun, held = _metric(runs.get("rerun"), c["metric"]), _metric(runs.get("heldout"), c["metric"])
        rep, rep_why = reported(repo, c)
        row = {"id": c["id"], "metric": c["metric"], "expected": c["expected"], "tolerance": c["tolerance"],
               "heldout_tolerance": c["heldout_tolerance"], "rerun": rerun, "heldout": held, "reported": rep, "holds": False, "why": ""}
        whys = []
        if c["reported"] and (rep is None or abs(rep - c["expected"]) > 1e-12):
            whys.append(rep_why or f"the repository reports {rep:g} for {c['id']}, and knos.yml claims {c['expected']:g}")
            cheats.append({"rule": "reported_mismatch", "claim": c["id"], "paths": [c["reported"]["file"]]})
        for which, got, tol in (("rerun", rerun, c["tolerance"]), ("heldout", held, c["heldout_tolerance"])):
            ran = runs.get(which)
            if not ran:
                continue
            if ran["why"] and got is None:
                continue
            if got is None:
                whys.append(f"the {which} run wrote no number for {c['metric']}")
                cheats.append({"rule": "metric_missing", "claim": c["id"], "run": which, "paths": []})
            elif abs(got - c["expected"]) > tol + 1e-12:
                whys.append(f"{which}: {got:.6g} is outside {c['expected']:g} ± {tol:g}")
        row["holds"] = not whys and rerun is not None and held is not None
        row["why"] = "; ".join(whys)
        rows.append(row)
    return rows, cheats


def machine() -> dict:
    """What the result says about where it ran: no host name, no user, no path."""
    return {"python": platform.python_version(), "platform": platform.platform(terse=True), "machine": platform.machine(),
            "cpus": os.cpu_count() or 0}


def commit_of(repo: Path) -> str:
    try:
        got = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return got.stdout.strip() if got.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}\s*", got.stdout) else ""


def reproduce(repo: Path | str, spec: dict, spec_sha256: str, *, heldout: Path | None = None, run=subprocess.run,
              now: Callable[[], float] = time.time, seed_source: Callable[[], int] | None = None, version: str = "", env: dict | None = None) -> tuple[dict, dict]:
    """(the result, the private logs). Two runs: `rerun` (the public split, the authors' data seed) and `heldout` (the
    held-out split: the `heldout` folder when given, else data made by the generator with a seed Knos picks now and
    the authors never saw). The held-out seed itself is kept out of the result; its sha256 is in it."""
    repo = Path(repo).resolve()
    runs: dict[str, dict] = {}
    logs: dict[str, str] = {}
    held_seed = None
    with tempfile.TemporaryDirectory(prefix="knos-repro-") as tmp:
        work = Path(tmp)
        runs["rerun"] = run_once(repo, spec, name="rerun", split=spec["splits"]["public"], data_seed=spec["data"]["seed"], heldout_dir=None,
                                 work=work, run=run, env=env)
        if heldout is not None:
            runs["heldout"] = run_once(repo, spec, name="heldout", split=spec["splits"]["heldout"], data_seed=None, heldout_dir=Path(heldout),
                                       work=work, run=run, env=env)
        elif spec["data"]["generator"]:
            held_seed = (seed_source or (lambda: secrets.randbelow(2**31 - 1) + 1))()
            if held_seed == spec["data"]["seed"]:
                held_seed += 1
            runs["heldout"] = run_once(repo, spec, name="heldout", split=spec["splits"]["heldout"], data_seed=held_seed, heldout_dir=None,
                                       work=work, run=run, env=env)
    for k, r in runs.items():
        logs[k] = r.pop("log", "")
    claims, cheats = judge(spec, runs, repo)
    if any(r["why"] and not r["metrics"] for r in runs.values()):
        status = "failed"
    elif cheats or any(c["why"] for c in claims):
        status = "contested"
    elif "heldout" not in runs:
        status = "incomplete"
    else:
        status = "reproduced" if all(c["holds"] for c in claims) else "contested"
    result = {"format": FORMAT, "name": spec["name"], "spec_sha256": spec_sha256, "commit": commit_of(repo), "knos": version,
              "machine": machine(), "at": int(now()), "status": status, "private": status != "reproduced",
              "heldout": {"source": "folder given at run time" if heldout is not None else ("generator, seed chosen by Knos at run time" if held_seed else "none"),
                          "seed_sha256": hashlib.sha256(str(held_seed).encode()).hexdigest() if held_seed else None},
              "runs": [{k: r[k] for k in ("name", "split", "exit", "seconds", "why")} for r in runs.values()],
              "claims": claims, "cheats": cheats, "authors": spec["authors"],
              "funding": spec["funding"] if status == "reproduced" else None}
    result["digest"] = digest(result)
    return result, logs


def summary(result: dict) -> list[str]:
    out = [f"{result['status'].upper()}: {result['name']} ({sum(c['holds'] for c in result['claims'])}/{len(result['claims'])} claims hold on the re-run and the held-out split)"]
    for c in result["claims"]:
        out.append(f"  {'holds' if c['holds'] else 'MISSES':6} {c['id']}: expected {c['expected']:g} ± {c['tolerance']:g}; "
                   f"re-run {_show(c['rerun'])}, held-out {_show(c['heldout'])}" + (f" ({c['why']})" if c["why"] else ""))
    for r in result["runs"]:
        if r["why"]:
            out.append(f"  run {r['name']}: {r['why']}")
    for ch in result["cheats"]:
        paths = ch.get("paths") or []
        out.append(f"  cheat rule {ch['rule']}" + (f": {', '.join(paths[:5])}" + (f" and {len(paths) - 5} more" if len(paths) > 5 else "") if paths else ""))
    return out


def _show(v) -> str:
    return "none" if v is None else f"{v:.6g}"


def python() -> str:
    return sys.executable
