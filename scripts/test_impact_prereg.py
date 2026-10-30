"""test_impact_prereg: does Qloo's lift move launch cities toward where a kind of business is common per person?

The plan is docs/reference/impact_prereg_plan.md, committed with its sha256 before any prediction; this script refuses
--claude, --knos and --score while the plan file is untracked or differs from HEAD. Truth, candidates, the Claude
prompt, the name matching and the metric are D1's (scripts/test_where_truth.py, imported). Samples: the 6-digit NAICS
codes of sectors 44-45, 71, 72 and 81 present in cbp23msa, minus D1's 30, sorted; main random.Random(4).sample of 75,
replication random.Random(5).sample of 75 from the rest (with fewer than 150, half each by the same seeds).
Arms: (a) Claude alone; (b) population, top 5; (c) the 15 most populous candidates reranked by lift (mean cell affinity
/ population share among the 15; no cell = lift 0, after those with cells, by population), top 5; (d) (c) with the 15
lift values shuffled by random.Random(4); (e) metros.py's own launch ranking among the candidates, top 5.
Knos's Qloo calls per code: /v2/tags as check.py asks it, then the heatmap of the first tag check.py keeps
(check._tag_map_q). Every request is counted by this script's own client; it refuses to start when the calls already
counted plus 2 per code pass 1,000, and stops at 1,200. Answers are cached only in a private folder given on the
command line (never inside the repo). The public file docs/reference/impact_prereg.json holds derived CBSA codes and
counts only.

    python scripts/test_impact_prereg.py --truth <census folder> <scratch>/k6-truth.json
    python scripts/test_impact_prereg.py --claude <scratch>/k6-truth.json <scratch>/k6-claude.json
    python scripts/test_impact_prereg.py --knos <scratch>/k6-truth.json <scratch>/k6-knos.json <private cache folder>
    python scripts/test_impact_prereg.py --score <scratch>/k6-truth.json <scratch>/k6-claude.json <scratch>/k6-knos.json
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_where_truth as twt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "wanted"))
PLAN = ROOT / "docs" / "reference" / "impact_prereg_plan.md"
PUBLIC = ROOT / "docs" / "reference" / "impact_prereg.json"
SECTORS = ("44", "45", "71", "72", "81")
N_EACH, SEED_MAIN, SEED_REP = 75, 4, 5
TOP_POP, K, BOOT, BOOT_SEED, PLACEBO_SEED = 15, 5, 2000, 4, 4
CALLS_PER_CODE, START_LIMIT, STOP_LIMIT = 2, 1000, 1200
RENDER_SERVICE = "srv-db911jbbc2fs73cg3cc0"


class Refused(SystemExit):
    pass


# ---------------------------------------------------------------- the plan must be committed

def _git(args: list[str], cwd: Path) -> int:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).returncode


def plan_problem(plan: Path = PLAN, root: Path = ROOT, git=_git) -> str | None:
    """None when the plan file is tracked and equal to HEAD (nothing staged or unstaged), else why not."""
    rel = plan.relative_to(root).as_posix()
    if not plan.exists():
        return f"{rel} does not exist"
    if git(["ls-files", "--error-unmatch", "--", rel], root) != 0:
        return f"{rel} is not committed"
    if git(["diff", "--quiet", "HEAD", "--", rel], root) != 0:
        return f"{rel} differs from the committed version"
    return None


def require_plan(plan: Path = PLAN, root: Path = ROOT, git=_git) -> str:
    why = plan_problem(plan, root, git)
    if why:
        raise Refused(f"REFUSED: {why}; commit the plan before any prediction")
    sha = hashlib.sha256(plan.read_bytes()).hexdigest()
    print(f"plan {plan.relative_to(root).as_posix()} sha256 {sha}")
    return sha


# ---------------------------------------------------------------- samples and truth

def eligible(cbp_codes) -> list[str]:
    """6-digit codes of sectors 44-45, 71, 72 and 81, minus D1's 30, sorted."""
    return sorted({c for c in cbp_codes if len(c) == 6 and c.isdigit() and c[:2] in SECTORS} - set(twt.CODES))


def draw(codes: list[str]) -> tuple[list[str], list[str]]:
    """Main: random.Random(4).sample of 75 over the sorted codes; replication: random.Random(5).sample of 75 of the
    rest. With fewer than 150 codes, each draws len // 2 by the same seeds."""
    pool = sorted(codes)
    each = N_EACH if len(pool) >= 2 * N_EACH else len(pool) // 2
    main = random.Random(SEED_MAIN).sample(pool, each)
    rest = [c for c in pool if c not in set(main)]
    return main, random.Random(SEED_REP).sample(rest, each)


