"""Ask the store before spending money. The memory decides whether you pay.

The README has always said nobody on this machine pays twice. Until now that
was only half true: the bot wrote what it bought back into the store, but
never looked in the store before buying, so the second identical request paid
again. This closes that, and makes the memory the thing that decides.

Three answers, and only the last one costs anything:

    withheld  somebody is mid-change on this topic. No purchase. You are told
              who holds it, exactly as an agent asking over MCP would be.
    have      the store already has it. No purchase. The stored answer is
              returned, with where it came from.
    buy       the store has nothing and nothing is claimed. Go and pay.

Nothing here is new behaviour invented for a demo. The withhold is
`core.Claims.withheld`, which is `answer.withheld`, which is what the MCP
server already says. The lookup is `answer.ask`, which is what `knos ask`
already runs. This composes them at the one point where the answer is worth
real money.

    python -m knos.gate --topic "market brief: BTC" --ask "market brief BTC"

Prints JSON: {"verdict", "answer", "holder", "where"}.
Never raises at the top level: the caller is a bot answering a person, and a
gate that crashes must not become a gate that spends. On any unexpected error
it returns verdict "buy" - failing towards the behaviour that was there
before this file existed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def decide(repo: Path, topic: str, question: str) -> dict[str, str]:
    """What the store says about buying this, without buying it."""
    from . import answer, paths
    from .core import Claims
    from .memory import Memory

    repo = Path(repo).resolve()
    paths.remember_pointed(repo)

    # A claim first. Somebody mid-change on this topic is a reason not to
    # spend at all: whatever comes back is about to be out of date, and the
    # person holding it is the cheaper place to ask.
    with Claims(repo=repo, who="the agent") as claims:
        withheld = claims.withheld(topic)
        if withheld:
            work = claims.holder(topic) or {}
            return {
                "verdict": "withheld",
                "answer": withheld,
                "holder": str(work.get("who", "")),
                "where": "",
            }

    # Then: was this reasoned from a decision that has since been reversed?
    # Buying more of it before anyone has looked is how one changed decision
    # becomes a pile of paid-for work built on it.
    from . import decide

    with Memory(repo) as mem:
        found = decide.is_suspect(mem, topic)
        if found is not None:
            return {
                "verdict": "suspect",
                "answer": decide.refusal(found),
                "holder": str(found.get("who", "")),
                "where": str(found.get("because", "")),
            }

    # Then what is already known - under this exact topic, and no other.
    #
    # This used to search, and searching is wrong here in a way that costs
    # more than money: `answer.ask` matches on shared stems, so a store
    # holding "market brief: BTC" answered a request for "market brief: ETH"
    # and the agent was handed the wrong asset's numbers for free. Saving a
    # cent by returning something true about a different subject is the worst
    # outcome available. `knos remember` writes the purchase under the topic
    # as a named thing, so the exact name is what to read back.
    from .memory import TOPIC

    with Memory(repo) as mem:
        thing = mem.thing(TOPIC, topic)
        note = str(((thing or {}).get("body") or {}).get("note", ""))
        if "Bought over x402" in note:
            return {
                "verdict": "have",
                "answer": note,
                "holder": "",
                "where": str(((thing or {}).get("body") or {}).get("when", "")),
            }

    return {"verdict": "buy", "answer": "", "holder": "", "where": ""}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="knos.gate", add_help=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--ask", required=True)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv[1:])

    try:
        said = decide(Path(args.repo), args.topic, args.ask)
    except Exception as why:  # noqa: BLE001 - a broken gate must not spend
        said = {"verdict": "buy", "answer": "", "holder": "", "where": "",
                "why": f"{type(why).__name__}: {why}"}
    print(json.dumps(said))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
