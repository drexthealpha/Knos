"""Real USDC, on Base mainnet, refused and allowed by the promoted record alone.

`promotion_bench.py` is a simulation and says so. This is the same claim with
the simulation taken out: one agent, one endpoint, one price, and the only
thing that changes between the runs is what the store knows about that agent.

    round 1   no record yet          gate says buy        real payment, real hash
    round 2   four claims, none closed   gate says unproven   nothing spent
    round 3   those claims closed        gate says buy        real payment, real hash

Every payment is an x402 settlement in USDC on Base and leaves a transaction
anybody can open. Every refusal costs nothing, which is the point: the money
that is not spent is the measurement.

**The budget is the honest limit here.** The wallet behind this holds cents,
not the thousands of dollars a forecast league can burn through, so this is
tens of live payments rather than a thousand. What it establishes is that the
promoted record is wired to real money in a shipped product - not how the
number scales.

    python scripts/live_gate.py            # dry, decides nothing is bought
    python scripts/live_gate.py --spend    # real payments, capped

Writes docs/evidence/live-gate.json.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# A hard ceiling in dollars. The script stops before crossing it whatever the
# rounds say, because a loop that pays per iteration is exactly the shape that
# empties a wallet through a typo.
CAP_USD = 0.02
PRICE_USD = 0.001
WHO = "the Telegram bot"
TOPIC = "ETH"


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    for args in (("init", "-q"), ("config", "user.email", "live@example.invalid"),
                 ("config", "user.name", "live"), ("add", "-A"),
                 ("commit", "-qm", "first")):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    return repo


def _verdict(repo: Path, who: str) -> dict:
    """What the gate says, without buying anything."""
    said = subprocess.run(
        [sys.executable, "-m", "knos.gate", "--topic", TOPIC, "--ask", TOPIC,
         "--as", who, "--repo", str(repo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT,
    )
    line = [x for x in said.stdout.splitlines() if x.strip()]
    return json.loads(line[-1]) if line else {"verdict": "unreadable"}


def _pay(topic: str) -> dict:
    """One real x402 purchase, through the product surface a person uses.

    Deliberately the bot's own `/news`, not `agent/buy.ts`: that one is the
    ACP path at ten times the price and a different mechanism entirely. This
    drives the same handler Telegram calls, so the gate call in the receipt
    below is the bot's own, not one this script made up.
    """
    said = subprocess.run(
        [str(ROOT / "agent" / "node_modules" / ".bin" / "tsx.cmd"),
         str(ROOT / "agent" / "bot.ts"), "/news", topic],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT / "agent", timeout=300,
    )
    out = said.stdout + said.stderr
    # The hash arrives inside a basescan URL, so a word starting with `0x`
    # never matches. Reading it that way once recorded a real $0.001 payment
    # as `paid: false` and wrote `spent_usd: 0.0` over it.
    found = re.search(r"0x[0-9a-fA-F]{64}", out)
    tx = found.group(0) if found else ""

    # What the bot actually did, which is not always what the gate predicted:
    # the answer bought in an earlier round is in the store by the time a later
    # one asks, so the bot answers free rather than buying again.
    # Order matters, and getting it wrong cost this file its credibility once
    # already. An answer served out of the store QUOTES the note written when
    # it was bought, and that note contains the original basescan URL - so a
    # hash in the reply is not evidence of a payment. The free markers are
    # checked first, and a hash only counts when they are absent.
    free = ("already paid for it once" in out or "nobody paid again" in out
            or "Free." in out)
    if free:
        outcome, paid = "free, the store already had it", False
        tx = ""          # that hash belongs to the earlier purchase
    elif tx:
        outcome, paid = "paid", True
    else:
        outcome, paid = "no payment and no answer", False
    return {"outcome": outcome, "paid": paid, "tx": tx,
            "said": out.strip()[-400:]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spend", action="store_true",
                        help="make the real payments (capped at $%.3f)" % CAP_USD)
    args = parser.parse_args()

    from knos.memory import Memory
    from knos import record

    rounds: list[dict] = []
    spent = 0.0

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        import os
        os.environ["KNOS_HOME"] = str(root / "home")
        repo = _repo(root)

        def attempt(label: str, note: str) -> None:
            nonlocal spent
            got = _verdict(repo, WHO)
            row = {"round": label, "store_says": note,
                   "verdict": got.get("verdict"),
                   "why": (got.get("answer") or "")[:200]}
            if got.get("verdict") == "buy":
                if not args.spend:
                    row["paid"] = "dry run - nothing bought"
                elif spent + PRICE_USD > CAP_USD:
                    row["paid"] = f"stopped at the ${CAP_USD:.3f} cap"
                else:
                    receipt = _pay(TOPIC)
                    spent += PRICE_USD if receipt["paid"] else 0.0
                    row["outcome"] = receipt["outcome"]
                    row["paid"] = receipt["paid"]
                    row["cost_usd"] = PRICE_USD if receipt["paid"] else 0.0
                    if receipt["tx"]:
                        row["tx"] = receipt["tx"]
                        row["receipt"] = (
                            "https://basescan.org/tx/" + receipt["tx"])
                    else:
                        row["seller_said"] = receipt["said"]
            else:
                row["outcome"] = "refused by the store"
                row["paid"] = False
                row["cost_usd"] = 0.0
            rounds.append(row)

        attempt("1", "nothing known about this agent")

        with Memory(repo) as mem:
            for n in range(4):
                record.note_taken(mem, f"job {n}", WHO)
        attempt("2", "four claims taken, none closed")

        with Memory(repo) as mem:
            for n in range(4):
                record.note_finished(mem, f"job {n}", WHO)
        attempt("3", "the same four claims, now closed")

    out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "network": "Base mainnet",
        "price_usd": PRICE_USD,
        "cap_usd": CAP_USD,
        "spent_usd": round(spent, 4),
        "agent": WHO,
        "rounds": rounds,
        "what_changed_between_rounds": (
            "Only what the store knows about this agent. Same endpoint, same "
            "price, same wallet, same topic."
        ),
        "what_this_is_not": (
            "A run at the scale of a real trading agent. The wallet behind it "
            "holds cents, so this is tens of live payments rather than "
            "thousands. It establishes that the promoted record is wired to "
            "real money in a shipped product, not how that number scales."
        ),
    }
    (ROOT / "docs" / "evidence" / "live-gate.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
