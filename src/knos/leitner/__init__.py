"""Leitner re-verification: proof is not checked once and trusted forever.

Every verified claim, product, lab, agent and sealed test sits in a box (config/leitner.yaml; default 1 -> 3 -> 7 ->
30 days, labs counted in orders). Passing a re-check moves the item up one box, so things that keep passing are
checked less and less; ANY failure drops it to box 1 and PAUSES its payouts until it passes again.

    s = Scheduler.load()                         the config, and the state file (KNOS_HOME/leitner/state.json)
    s.add("claim:42", "claim", now)              a newly verified item starts in box 1
    s.due(now)                                   what to re-check now (days), or s.due_orders("lab:x", n) (orders)
    s.result("claim:42", passed, now, cost=1)    promote, or demote to box 1 and pause
    s.can_pay("claim:42")                        False while paused: the lab vault demo (knos.labs.devnet) asks this first
    rotate(tests, pool, cfg)                     sealed tests nobody fails are retired; tests that catch cheats stay hot

    synthetic_history(...)  /  dashboard()       cost per verification before (re-check everything daily) and after
                                                 (Leitner), on a SYNTHETIC history, labelled synthetic everywhere

Cost is counted in re-runs (one re-run of an item's sealed checks = 1); what a re-run costs in USD has not been measured,
so no USD figure is given.
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DAY = 86_400
KINDS = ("claim", "product", "lab", "agent", "sealed_test")
DEFAULT: dict[str, Any] = {"version": 1, "default": {"unit": "days", "boxes": [1, 3, 7, 30]},
                           "kinds": {"lab": {"unit": "orders", "boxes": [1, 3, 7, 30]}},
                           "rotation": {"retire_after_clean_runs": 20, "hot_after_catch_runs": 10}}


class LeitnerError(ValueError):
    pass


def config_path() -> Path | None:
    named = os.environ.get("KNOS_LEITNER")
    if named:
        return Path(named)
    here = Path(__file__).resolve()
    for p in (here.parents[3] / "config" / "leitner.yaml", here.parents[1] / "_config" / "leitner.yaml"):   # tree, then wheel
        if p.is_file():
            return p
    return None


def load_config(path: Path | None = None) -> dict:
    """config/leitner.yaml, checked; the built-in default (the same boxes) when the file is absent (a wheel install)."""
    p = path or config_path()
    if p is None:
        cfg = DEFAULT
    else:
        from ..money.fees_config import read
        cfg = read(Path(p))
    problems = validate(cfg)
    if problems:
        raise LeitnerError("; ".join(problems))
    return cfg


def validate(cfg: Any) -> list[str]:
    out = []
    if not isinstance(cfg, dict):
        return ["the Leitner config is a mapping"]
    rows = [("default", cfg.get("default"))] + [(f"kinds.{k}", v) for k, v in (cfg.get("kinds") or {}).items()]
    for where, row in rows:
        if not isinstance(row, dict):
            out.append(f"{where}: a mapping of unit and boxes")
            continue
        if row.get("unit") not in ("days", "orders"):
            out.append(f"{where}.unit: days or orders")
        b = row.get("boxes")
        if not isinstance(b, list) or not b or any(isinstance(x, bool) or not isinstance(x, int) or x < 1 for x in b) or b != sorted(b):
            out.append(f"{where}.boxes: a rising list of whole numbers from 1")
    for k in (cfg.get("kinds") or {}):
        if k not in KINDS:
            out.append(f"kinds.{k}: one of {', '.join(KINDS)}")
    rot = cfg.get("rotation") or {}
    for k in ("retire_after_clean_runs", "hot_after_catch_runs"):
        v = rot.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
            out.append(f"rotation.{k}: a whole number from 1")
    return out


def schedule(cfg: dict, kind: str) -> dict:
    if kind not in KINDS:
        raise LeitnerError(f"kind: one of {', '.join(KINDS)}")
    return (cfg.get("kinds") or {}).get(kind) or cfg["default"]


@dataclass
class Item:
    id: str
    kind: str
    box: int = 0                 # index into the kind's boxes: 0 is "box 1"
    paused: bool = False
    next_due: int = 0            # a unix time (unit days) or an order count (unit orders)
    checks: int = 0
    failures: int = 0
    cost: float = 0.0
    last: str = ""               # "pass" | "fail" | ""

    @property
    def box_number(self) -> int:
        return self.box + 1


@dataclass
class Scheduler:
    cfg: dict = field(default_factory=lambda: load_config())
    items: dict[str, Item] = field(default_factory=dict)
    path: Path | None = None

    # -- state ----------------------------------------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None, cfg: dict | None = None) -> "Scheduler":
        if path is None:
            from .. import paths
            path = paths.home() / "leitner" / "state.json"
        state = Path(path)
        s = cls(cfg or load_config(), {}, state)
        if state.is_file():
            for row in json.loads(state.read_text(encoding="utf-8")).get("items", []):
                s.items[row["id"]] = Item(**row)
        return s

    def save(self) -> None:
        if self.path is None:
            raise LeitnerError("no state file named")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"v": 1, "items": [asdict(i) for i in self.items.values()]}, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # -- the boxes ------------------------------------------------------------------------------------------------
    def unit(self, kind: str) -> str:
        return schedule(self.cfg, kind)["unit"]

    def interval(self, kind: str, box: int) -> int:
        b = schedule(self.cfg, kind)["boxes"]
        return b[min(box, len(b) - 1)]

    def _next(self, it: Item, now: int) -> int:
        n = self.interval(it.kind, it.box)
        return now + n * DAY if self.unit(it.kind) == "days" else now + n

    def add(self, item_id: str, kind: str, now: int) -> Item:
        """A newly verified item: box 1, due one interval from `now` (a time, or the lab's order count)."""
        if item_id in self.items:
            return self.items[item_id]
        it = Item(item_id, kind)
        it.next_due = self._next(it, now)
        self.items[item_id] = it
        return it

    def due(self, now: int) -> list[Item]:
        """Items counted in days whose re-check is due at `now`, paused ones first (they wait to be paid)."""
        got = [i for i in self.items.values() if self.unit(i.kind) == "days" and i.next_due <= now]
        return sorted(got, key=lambda i: (not i.paused, i.next_due, i.id))

    def due_orders(self, item_id: str, orders: int) -> bool:
        """For an item counted in orders (a lab): is order number `orders` one to spot-check?"""
        it = self.items[item_id]
        return it.paused or orders >= it.next_due

    def result(self, item_id: str, passed: bool, now: int, cost: float = 1.0) -> Item:
        """A re-check's result. Pass: up one box (the top box stays), payouts resume. Fail: box 1, paused."""
        it = self.items[item_id]
        it.checks += 1
        it.cost += cost
        if passed:
            it.box = 0 if it.paused else min(it.box + 1, len(schedule(self.cfg, it.kind)["boxes"]) - 1)
            it.paused = False
            it.last = "pass"
        else:
            it.box, it.paused, it.last = 0, True, "fail"
            it.failures += 1
        it.next_due = self._next(it, now)
        return it

    def can_pay(self, item_id: str) -> bool:
        """Payouts and graduation go ahead only for an item that is known and not paused."""
        it = self.items.get(item_id)
        return it is not None and not it.paused

    def summary(self) -> dict:
        rows = list(self.items.values())
        return {"items": len(rows), "paused": sorted(i.id for i in rows if i.paused),
                "by_box": {str(b + 1): sum(1 for i in rows if i.box == b) for b in range(max([len(schedule(self.cfg, k)["boxes"]) for k in KINDS]))},
                "checks": sum(i.checks for i in rows), "cost_reruns": sum(i.cost for i in rows)}


def step(days: int, passed: bool, kind: str | None = None, cfg: dict | None = None) -> tuple[int, bool]:
    """One re-check on the ladder (default 1 -> 3 -> 7 -> 30 days; 30 stays 30): (next interval, paused). A pass moves
    up one rung; any failure goes back to the first rung and pauses payouts (paused True)."""
    boxes = (schedule(cfg or load_config(), kind) if kind else (cfg or load_config())["default"])["boxes"]
    if not passed:
        return boxes[0], True
    at = max([i for i, b in enumerate(boxes) if b <= days], default=-1)
    return boxes[min(at + 1, len(boxes) - 1)], False


# ---- sealed test rotation -------------------------------------------------------------------------------------------

def rotate(tests: list[dict], pool: list[dict], cfg: dict | None = None) -> dict:
    """tests: [{"id", "runs", "failures", "cheats_caught", "runs_since_catch"}]. A test nobody has failed in
    `retire_after_clean_runs` runs is retired and replaced from `pool`; a test that caught a cheat stays hot (re-run
    every time, box 1) until `hot_after_catch_runs` runs have passed since. Returns {"keep", "hot", "retired", "added"}."""
    rot = (cfg or load_config()).get("rotation") or DEFAULT["rotation"]
    retire_n, hot_n = rot["retire_after_clean_runs"], rot["hot_after_catch_runs"]
    keep, hot, retired = [], [], []
    for t in tests:
        if t.get("cheats_caught", 0) and t.get("runs_since_catch", 0) < hot_n:
            hot.append(t["id"])
            keep.append(t)
        elif t.get("failures", 0) == 0 and not t.get("cheats_caught", 0) and t.get("runs", 0) >= retire_n:
            retired.append(t["id"])
        else:
            keep.append(t)
    fresh = [p for p in pool if p["id"] not in {t["id"] for t in tests}][:len(retired)]
    return {"keep": [t["id"] for t in keep] + [p["id"] for p in fresh], "hot": hot, "retired": retired,
            "added": [p["id"] for p in fresh]}


# ---- cost per verification on a SYNTHETIC history -------------------------------------------------------------------

SYNTHETIC = ("SYNTHETIC: a made-up history (seeded random breakages), not measured on any real item. Cost is counted in "
             "re-runs; the USD cost of a re-run is not measured, so none is given.")


def synthetic_history(items: int = 60, days: int = 120, seed: int = 334, break_share: float = 0.15) -> list[dict]:
    """SYNTHETIC: `items` verified items; a `break_share` of them break once, on a random day, and stay broken until
    a re-check catches them (then they are fixed the next day). Seeded, so the same every time."""
    rng = random.Random(seed)
    out = []
    for n in range(items):
        breaks = rng.randrange(5, days - 5) if rng.random() < break_share else None
        out.append({"id": f"synthetic-{n:03d}", "kind": KINDS[n % 4] if KINDS[n % 4] != "lab" else "claim", "breaks_on": breaks,
                    "synthetic": True})
    return out


def simulate(history: list[dict], days: int, policy: str, cfg: dict | None = None) -> dict:
    """Run a policy over the history: "daily" (every item re-checked every day: box 1 forever) or "leitner".
    Returns re-runs, item-days kept verified, failures caught, the mean days a breakage went unseen, and the days a
    broken item could still be paid (it was not yet paused)."""
    cfg = cfg or load_config()
    s = Scheduler(cfg, {}, None)
    t0 = 0
    for h in history:
        s.add(h["id"], h["kind"], t0)
    broken: dict[str, int] = {}
    fixed_on: dict[str, int] = {}
    caught, delays, paid_while_broken = 0, [], 0
    reruns = 0
    for day in range(1, days + 1):
        now = day * DAY
        for h in history:
            if h["breaks_on"] == day and h["id"] not in fixed_on:
                broken[h["id"]] = day
            if fixed_on.get(h["id"]) == day:
                broken.pop(h["id"], None)
        todo = [it.id for it in s.items.values()] if policy == "daily" else [it.id for it in s.due(now)]
        for iid in todo:
            reruns += 1
            ok = iid not in broken
            s.result(iid, ok, now)
            if not ok and iid not in fixed_on:
                caught += 1
                delays.append(day - broken[iid])
                fixed_on[iid] = day + 1
        paid_while_broken += sum(1 for iid in broken if s.can_pay(iid))
    item_days = len(history) * days
    return {"policy": policy, "reruns": reruns, "item_days": item_days, "reruns_per_item_day": round(reruns / item_days, 4),
            "breakages": sum(1 for h in history if h["breaks_on"]), "caught": caught,
            "mean_days_unseen": round(sum(delays) / len(delays), 2) if delays else None,
            "max_days_unseen": max(delays) if delays else None, "payable_days_while_broken": paid_while_broken}


def dashboard(items: int = 60, days: int = 120, seed: int = 334, cfg: dict | None = None) -> dict:
    """The money dashboard's block: cost per verification before and after, on the SYNTHETIC history."""
    cfg = cfg or load_config()
    h = synthetic_history(items, days, seed)
    before, after = simulate(h, days, "daily", cfg), simulate(h, days, "leitner", cfg)
    return {"label": SYNTHETIC, "synthetic": True, "items": items, "days": days, "seed": seed,
            "boxes": {k: schedule(cfg, k) for k in KINDS}, "before": before, "after": after,
            "reruns_saved_share": round(1 - after["reruns"] / before["reruns"], 4) if before["reruns"] else None,
            "unit": "re-runs per item-day kept verified (one re-run of an item's sealed checks = 1)"}
