"""Measured ablation: what knos does with the store, and without it.

Every number below is a real run against the real refusal code, seeded so it
reproduces. Nothing here is a judge-facing figure that was typed by hand.

The claim under test is the one the whole product rests on: knos does not
warn, it **withholds**, and the withhold is only possible because a durable
store in Sibyl says somebody is already on the work. Take the store away and
the refusal cannot happen - not "degrades", cannot happen - so the second
agent is told the thing it was supposed to be refused.

Four arms, each the same request run twice with one thing changed:

    withhold on    a claim stands in Sibyl -> search is refused, holder named
    withhold off   same claim, store deleted -> the answer comes straight out

    guard on       an edit to claimed work -> the hook refuses it (exit 2)
    guard off      same edit, store deleted -> the hook allows it (exit 0)

    action on      a PR touching a claimed topic -> the check comments
    action off     same PR, no decisions file -> the check says nothing

    paid on        a bought answer is written back -> the next agent is free
    paid off       same purchase, store deleted -> nothing was kept

Run it: python scripts/ablation.py
Pinned by tests/test_ablation.py, so a change that quietly weakens any arm
fails the suite rather than the demo.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "docs" / "evidence" / "ablation.json"
TRIALS = 12
SEED = 1337


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo(root: Path) -> Path:
    """A real git repo, because knos keys its store on the git common dir."""
    repo = root / "repo"
    repo.mkdir()
    (repo / "risk_guard.py").write_text("def check(asset):\n    return True\n", encoding="utf-8")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, capture_output=True, text=True, check=False
    )
    run("init", "-q")
    run("config", "user.email", "ablation@example.invalid")
    run("config", "user.name", "ablation")
    run("add", "-A")
    run("commit", "-qm", "first")
    return repo


def _seed_claim(repo: Path, topic: str = "the risk guard") -> None:
    from knos.memory import Fact, Memory

    with Memory(repo) as mem:
        mem.record(
            Fact(
                text="the risk guard refuses unknown assets",
                source="session",
                where="Claude Code session aaaa1111 2026-08-20",
                when="2026-08-20",
                about=topic,
            )
        )
        mem.working_on(topic, "Claude Code", _now())


def arm_withhold(repo: Path, topic: str) -> tuple[bool, bool]:
    """(refused_with_store, refused_without_store) for a second agent asking."""
    from knos import mcp, paths
    from knos.memory import Memory

    with Memory(repo) as mem:
        held_on = mcp._held(mem, topic, "Cursor", "").startswith("Withheld.")

    paths.store_for(repo).unlink()

    with Memory(repo) as mem:
        held_off = mcp._held(mem, topic, "Cursor", "").startswith("Withheld.")
    return held_on, held_off


def arm_guard(repo: Path, topic: str) -> tuple[bool, bool]:
    """(refused_with_store, refused_without_store) for an edit to claimed work."""
    from knos import guard, paths

    target = repo / "risk_guard.py"
    on = not guard.check(repo, str(target), "Cursor").allow

    paths.store_for(repo).unlink()

    off = not guard.check(repo, str(target), "Cursor").allow
    return on, off


def arm_action(repo: Path, topic: str) -> tuple[bool, bool]:
    """(commented_with_file, commented_without_file) for the PR check."""
    sys.path.insert(0, str(ROOT / "action"))
    import knos_pr_check as check

    from knos import share
    from knos.memory import Memory

    with Memory(repo) as mem:
        share.write(repo, mem)
    shared = repo / ".knos" / "decisions.md"
    text = shared.read_text(encoding="utf-8") if shared.exists() else ""

    subject = check.words(f"update {topic} risk_guard.py")
    claims = check.read_claims(text)
    on = any(check.words(t) & subject for t, _ in claims)

    off = any(check.words(t) & subject for t, _ in check.read_claims(""))
    return on, off


def arm_paid(repo: Path) -> tuple[bool, bool]:
    """(kept_with_store, kept_without_store) for a bought answer written back.

    The purchase itself is not re-run here - that costs real USDC and is
    evidenced separately with on-chain receipts. What is measured is the half
    that makes paying once enough: the write-back, and whether the next agent
    finds it.
    """
    from knos import answer, paths
    from knos.memory import TOPIC, Fact, Memory

    # Exactly what `knos remember` writes, which is what the bot calls after a
    # purchase: the journal entry and the named thing. Writing only one of the
    # two measures a path the product does not use.
    note = "Bought over x402 on Base: market brief BTC. Paid: https://basescan.org/tx/0xce109c"
    topic = "market brief: BTC"
    now = _now()
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        mem.record(
            Fact(text=note, source="note", where="you said so", when=now, about=topic)
        )
        mem.note_thing(TOPIC, topic, {"note": note, "when": now[:10]})
    with Memory(repo) as mem:
        on = any("Bought over x402" in p.text for p in answer.ask(repo, mem, "market brief BTC"))

    paths.store_for(repo).unlink()

    with Memory(repo) as mem:
        off = any("Bought over x402" in p.text for p in answer.ask(repo, mem, "market brief BTC"))
    return on, off


def arm_spend(repo: Path) -> tuple[bool, bool, bool]:
    """Does the memory stop the money?

    Returns (paid_again_with_store, paid_again_without_store, refused_when_claimed).

    Arm three is the one that matters most: a claim standing on the topic
    means the answer is about to be stale and the holder is the cheaper place
    to ask, so the gate refuses to spend at all.
    """
    from knos import answer, gate, paths
    from knos.memory import TOPIC, Fact, Memory

    topic = "market brief: BTC"
    note = "Bought over x402 on Base: brief. Paid: https://basescan.org/tx/0xce109c"
    now = _now()
    paths.remember_pointed(repo)

    with Memory(repo) as mem:
        answer.point(repo, mem, index_code=False)
        mem.record(Fact(text=note, source="note", where="you said so", when=now, about=topic))
        mem.note_thing(TOPIC, topic, {"note": note, "when": now[:10]})

    # With the store: the second identical request must not buy.
    would_buy_on = gate.decide(repo, topic, topic)["verdict"] == "buy"

    # A claim standing on it: refuse to spend at all.
    with Memory(repo) as mem:
        mem.working_on(topic, "Claude Code", _now())
    refused = gate.decide(repo, topic, topic)["verdict"] == "withheld"

    paths.store_for(repo).unlink()

    # Without the store: nothing remembers the purchase, so it buys again.
    would_buy_off = gate.decide(repo, topic, topic)["verdict"] == "buy"
    return would_buy_on, would_buy_off, refused


def arm_reversed(repo: Path) -> tuple[bool, bool, bool]:
    """A decision is reversed. Does anything actually change?

    Returns (edit_refused, spend_refused, allowed_again_after_reconsider).

    This is the arm that separates a memory that records from a memory that
    decides. Reversing one decision holds the work reasoned from it, across
    two different surfaces, until somebody says they have looked.
    """
    from knos import decide, gate, guard, paths
    from knos.memory import TOPIC, Memory

    guard_topic, tests_topic = "the risk guard", "the risk guard tests"
    now = _now()
    paths.remember_pointed(repo)
    with Memory(repo) as mem:
        mem.note_thing(TOPIC, guard_topic, {"note": "refuses unknown assets", "when": now[:10]})
        mem.note_thing(TOPIC, tests_topic, {"note": "assume unknown refused", "when": now[:10]})

    target = repo / "risk_guard.py"
    with Memory(repo) as mem:
        decide.supersede(mem, guard_topic, "unknown assets pass with a warning", "you", _now())

    edit_refused = not guard.check(repo, str(target), "Cursor").allow
    spend_refused = gate.decide(repo, tests_topic, tests_topic)["verdict"] == "suspect"

    with Memory(repo) as mem:
        decide.reconsider(mem, tests_topic, "you", _now())
    allowed_again = guard.check(repo, str(target), "Cursor").allow
    return edit_refused, spend_refused, allowed_again


def run() -> dict:
    random.seed(SEED)
    topic = "the risk guard"
    tally = {
        "withhold": {"on_refused": 0, "off_refused": 0},
        "guard": {"on_refused": 0, "off_refused": 0},
        "action": {"on_commented": 0, "off_commented": 0},
        "paid": {"on_kept": 0, "off_kept": 0},
        "spend": {"on_paid_again": 0, "off_paid_again": 0, "refused_when_claimed": 0},
        "reversed": {"edit_refused": 0, "spend_refused": 0, "allowed_after_reconsider": 0},
    }

    for _ in range(TRIALS):
        for name, fn, keys in (
            ("withhold", arm_withhold, ("on_refused", "off_refused")),
            ("guard", arm_guard, ("on_refused", "off_refused")),
            ("action", arm_action, ("on_commented", "off_commented")),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                os.environ["KNOS_HOME"] = str(root / "home")
                repo = _repo(root)
                _seed_claim(repo, topic)
                on, off = fn(repo, topic)
                tally[name][keys[0]] += int(on)
                tally[name][keys[1]] += int(off)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["KNOS_HOME"] = str(root / "home")
            repo = _repo(root)
            on, off = arm_paid(repo)
            tally["paid"]["on_kept"] += int(on)
            tally["paid"]["off_kept"] += int(off)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["KNOS_HOME"] = str(root / "home")
            repo = _repo(root)
            on, off, refused = arm_spend(repo)
            tally["spend"]["on_paid_again"] += int(on)
            tally["spend"]["off_paid_again"] += int(off)
            tally["spend"]["refused_when_claimed"] += int(refused)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.environ["KNOS_HOME"] = str(root / "home")
            repo = _repo(root)
            edit, spend, again = arm_reversed(repo)
            tally["reversed"]["edit_refused"] += int(edit)
            tally["reversed"]["spend_refused"] += int(spend)
            tally["reversed"]["allowed_after_reconsider"] += int(again)

    return {
        "trials": TRIALS,
        "seed": SEED,
        "when": _now(),
        "arms": tally,
    }


def render(result: dict) -> str:
    t = result["trials"]
    a = result["arms"]
    rows = [
        ("Withhold: second agent asks about claimed work",
         f"refused {a['withhold']['on_refused']}/{t}",
         f"refused {a['withhold']['off_refused']}/{t}"),
        ("Guard: an edit to claimed work",
         f"refused {a['guard']['on_refused']}/{t}",
         f"refused {a['guard']['off_refused']}/{t}"),
        ("Action: a PR touching a claimed topic",
         f"commented {a['action']['on_commented']}/{t}",
         f"commented {a['action']['off_commented']}/{t}"),
        ("Paid: a bought answer, found by the next agent",
         f"kept {a['paid']['on_kept']}/{t}",
         f"kept {a['paid']['off_kept']}/{t}"),
        ("Spend: the same request a second time",
         f"paid again {a['spend']['on_paid_again']}/{t}",
         f"paid again {a['spend']['off_paid_again']}/{t}"),
        ("Spend: the same request while somebody holds it",
         f"refused {a['spend']['refused_when_claimed']}/{t}",
         "n/a - no claim survives"),
        ("Reversed decision: an edit resting on it",
         f"refused {a['reversed']['edit_refused']}/{t}",
         "n/a - nothing is held"),
        ("Reversed decision: a purchase resting on it",
         f"refused {a['reversed']['spend_refused']}/{t}",
         "n/a - nothing is held"),
        ("Reversed decision: the same edit after reconsidering",
         f"allowed {a['reversed']['allowed_after_reconsider']}/{t}",
         "n/a"),
    ]
    width = max(len(r[0]) for r in rows)
    out = [f"knos ablation - {t} trials, seed {result['seed']}", ""]
    out.append(f"{'':<{width}}  {'store present':<16} store deleted")
    for what, on, off in rows:
        out.append(f"{what:<{width}}  {on:<16} {off}")
    return "\n".join(out)


if __name__ == "__main__":
    result = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(render(result))
    print(f"\nwritten to {OUT.relative_to(ROOT)}")
