"""`knos outcome draft`: a plain-English goal and a sample of the buyer's data in, a draft outcome.yaml out.

By default nothing leaves the machine: the goal's words pick a template (support resolution, conversion, time taken,
value per item, or a generic yes/no result) and the sample's columns fill it (the id, the time, the field the metric
reads). With `--llm` and the user's own Anthropic key (named by `--llm-key-env`, read from the environment, never
written anywhere), Claude drafts the spec instead; whatever it returns is checked against the schema exactly like a
hand-written spec, and the template's draft is kept when it does not hold.

A draft is a starting point, not terms: the parties read it, fix the numbers, sign its hash (`knos outcome sign`),
and only then fund it. Everything a draft cannot know is written as a value that fails validation or is marked
`EDIT` in a comment: the parties' GitHub ids, the seller's address, the escrow.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import data as data_mod
from . import yamlish
from .spec import problems

MODEL = "claude-opus-5-5"
PLACEHOLDER_ADDRESS = "11111111111111111111111111111111"     # the system program: a valid address that pays nobody; EDIT

TEMPLATES = {
    "support": {"words": ("ticket", "support", "resolv", "solve", "help desk", "helpdesk", "customer service", "deflect"),
                "metric": "resolved_without_human", "direction": "higher", "lift": "relative",
                "want": ("resolved", "solved", "status", "escalated", "reopened")},
    "conversion": {"words": ("convert", "conversion", "purchase", "sign up", "signup", "checkout", "activate", "retain"),
                   "metric": "converted", "direction": "higher", "lift": "relative", "want": ("converted", "purchased", "signed_up", "activated")},
    "time": {"words": ("faster", "time to", "latency", "minutes", "hours", "duration", "wait", "quicker"),
             "metric": "time_taken", "direction": "lower", "lift": "relative", "want": ("minutes", "seconds", "hours", "duration", "time")},
    "value": {"words": ("revenue", "spend", "order value", "basket", "value", "sales", "margin"),
              "metric": "value_per_item", "direction": "higher", "lift": "relative", "want": ("revenue", "value", "amount", "total", "spend")},
}


def sample_rows(path: Path, limit: int = 200) -> list[dict]:
    raw = path.read_bytes()
    fmt = "csv" if path.suffix.lower() == ".csv" else "jsonl" if path.suffix.lower() == ".jsonl" else "json"
    rows = data_mod.parse(raw, fmt)
    return rows[:limit]


def _fmt_of(path: Path) -> str:
    s = path.suffix.lower()
    return "csv" if s == ".csv" else "jsonl" if s == ".jsonl" else "json"


def pick_template(goal: str) -> str:
    g = goal.lower()
    best, score = "generic", 0
    for name, t in TEMPLATES.items():
        n = sum(1 for w in t["words"] if w in g)
        if n > score:
            best, score = name, n
    return best


def _id_field(cols: list[str]) -> str:
    for c in cols:
        if c.lower() in ("id", "item_id") or c.lower().endswith("_id"):
            return c
    return cols[0]


def _time_field(rows: list[dict], cols: list[str]) -> str:
    for c in cols:
        if any(w in c.lower() for w in ("created", "time", "date", "_at", "opened")):
            try:
                data_mod.when(rows[0][c])
                return c
            except (data_mod.DataError, KeyError):
                continue
    return "created_at"


def _binary(rows: list[dict], c: str) -> bool:
    vals = {r.get(c) for r in rows}
    return bool(vals) and vals <= {0, 1, True, False, None}


def _numeric(rows: list[dict], c: str) -> bool:
    return all(isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool) for r in rows if r.get(c) is not None)


def formula_for(template: str, rows: list[dict], cols: list[str]) -> tuple[str, str]:
    """(the formula, a note on what it reads)."""
    low = {c.lower(): c for c in cols}
    if template == "support":
        parts = []
        if "status" in low:
            solved = sorted({str(r.get(low["status"])) for r in rows if str(r.get(low["status"])).lower() in ("solved", "resolved", "closed")})
            if solved:
                parts.append(f"{low['status']} == {solved[0]!r}")
        for neg in ("escalated", "reopened", "human_replied", "handoff"):
            if neg in low and _binary(rows, low[neg]):
                parts.append(f"{low[neg]} == 0")
        for pos in ("resolved", "solved"):
            if pos in low and _binary(rows, low[pos]) and not parts:
                parts.append(f"{low[pos]} == 1")
        if parts:
            return f"1 if {' and '.join(parts)} else 0", "an item counts 1 when it was solved with no escalation and no reopening"
    want = TEMPLATES.get(template, {}).get("want", ())
    for w in want:
        for c in cols:
            if w in c.lower():
                if _binary(rows, c):
                    return f"1 if {c} else 0", f"{c} is 1 for a success"
                if _numeric(rows, c):
                    return c, f"the value of {c}"
    for c in cols:
        if _binary(rows, c):
            return f"1 if {c} else 0", f"{c} is 1 for a success (EDIT: check this is the result you pay for)"
    return "0", "EDIT: no yes/no or numeric column was found; write the formula"


def template_draft(goal: str, rows: list[dict], data_path: str, fmt: str, *, synthetic: bool, now: datetime | None = None) -> tuple[dict, dict]:
    """(the draft spec, comments to write above its keys)."""
    if not rows:
        raise ValueError("the sample has no rows")
    cols = list(rows[0].keys())
    t = pick_template(goal)
    formula, note = formula_for(t, rows, cols)
    tpl = TEMPLATES.get(t, {"metric": "success", "direction": "higher", "lift": "relative"})
    now = now or datetime.now(timezone.utc)
    start = (now + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=28)
    fmt_t = "%Y-%m-%dT%H:%M:%SZ"
    spec: dict[str, Any] = {
        "version": 1,
        "title": goal.strip().rstrip(".")[:120] or "A measured result",
        "synthetic": synthetic,
        "parties": {"buyer": {"github": "EDIT-buyer", "id": 1}, "seller": {"github": "EDIT-seller", "id": 1, "address": PLACEHOLDER_ADDRESS}},
        "metric": {"name": tpl["metric"], "formula": formula, "aggregate": "mean", "direction": tpl["direction"], "lift": tpl["lift"]},
        "data": {"source": "file", "path": data_path, "format": fmt, "id_field": _id_field(cols), "time_field": _time_field(rows, cols), "synthetic": synthetic},
        "window": {"start": start.strftime(fmt_t), "end": end.strftime(fmt_t)},
        "control": {"share": 0.2, "salt": secrets.token_hex(16)},
        "success": {"min_lift": 0.05, "confidence": 0.95},
        "bootstrap": {"resamples": 2000, "seed": int.from_bytes(secrets.token_bytes(4), "big")},
        "price": {"currency": "USDC", "unit_price": 1.0, "cap": 30.0},
        "tiers": [{"name": "lift-5", "min_lift": 0.05, "amount": 5.0}, {"name": "lift-10", "min_lift": 0.10, "amount": 10.0},
                  {"name": "lift-20", "min_lift": 0.20, "amount": 15.0}],
        "dispute_window_days": 7,
        "escrow": {"cluster": "devnet", "repository": "EDIT/repository", "repository_id": 1, "issue": 1, "funder": PLACEHOLDER_ADDRESS,
                   "mint": PLACEHOLDER_ADDRESS, "seq_start": 0, "work_seconds": int((end - now).total_seconds()) + 14 * 86_400},
    }
    comments = {
        "title": f"DRAFT made by `knos outcome draft` from a template ({t}). Read every line; EDIT marks what a draft cannot know.",
        "parties": "EDIT: both GitHub accounts and their numeric ids; the seller's Solana address is where the tiers pay.",
        "metric": f"The formula: {note}.",
        "window": "Opens a week from the draft, for 28 days. Fund before it opens: the salt and the window are fixed then.",
        "control": "A public salt, made at random now. Items whose hash falls below `share` are the control group.",
        "tiers": "One order per tier; the amounts add up to the cap. A tier pays when the lower confidence bound of the lift reaches its min_lift.",
        "escrow": "EDIT: the repository whose prove.yml measures, its numeric id, the issue, the funding wallet and the mint. Devnet only.",
    }
    if synthetic:
        comments["synthetic"] = "The sample is SYNTHETIC (made up): every result and record made from this spec says so."
    return spec, comments


def llm_draft(goal: str, rows: list[dict], fallback: dict, key: str, model: str = MODEL) -> dict | None:
    """Claude's draft, through the Anthropic SDK with the user's own key; None when the SDK is missing, the model
    declines, or the answer is not a spec that holds (the template's draft is used instead)."""
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError:
        return None
    client = anthropic.Anthropic(api_key=key)
    sample = json.dumps(rows[:20], default=str)[:12_000]
    prompt = ("Draft a Knos outcome spec as one JSON object, nothing else. Keep the shape and every key of this starting draft; change "
              "only metric.formula, metric.name, metric.direction, metric.lift, data.id_field, data.time_field, title and the tiers' min_lift "
              "values so that they fit the goal and the data. The formula is a Python-like expression over one row's fields that gives a number.\n\n"
              f"Goal: {goal}\n\nStarting draft:\n{json.dumps(fallback)}\n\nFirst rows of the buyer's data:\n{sample}")
    resp = client.beta.messages.create(model=model, max_tokens=16000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                       messages=[{"role": "user", "content": prompt}])
    if resp.stop_reason == "refusal":
        return None
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return None
    for k in ("parties", "escrow", "control", "bootstrap", "synthetic", "price", "data"):
        if k in fallback and k != "data":
            got[k] = fallback[k]          # what the parties fix themselves is never the model's
    if isinstance(got.get("data"), dict):
        got["data"] = {**fallback["data"], **{k: v for k, v in got["data"].items() if k in ("id_field", "time_field")}}
    return got if not [p for p in problems(got) if "EDIT" not in p and "address" not in p] else None


def draft(goal: str, sample: Path, *, data_path: str | None = None, synthetic: bool = False, llm: bool = False, key_env: str | None = None,
          env: dict | None = None, now: datetime | None = None) -> tuple[str, dict, str]:
    """(the YAML text, the spec, how it was made: "template" or "llm")."""
    rows = sample_rows(sample)
    spec, comments = template_draft(goal, rows, data_path or sample.name, _fmt_of(sample), synthetic=synthetic, now=now)
    how = "template"
    if llm:
        env = os.environ if env is None else env
        if not key_env or not env.get(key_env):
            raise ValueError("--llm needs your own key: pass --llm-key-env NAME with the key in that environment variable")
        got = llm_draft(goal, rows, spec, env[key_env])
        if got is not None:
            spec, how = got, "llm"
            comments["title"] = f"DRAFT made by `knos outcome draft --llm` ({MODEL}, your key). Read every line; EDIT marks what a draft cannot know."
    return yamlish.dumps(spec, comments), spec, how


def sample_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
