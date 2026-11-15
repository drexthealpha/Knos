"""A spend cap on your agents: once today's (or this week's, or month's) spend reaches it, edits are refused.

The cap is enforced where knos already stands, at the edit guard: an agent past the cap is told so, in one line,
with the command that raises it. It is a cap on spend measured at API list prices from the agents' own logs, so it
lags by at most one model call, and it stops work rather than billing: nothing is charged anywhere.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .. import paths

PERIODS = ("day", "week", "month")
CHECK_EVERY = 60.0  # seconds between reads of the agents' logs from the guard


def path() -> Path:
    return paths.home() / "budget.json"


def get() -> dict | None:
    try:
        got = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(got, dict) or float(got.get("usd", 0)) <= 0 or got.get("per") not in PERIODS:
        return None
    return got


def set_cap(usd: float, per: str = "day", repo: str | None = None) -> dict:
    """`repo` limits what counts toward the cap to agent sessions working in that repo (or inside it)."""
    if usd <= 0:
        raise ValueError("a cap is a positive number of dollars")
    if per not in PERIODS:
        raise ValueError(f"per must be one of {', '.join(PERIODS)}")
    body = {"usd": round(float(usd), 2), "per": per, "set_at": datetime.now(timezone.utc).isoformat()}
    if repo:
        body["repo"] = str(Path(repo).resolve())
    path().write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return body


def raise_cap(by: float) -> dict:
    cur = get()
    if cur is None:
        raise ValueError("no cap is set")
    return set_cap(float(cur["usd"]) + by, cur["per"], cur.get("repo"))


def clear() -> bool:
    try:
        path().unlink()
        return True
    except FileNotFoundError:
        return False


def state(refresh_every: float = 0.0) -> dict | None:
    """None when no cap is set; else {'usd', 'per', 'spent', 'over', 'estimated'}."""
    cap = get()
    if cap is None:
        return None
    from . import meter

    meter.update(min_interval=refresh_every)
    start = meter.period_start(cap["per"])
    got = meter.spent(start, repo=cap.get("repo"))
    paid = 0.0
    if (paths.home() / "agentpay.db").exists():  # one budget: model tokens plus what agents paid APIs
        from . import agentpay

        paid = agentpay.spent(since=start.timestamp())
    total = got["usd"] + paid
    return {"usd": float(cap["usd"]), "per": cap["per"], "spent": total, "tokens_usd": got["usd"], "paid_usd": paid,
            "over": total >= float(cap["usd"]), "estimated": got["estimated"], "repo": cap.get("repo")}


# ---- agent budget wallets: which agent has which wallet, and its Knos cap ----------------------

def _agents_path() -> Path:
    return paths.home() / "agents.json"


def agents() -> dict:
    try:
        got = json.loads(_agents_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def set_agent(agent: str, chain: str, network: str, cap: float, address: str) -> dict:
    all_ = agents()
    all_[agent] = {"chain": chain, "network": network, "cap": round(float(cap), 6), "address": address}
    _agents_path().write_text(json.dumps(all_, indent=2) + "\n", encoding="utf-8")
    return all_[agent]


def refusal(repo: str | Path | None = None) -> str | None:
    """For the edit guard: a one-line refusal when a licensed cap is reached, else None. Never raises. A cap scoped to
    one repo refuses only edits in that repo."""
    try:
        cap = get()
        if cap is None:
            return None
        if cap.get("repo") and repo is not None:
            here = str(Path(repo).resolve())
            if not (here == cap["repo"] or here.startswith(cap["repo"].rstrip("/\\") + os.sep)):
                return None
        from . import licence

        if not licence.status()["active"]:
            return None
        s = state(refresh_every=CHECK_EVERY)
        if not s or not s["over"]:
            return None
        scope = f" for {Path(s['repo']).name}" if s.get("repo") else ""
        return (f"knos: this {s['per']}'s agent spend cap{scope} of ${s['usd']:.2f} is reached (${s['spent']:.2f} at "
                f"API list prices, including agents' API payments). A person can raise it: knos budget raise 10")
    except Exception:
        return None