def truth(folder: str, out: str) -> int:
    d = Path(folder)
    pop, names = {}, {}
    with open(d / "cbsa-est2023-alldata.csv", encoding="latin-1") as f:
        for r in csv.DictReader(f):
            if r["LSAD"] == "Metropolitan Statistical Area" and int(r["POPESTIMATE2023"]) >= twt.MIN_POP:
                pop[r["CBSA"]], names[r["CBSA"]] = int(r["POPESTIMATE2023"]), r["NAME"]
    with open(d / "naics2017.txt", encoding="latin-1") as f:
        titles = {row[0].strip(): row[1].strip() for row in csv.reader(f) if row}
    est: dict[str, dict[str, int]] = {}
    with zipfile.ZipFile(d / "cbp23msa.zip") as z:
        for row in csv.DictReader(io.TextIOWrapper(z.open("cbp23msa.txt"), encoding="latin-1")):
            c = row["naics"]
            if len(c) == 6 and c.isdigit() and c[:2] in SECTORS:
                cell = est.setdefault(c, {})
                if row["msa"] in pop:
                    cell[row["msa"]] = int(row["est"])
    codes = eligible(est)
    main, rep = draw(codes)
    rows, dropped = [], []
    for sample, chosen in (("main", main), ("replication", rep)):
        for c in chosen:
            if not est[c]:
                dropped.append(c)
                continue
            rate = sorted(((v / pop[m] * 100_000, m) for m, v in est[c].items()), key=lambda x: (-x[0], x[1]))
            rows.append({"naics": c, "sample": sample, "title": titles.get(c, c), "top10": [m for _, m in rate[:twt.TOP]],
                         "rates": [round(r, 3) for r, _ in rate[:twt.TOP]]})
    top15 = sorted(pop, key=lambda m: (-pop[m], m))[:TOP_POP]
    doc = {"columns": {"cbp": ["msa", "naics", "est"], "population": ["CBSA", "LSAD", "POPESTIMATE2023", "NAME"]},
           "sectors": list(SECTORS), "excluded_d1": sorted(set(twt.CODES) & set(est)), "eligible": codes, "n_eligible": len(codes),
           "main": main, "replication": rep, "dropped": dropped,
           "candidates": [{"cbsa": m, "name": names[m], "pop": pop[m]} for m in sorted(pop)], "top15": top15, "codes": rows}
    Path(out).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(f"{len(pop)} candidate metros; {len(est)} codes in the sectors, {len(doc['excluded_d1'])} of them D1's; "
          f"n eligible {len(codes)}; main {len(main)}, replication {len(rep)}; dropped {dropped}")
    print("main", " ".join(main))
    print("replication", " ".join(rep))
    return 0


# ---------------------------------------------------------------- the rankings

def metro_means(cells: list[dict], where=None) -> dict[str, tuple[float, int]]:
    """CBSA -> (mean cell affinity, cell count), each cell placed by metros.py (TIGER/Line 2023)."""
    if where is None:
        from knos_wanted import metros
        where = metros.metro
    acc: dict[str, list[float]] = {}
    for c in cells or []:
        a = c.get("affinity")
        m = where(c.get("lat"), c.get("lon"))
        if m and isinstance(a, (int, float)):
            acc.setdefault(m["cbsa"], []).append(float(a))
    return {k: (sum(v) / len(v), len(v)) for k, v in acc.items()}


def rank_pop(top15: list[str]) -> list[str]:
    return list(top15[:K])


def lifts(top15: list[str], pop: dict[str, int], means: dict[str, tuple[float, int]]) -> list[float]:
    """Lift of each of the 15 (in their order): mean affinity / population share among the 15; 0 with no cell."""
    total = sum(pop[m] for m in top15)
    return [means[m][0] / (pop[m] / total) if m in means else 0.0 for m in top15]


def _by_lift(top15: list[str], pop: dict[str, int], lift: list[float], has: list[bool]) -> list[str]:
    order = sorted(range(len(top15)), key=lambda i: (not has[i], -lift[i], -pop[top15[i]], top15[i]))
    return [top15[i] for i in order][:K]


def rank_lift15(top15: list[str], pop: dict[str, int], means: dict[str, tuple[float, int]]) -> list[str]:
    """(c): the 15 by lift, those with cells first; the rest by population."""
    return _by_lift(top15, pop, lifts(top15, pop, means), [m in means for m in top15])


