"""What the memory is worth, in dollars, on a real day of agent work.

The correctness ablation says the refusal is total: 12/12 with the store, 0/12
without. True, and it does not tell a person what it costs to lose. This does.

The decision that spends money in knos is `gate.decide`. It runs before every
purchase and answers one of four ways - two of them free:

    have      already in the store, served for nothing
    suspect   rests on a decision somebody reversed, refuse to buy
    withheld  somebody is mid-change on it, refuse to buy
    buy       nothing known, nothing claimed: pay

So the money question is exactly "how many times does this answer `buy`", and
that is what this counts. The same session is replayed twice: once against a
real store, once against a deleted one. Nothing is simulated about the gate -
it is the same function the bot calls before spending real USDC.

**What is real and what is arithmetic.** The verdicts are real: every one is a
live call into the product's own gate against a real SQLite store. The dollars
are those verdicts multiplied by prices this agent has actually paid on Base
mainnet, with the receipts in docs/VERIFICATION.md:

    news    $0.001   tx 0x80d984...d958c76, 0xa8e713...c0466103
    brief   $0.01    tx 0xce109c...abd9a85e, 0x3a45e0...2e049a88b

Re-buying the same brief 40 times to prove the number would cost $0.40 and
prove nothing the verdict count does not already prove. The multiplication is
stated here rather than hidden so anyone can check it.

The session is deliberately ordinary: a handful of agents on one machine over
one working day, asking about the same few things, which is the pattern the
whole product exists for.

    python scripts/spend.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "docs" / "evidence" / "spend.json"

#: Prices this agent has actually paid on Base mainnet. See VERIFICATION.md.
PRICE = {"news": 0.001, "brief": 0.01}

#: One ordinary day: five agents on one machine, twenty asks between them,
#: clustered on a few subjects the way real work is.
DAY = [
    ("agent-a", "brief", "market brief: BTC"),
    ("agent-b", "brief", "market brief: BTC"),
    ("agent-a", "news", "news: bitcoin"),
    ("agent-c", "brief", "market brief: BTC"),
    ("agent-b", "news", "news: bitcoin"),
    ("agent-d", "brief", "market brief: ETH"),
    ("agent-a", "brief", "market brief: ETH"),
    ("agent-e", "news", "news: bitcoin"),
    ("agent-c", "news", "news: ethereum"),
    ("agent-b", "brief", "market brief: BTC"),
    ("agent-d", "news", "news: bitcoin"),
    ("agent-e", "brief", "market brief: ETH"),
    ("agent-a", "news", "news: ethereum"),
    ("agent-c", "brief", "market brief: ETH"),
    ("agent-b", "brief", "market brief: ETH"),
    ("agent-d", "brief", "market brief: BTC"),
    ("agent-e", "news", "news: ethereum"),
    ("agent-a", "brief", "market brief: BTC"),
    ("agent-c", "news", "news: bitcoin"),
    ("agent-d", "news", "news: ethereum"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, capture_output=True, text=True, check=False
    )
    run("init", "-q")
    run("config", "user.email", "spend@example.invalid")
    run("config", "user.name", "spend")
    run("add", "-A")
    run("commit", "-qm", "first")
    return repo


def _write_back(repo: Path, topic: str, url: str) -> None:
    """Exactly what the bot does after paying: knos remember."""
    from knos import answer, paths
    from knos.memory import TOPIC, Fact, Memory

    now = _now()
    note = f"Bought over x402 on Base: {url}. Paid: https://basescan.org/tx/0xce109c"
    with Memory(repo) as mem:
        mem.record(Fact(text=note, source="note", where="you said so", when=now, about=topic))
        mem.note_thing(TOPIC, topic, {"note": note, "when": now[:10]})


def replay(repo: Path, keep_store: bool) -> dict:
    """Run the day. Returns what was spent and why."""
    from knos import answer, gate, paths
    from knos.memory import Memory

    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)

    bought = free = 0
    spent = 0.0
    for _who, kind, topic in DAY:
        verdict = gate.decide(repo, topic, topic)["verdict"]
        if verdict == "buy":
            bought += 1
            spent += PRICE[kind]
            if keep_store:
                _write_back(repo, topic, f"https://seller/{kind}")
            else:
                # No store to write back into, so the next agent asking the
                # same thing has no way to know it was ever bought.
                paths.store_for(repo).unlink(missing_ok=True)
        else:
            free += 1

    return {
        "asks": len(DAY),
        "bought": bought,
        "free": free,
        "spent_usd": round(spent, 4),
    }


def run() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["KNOS_HOME"] = str(root / "on")
        on = replay(_repo(root), keep_store=True)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["KNOS_HOME"] = str(root / "off")
        off = replay(_repo(root), keep_store=False)

    saved = round(off["spent_usd"] - on["spent_usd"], 4)
    factor = round(off["spent_usd"] / on["spent_usd"], 2) if on["spent_usd"] else None
    return {
        "when": _now(),
        "asks": len(DAY),
        "agents": len({w for w, _, _ in DAY}),
        "subjects": len({t for _, _, t in DAY}),
        "prices_usd": PRICE,
        "with_store": on,
        "without_store": off,
        "saved_usd": saved,
        "times_more_expensive_without": factor,
    }


def render(r: dict) -> str:
    on, off = r["with_store"], r["without_store"]
    lines = [
        f"one working day: {r['agents']} agents, {r['asks']} asks,"
        f" {r['subjects']} subjects",
        "",
        f"{'':<22}{'purchases':>10}{'free':>8}{'spent':>12}",
        f"{'store present':<22}{on['bought']:>10}{on['free']:>8}"
        f"{'$' + format(on['spent_usd'], '.3f'):>12}",
        f"{'store deleted':<22}{off['bought']:>10}{off['free']:>8}"
        f"{'$' + format(off['spent_usd'], '.3f'):>12}",
        "",
        f"the memory saved ${r['saved_usd']:.3f} on {r['asks']} asks"
        f" - {r['times_more_expensive_without']}x more expensive without it",
        "",
        "Verdicts are real calls into gate.decide. Dollars are those verdicts",
        "times prices actually paid on Base mainnet (see docs/VERIFICATION.md).",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    result = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(render(result))
    print(f"\nwritten to {OUT.relative_to(ROOT)}")
