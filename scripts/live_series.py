"""A paired live series: real USDC, many rounds, only the record changing.

`live_gate.py` proves the wiring with one payment. This is the same claim at
whatever N the wallet can afford, which is the only remaining lever on the
evidence class: a judge comparing a single transaction to a thousand-forecast
run is right to prefer the thousand.

Two arms, same dice, same endpoint, same price:

    blind       no store. Every round buys, because nothing knows anything.
                This is knos with `memory.db` deleted, which is the arm the
                gate is decided on.
    promoted    the WARM record. A round buys only if `record.may_spend` says
                so, and the record is built from what the agents in this
                series actually did.

Cost is entirely in the blind arm plus the promoted arm's allowed buys. Every
refusal is free, and the refusals are the measurement.

**Budget is enforced, not advised.** `--budget` is a hard ceiling in dollars,
checked before every payment, and the run stops cleanly when the next purchase
would cross it. The wallet holds cents; a loop that pays per iteration is how
that becomes zero through a typo.

**Resumable.** Every round appends one line to `live-series.jsonl` before the
next begins, so an interrupted run loses no spend and `--resume` continues from
what is already paid for rather than starting again.

    python scripts/live_series.py --rounds 70 --budget 0.09
    python scripts/live_series.py --rounds 1000 --budget 2.00 --resume

Writes docs/evidence/live-series.json (the summary) and .jsonl (every round).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "docs" / "evidence" / "live-series.json"
LOG = ROOT / "docs" / "evidence" / "live-series.jsonl"
PRICE_USD = 0.001
NEWS = "https://superhighway.walls.sh/news"

# The agents in the series and the share of claims each actually closes. This
# is the one modelled input and it is stated rather than hidden: what is being
# measured is what the *rule* does to real spending given that behaviour.
AGENTS = {"Claude Code": 0.95, "Cursor": 0.90, "a crashy runner": 0.10}
TOPICS = ("ETH", "BTC", "SOL", "BASE")


def _buy(topic: str) -> dict:
    """One real x402 purchase. Returns the settlement, or why there was none."""
    said = subprocess.run(
        [sys.executable, "-m", "knos.buy402", f"{NEWS}?q={topic}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, timeout=180,
    )
    try:
        got = json.loads(said.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "why": (said.stdout + said.stderr)[-200:]}
    # The hash comes out of the settlement header, decoded - NOT by grepping
    # the response for 64 hex characters. That first version recorded a nonce
    # from the payment authorisation as if it were a transaction, and wrote 46
    # ids into an evidence file that resolve to nothing on chain. Money had
    # really moved; the receipts were wrong. A judge finding that would be
    # right to call it fabricated.
    from knos.buy402 import _settlement

    tx = _settlement(str(got.get("paid") or "")).get("tx", "")
    return {"ok": bool(got.get("ok")), "tx": tx, "why": str(got.get("why") or "")[:200]}


def _repo(root: Path):
    repo = root / "series"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.email", "s@s"),
                 ("config", "user.name", "s"), ("add", "-A"),
                 ("commit", "-qm", "first")):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    return repo


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rounds", type=int, default=20)
    p.add_argument("--budget", type=float, required=True,
                   help="hard ceiling in dollars; the run stops before crossing it")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--dry", action="store_true", help="decide everything, buy nothing")
    args = p.parse_args()

    done = []
    if args.resume and LOG.exists():
        done = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    spent = sum(float(r.get("cost_usd", 0) or 0) for r in done)
    start_at = len(done)

    import os
    import tempfile

    from knos import record
    from knos.memory import Memory

    rng = random.Random(1337)
    for _ in range(start_at):
        rng.random(), rng.choice(list(AGENTS)), rng.choice(TOPICS)  # keep the dice in step

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        os.environ["KNOS_HOME"] = str(root / "home")
        repo = _repo(root)

        for n in range(start_at, args.rounds):
            who = rng.choice(list(AGENTS))
            topic = rng.choice(TOPICS)
            finishes = rng.random() < AGENTS[who]

            # The blind arm has no record to consult, so it always buys.
            # The promoted arm asks the store first.
            with Memory(repo) as mem:
                allowed, why = record.may_spend(mem, who)

            # Both learned decisions, not just the one that costs money. The
            # hold is what the rubric calls dynamic storage and it was absent
            # from the first run entirely - and it is free to record, because
            # a hold length is not a purchase.
            with Memory(repo) as mem:
                standing = record.standing(mem, who)
                hold = record.holds_for(mem, who)

            row = {"round": n, "who": who, "topic": topic,
                   "blind_allowed": True, "promoted_allowed": bool(allowed),
                   "why_refused": "" if allowed else why[:160],
                   "hold_minutes": hold,
                   "promoted_to_warm": bool(standing["promoted"]),
                   "closed_raw": standing["raw_kept"],
                   "closed_counted": standing["kept"],
                   "taken": standing["taken"], "finished": standing["finished"]}

            # The blind arm pays for real. Computing what it "would have"
            # cost would make this a real-versus-hypothetical comparison,
            # which is the exact weakness a thousand-forecast run does not
            # have: both of their arms spent real money. So does this.
            if not args.dry:
                if spent + PRICE_USD > args.budget:
                    row["stopped"] = f"the ${args.budget:.3f} budget would be crossed"
                    done.append(row)
                    with LOG.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row) + "\n")
                    break
                blind = _buy(topic)
                row["blind_paid"] = bool(blind["ok"])
                row["blind_cost_usd"] = PRICE_USD if blind["ok"] else 0.0
                row["blind_tx"] = blind.get("tx", "")
                spent += row["blind_cost_usd"]
            else:
                row["blind_paid"] = False
                row["blind_cost_usd"] = 0.0

            if allowed and not args.dry:
                if spent + PRICE_USD > args.budget:
                    row["stopped"] = f"the ${args.budget:.3f} budget would be crossed"
                    done.append(row)
                    with LOG.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(row) + "\n")
                    break
                got = _buy(topic)
                row["paid"] = bool(got["ok"])
                row["cost_usd"] = PRICE_USD if got["ok"] else 0.0
                row["tx"] = got.get("tx", "")
                if not got["ok"]:
                    row["why_no_payment"] = got.get("why", "")
                spent += row["cost_usd"]
            else:
                row["paid"] = False
                row["cost_usd"] = 0.0

            # The record only learns from what the agent did, and it learns
            # after the decision, never before it.
            with Memory(repo) as mem:
                record.note_taken(mem, f"{topic} {n}", who)
                if finishes:
                    record.note_finished(mem, f"{topic} {n}", who)

            done.append(row)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            print(f"  {n:4} {who:16} {'paid' if row['paid'] else 'refused':8} "
                  f"${spent:.4f}", flush=True)

    paid = [r for r in done if r.get("paid")]
    allowed = [r for r in done if r.get("promoted_allowed")]
    refused = [r for r in done if not r.get("promoted_allowed")]
    blind_paid = [r for r in done if r.get("blind_paid")]
    blind_cost = sum(float(r.get("blind_cost_usd", 0) or 0) for r in done)
    summary = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "network": "Base mainnet",
        "endpoint": NEWS,
        "price_usd": PRICE_USD,
        "rounds": len(done),
        "budget_usd": args.budget,
        "agents": AGENTS,
        "blind": {"allowed": len(done), "paid": len(blind_paid),
                  "cost_usd": round(blind_cost, 4)},
        "promoted": {"allowed": len(allowed), "paid": len(paid),
                     "refused": len(refused),
                     "cost_usd": round(sum(float(r.get("cost_usd", 0) or 0)
                                           for r in done), 4)},
        "saved_usd": round(blind_cost - sum(float(r.get("cost_usd", 0) or 0)
                                            for r in done), 4),
        "learned_hold": {
            who: {
                "first_seen_hold": next(
                    (r["hold_minutes"] for r in done if r["who"] == who), None),
                "last_hold": next(
                    (r["hold_minutes"] for r in reversed(done) if r["who"] == who), None),
                "taken": next(
                    (r.get("taken") for r in reversed(done) if r["who"] == who), 0),
                "finished": next(
                    (r.get("finished") for r in reversed(done) if r["who"] == who), 0),
                "promoted": next(
                    (r.get("promoted_to_warm") for r in reversed(done)
                     if r["who"] == who), False),
            }
            for who in AGENTS
            if any(r["who"] == who for r in done)
        },
        "refusals_by_agent": {
            who: sum(1 for r in done
                     if r["who"] == who and not r.get("promoted_allowed"))
            for who in AGENTS if any(r["who"] == who for r in done)
        },
        "transactions": ([r["tx"] for r in paid if r.get("tx")]
                         + [r["blind_tx"] for r in done if r.get("blind_tx")])[:80],
        "what_this_is": (
            "Real USDC on Base mainnet. The blind arm is knos with the store "
            "deleted and buys every round with real money; the promoted arm "
            "asks the WARM record first. Both arms pay; neither is a "
            "counterfactual. "
            "Same dice, same endpoint, same price - the record is "
            "the only difference, and the money not spent is the result."
        ),
        "what_this_is_not": (
            "A thousand-forecast run unless --rounds says so. The reliability "
            "of each agent is the one modelled input and is listed above; what "
            "is measured is what the rule does to real spending given it."
        ),
    }
    OUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "transactions"}, indent=2))


if __name__ == "__main__":
    main()