def rank_placebo(top15: list[str], pop: dict[str, int], means: dict[str, tuple[float, int]], rng: random.Random) -> list[str]:
    """(d): (c) with the 15 lift values shuffled across the 15 by rng; a shuffled 0 sorts after, by population."""
    lv = lifts(top15, pop, means)
    rng.shuffle(lv)
    return _by_lift(top15, pop, lv, [x > 0 for x in lv])


def rank_pure(cells: list[dict], cands: set[str], stats=None) -> list[str]:
    """(e): metros.py's own launch ranking (metros.stats order: lift among the metros with cells), candidates only."""
    if stats is None:
        from knos_wanted import metros
        stats = metros.stats
    return [r["cbsa"] for r in stats(cells) if r["cbsa"] in cands][:K]


def overlap(top5: list[str], top10) -> float:
    return len(set(top5[:K]) & set(top10)) / K


def bootstrap(pairs: dict[str, list[tuple[float, float]]], seed: int = BOOT_SEED, n_boot: int = BOOT) -> dict[str, list[float]]:
    """Paired percentile bootstrap: one rng, one set of resampled code indexes shared by every contrast.
    pairs: contrast -> [(x, y) per code], difference x - y."""
    n = len(next(iter(pairs.values())))
    rng = random.Random(seed)
    diffs: dict[str, list[float]] = {k: [] for k in pairs}
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        for k, v in pairs.items():
            diffs[k].append(sum(v[i][0] - v[i][1] for i in idx) / n)
    out = {}
    for k, d in diffs.items():
        d.sort()
        out[k] = [round(d[int(0.025 * n_boot)], 4), round(d[int(0.975 * n_boot) - 1], 4)]
    return out


# ---------------------------------------------------------------- the counted Qloo client

class Stop(Exception):
    pass


class Counted:
    """Every request counted (a cached answer is not a request), the count kept in the private folder. get() returns
    (status, derived) where derived is the small part the test reads, never a whole body."""

    def __init__(self, folder: str, send, stop_at: int = STOP_LIMIT):
        self.dir = Path(folder).resolve()
        if self.dir == ROOT or ROOT in self.dir.parents:
            raise Refused("REFUSED: the cache folder is inside the repo")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.count_file = self.dir / "calls.json"
        self.calls = json.loads(self.count_file.read_text(encoding="utf-8"))["calls"] if self.count_file.exists() else 0
        self.send, self.stop_at = send, stop_at

    def _save(self):
        self.count_file.write_text(json.dumps({"calls": self.calls}), encoding="utf-8")

    def get(self, path: str, params: dict, derive) -> tuple[int | None, object]:
        key = hashlib.sha256((path + "?" + json.dumps(params, sort_keys=True, default=str)).encode()).hexdigest()
        f = self.dir / f"{key}.json"
        if f.exists():
            got = json.loads(f.read_text(encoding="utf-8"))
            return got["status"], got["derived"]
        if self.calls >= self.stop_at:
            raise Stop(f"stopped at {self.calls} Qloo calls (limit {self.stop_at})")
        self.calls += 1
        self._save()
        status, body = self.send(path, params)
        if status == 429:
            raise Stop(f"Qloo answered 429 on call {self.calls}")
        derived = derive(body) if status == 200 else None
        f.write_text(json.dumps({"status": status, "derived": derived}), encoding="utf-8")
        return status, derived


def _live_send():
    """The server's Qloo key, read in memory from the Render service environment; never printed or stored."""
    import urllib.error
    import urllib.parse
    import urllib.request
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        rk = winreg.QueryValueEx(k, "RENDER_API_KEY")[0]
    req = urllib.request.Request(f"https://api.render.com/v1/services/{RENDER_SERVICE}/env-vars?limit=100",
                                 headers={"Authorization": "Bearer " + rk, "Accept": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=60))
    env = {(x.get("envVar") or x)["key"]: (x.get("envVar") or x).get("value") for x in r}
    key, base = env.get("QLOO_API_KEY") or "", (env.get("QLOO_BASE_URL") or "").rstrip("/")
    if not key or not base:
        raise Refused("REFUSED: the Render service has no Qloo key or base URL")

    def send(path: str, params: dict):
        q = urllib.request.Request(base + path + "?" + urllib.parse.urlencode(params), headers={"x-api-key": key, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(q, timeout=60) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, None
        except (urllib.error.URLError, TimeoutError, ValueError):
            return None, None
    return send


def _no_send(path: str, params: dict):
    raise Stop(f"no sender for {path}")


def tag_query(title: str) -> tuple[dict, list[str]]:
    """check.gather's /v2/tags question for the title, and the content words its keep rule reads."""
    from knos_wanted import check
    words = check.content_words(title)
    drop = check.kind_words() | {check._norm(w) for w in check.PLACE_NOUNS}
    q_words = [w for w in words if w not in drop] or words
    return ({"filter.query": " ".join(q_words[:6]), "feature.semantic_search": "true", "feature.typo_tolerance": "true", "take": 8},
            words)


def kept_tags(tags: list[dict], words: list[str]) -> list[dict]:
    """check.gather's rule: a tag whose name shares a content word with the idea, one per id and one per name."""
    from knos_wanted import check
    out: list[dict] = []
    for t in tags or []:
        if (t.get("id") and t["id"] not in {x["id"] for x in out} and {check._norm(x) for x in check.tokens(t.get("name"))} & set(words)
                and str(t.get("name") or "").lower() not in {str(x["name"] or "").lower() for x in out}):
            out.append({"id": t["id"], "name": t.get("name")})
    return out


def _tags_of(body) -> list[dict]:
    return [{"id": t.get("id"), "name": t.get("name")} for t in (((body or {}).get("results") or {}).get("tags") or [])]


def _cells_of(body) -> list[dict]:
    from knos_wanted import check
    return [{"lat": (h.get("location") or {}).get("latitude"), "lon": (h.get("location") or {}).get("longitude"),
             "affinity": (h.get("query") or {}).get("affinity")}
            for h in (((body or {}).get("results") or {}).get("heatmap") or [])[:check.HEAT_CELLS]]


def knos_arm(truth_file: str, out: str, cache: str, send=None, plan_sha: str | None = None) -> int:
    from knos_wanted import check, metros
    sha = plan_sha or require_plan()
    t = json.loads(Path(truth_file).read_text(encoding="utf-8"))
    client = Counted(cache, send or _no_send)
    planned = CALLS_PER_CODE * len(t["codes"])
    if client.calls + planned > START_LIMIT:
        raise Refused(f"REFUSED: {client.calls} calls counted + {planned} planned passes {START_LIMIT}")
    if send is None:
        client.send = _live_send()
    pop = {c["cbsa"]: c["pop"] for c in t["candidates"]}
    cands, top15 = set(pop), t["top15"]
    rngs = {"main": random.Random(PLACEBO_SEED), "replication": random.Random(PLACEBO_SEED)}
    rows, stopped = [], None
    for r in t["codes"]:
        try:
            q, words = tag_query(r["title"])
            s_tags, tags = client.get("/v2/tags", q, _tags_of)
            kept = kept_tags(tags or [], words)
            s_map, cells = None, []
            if kept:
                s_map, cells = client.get("/v2/insights", check._tag_map_q(kept[0]["id"], None), _cells_of)
                cells = cells or []
        except Stop as e:
            stopped = str(e)
            break
        flat = metros.flat(cells)
        used = [] if flat else cells
        means = metro_means(used)
        rows.append({"naics": r["naics"], "sample": r["sample"], "status": [s_tags, s_map], "tags_kept": len(kept),
                     "cells": len(cells), "flat": flat, "metros_15_with_cells": sum(1 for m in top15 if m in means),
                     "pop_top5": rank_pop(top15), "top5": rank_lift15(top15, pop, means),
                     "placebo_top5": rank_placebo(top15, pop, means, rngs[r["sample"]]), "pure_top5": rank_pure(used, cands)})
        print(r["naics"], r["sample"], "tags", len(kept), "cells", len(cells), "c", rows[-1]["top5"], f"calls {client.calls}", flush=True)
    Path(out).write_text(json.dumps({"plan_sha256": sha, "qloo_calls": client.calls, "stopped": stopped, "rows": rows}, indent=1), encoding="utf-8")
    print(f"Qloo calls counted: {client.calls}" + (f"; {stopped}" if stopped else ""))
    if stopped and client.calls <= 1 and "429" in stopped:
        print("BLOCKED test_impact_prereg: Qloo answered 429 at the start; not run")
    return 1 if stopped else 0


def claude_arm(truth_file: str, out: str) -> int:
    require_plan()
    return twt.claude_arm(truth_file, out)


# ---------------------------------------------------------------- score

def score_sample(codes: list[str], top10: dict, arms: dict[str, dict[str, list[str]]], seed: int = BOOT_SEED) -> dict:
    ov = {a: {c: overlap(arms[a][c], top10[c]) for c in codes} for a in arms}
    pairs = {f"c-{x}": [(ov["c"][c], ov[x][c]) for c in codes] for x in ("a", "b", "d")}
    iv = bootstrap(pairs, seed)
    means = {a: round(sum(ov[a].values()) / len(codes), 4) for a in arms}
    diff = {k: round(means["c"] - means[k[2:]], 4) for k in pairs}
    return {"n": len(codes), "mean_overlap": means, "difference": diff, "interval_95": iv, "per_code": ov}


def verdict(main: dict, rep: dict) -> bool:
    """K6: on the main sample (c)-(a), (c)-(b) and (c)-(d) intervals all above 0; the replication's three
    differences have the same sign (above 0)."""
    return (all(main["interval_95"][k][0] > 0 for k in ("c-a", "c-b", "c-d"))
            and all(rep["difference"][k] > 0 for k in ("c-a", "c-b", "c-d")))


def score(truth_file: str, claude_file: str, knos_file: str) -> int:
    sha = require_plan()
    t = json.loads(Path(truth_file).read_text(encoding="utf-8"))
    ca = json.loads(Path(claude_file).read_text(encoding="utf-8"))
    kn = json.loads(Path(knos_file).read_text(encoding="utf-8"))
    top10 = {r["naics"]: r["top10"] for r in t["codes"]}
    a = {r["naics"]: r["top5"] for r in ca["rows"]}
    kr = {r["naics"]: r for r in kn["rows"]}
    res, missing = {}, {}
    for sample in ("main", "replication"):
        want = [r["naics"] for r in t["codes"] if r["sample"] == sample]
        codes = [c for c in want if c in a and c in kr]
        missing[sample] = [c for c in want if c not in codes]
        arms = {"a": {c: a[c] for c in codes}, "b": {c: kr[c]["pop_top5"] for c in codes}, "c": {c: kr[c]["top5"] for c in codes},
                "d": {c: kr[c]["placebo_top5"] for c in codes}, "e": {c: kr[c]["pure_top5"] for c in codes}}
        res[sample] = score_sample(codes, top10, arms) if codes else None
    ok = bool(res["main"] and res["replication"]) and not any(missing.values()) and not kn.get("stopped") and verdict(res["main"], res["replication"])
    names = {"a": "claude_alone", "b": "population", "c": "lift_of_top15", "d": "placebo", "e": "pure_lift"}
    doc = {"made": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "plan": "docs/reference/impact_prereg_plan.md",
           "plan_sha256": sha, "n_eligible": t["n_eligible"], "qloo_calls": kn.get("qloo_calls"), "stopped": kn.get("stopped"),
           "missing": missing, "arms": names, "metric": "overlap at 5 with the Census top 10, divided by 5",
           "bootstrap": {"resamples": BOOT, "seed": BOOT_SEED, "paired": True}, "pass": ok,
           "claude": {"claude_code": ca.get("claude_code"), "models": ca.get("models")}, "samples": {}}
    for sample, s in res.items():
        if not s:
            continue
        doc["samples"][sample] = {"n": s["n"], "mean_overlap": {names[k]: v for k, v in s["mean_overlap"].items()},
                                  "difference": s["difference"], "interval_95": s["interval_95"],
                                  "codes_with_cells": sum(1 for r in kn["rows"] if r["sample"] == sample and r["cells"] and not r["flat"]),
                                  "per_code": [{"naics": c, "truth_top10": top10[c], "a": a[c], "b": kr[c]["pop_top5"], "c": kr[c]["top5"],
                                                "d": kr[c]["placebo_top5"], "e": kr[c]["pure_top5"]} for c in s["per_code"]["c"]]}
    PUBLIC.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    lines = [f"plan {doc['plan']} sha256 {sha}", f"claude: {doc['claude']}", f"Qloo calls {doc['qloo_calls']}"]
    for sample, s in res.items():
        if s:
            m, iv, d = s["mean_overlap"], s["interval_95"], s["difference"]
            lines.append(f"{sample} n {s['n']}: a {m['a']:.3f} b {m['b']:.3f} c {m['c']:.3f} d {m['d']:.3f} e {m['e']:.3f}; "
                         + "; ".join(f"{k} {d[k]:+.3f} [{iv[k][0]:+.3f}, {iv[k][1]:+.3f}]" for k in ("c-a", "c-b", "c-d")))
    lines.append(f"{'PASS' if ok else 'FAIL'} test_impact_prereg: n eligible {t['n_eligible']}, Qloo calls {doc['qloo_calls']}, "
                 f"missing {sum(len(v) for v in missing.values())}")
    print("\n".join(lines))
    (Path(knos_file).parent / "test_impact_prereg.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = {"--truth": truth, "--claude": claude_arm, "--knos": knos_arm, "--score": score}[args[0]]
    sys.exit(mode(*args[1:]))
