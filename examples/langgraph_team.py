"""Three LangGraph agents share one Sibyl memory and coordinate without race conditions.

Two worker agents are LangGraph graphs: pick a task -> claim it with Knos -> work -> write what it found to Sibyl's
own LangGraph BaseStore (backed by the workspace's Knos/Sibyl store) -> release. The second agent reaches for the task
the first one holds, is refused, and takes the next one. A third agent (carol) reads findings only from the store
and never claims tasks.

The "models" are scripted functions, so this runs anywhere with no API key:

    pip install "knos[langgraph]"
    python examples/langgraph_team.py

In a workspace with .knos/team.json the same claims are enforced across machines through Solana.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph
from sibyl_memory_langgraph import SibylStore

from knos.sdk import Knos

TASKS = ["task:invoice-4411", "task:invoice-4412", "task:invoice-4413"]


class State(TypedDict, total=False):
    task: str
    refused: list[str]
    finding: str


def scripted_model(agent: str, task: str) -> str:
    """Stands in for an LLM call: deterministic, so the example is a test."""
    return f"{agent} checked {task.split(':', 1)[1]}: totals match, no duplicate"


def build(k: Knos, store: SibylStore):
    def pick(state: State) -> State:
        refused = list(state.get("refused", []))
        for task in TASKS:
            if task in refused:
                continue
            if k.claim(task):
                return {"task": task, "refused": refused}
            refused.append(task)
            print(f"  {k.agent}: {task} is claimed by {k.holder}; taking other work")
        return {"task": "", "refused": refused}

    def work(state: State) -> State:
        return {"finding": scripted_model(k.agent, state["task"])}

    def write(state: State) -> State:
        store.put(("team", "findings"), state["task"], {"text": state["finding"], "by": k.agent})
        k.remember(state["finding"], about=state["task"].split(":", 1)[1])
        return {}

    g = StateGraph(State)
    g.add_node("pick", pick)
    g.add_node("work", work)
    g.add_node("write", write)
    g.set_entry_point("pick")
    g.add_conditional_edges("pick", lambda s: "work" if s.get("task") else END, {"work": "work", END: END})
    g.add_edge("work", "write")
    g.add_edge("write", END)
    return g.compile(store=store)


def build_reader(store: SibylStore, agent: str = "carol"):
    """An agent that reads findings from the shared Sibyl store and never claims tasks."""
    def inspect(state: State) -> State:
        items = list(store.search(("team", "findings")))
        findings = [f"{item.key}: {item.value.get('text', '')}" for item in sorted(items, key=lambda x: x.key)]
        return {"finding": f"{agent} read {len(items)} finding(s): {'; '.join(findings)}"}

    g = StateGraph(State)
    g.add_node("inspect", inspect)
    g.set_entry_point("inspect")
    g.add_edge("inspect", END)
    return g.compile(store=store)


def run(workspace: Path) -> dict:
    alice, bob = Knos("alice", workspace), Knos("bob", workspace)
    mem, client = alice.memory_client()
    try:
        store = SibylStore(client=client)  # Sibyl's own LangGraph store, on the workspace's Knos/Sibyl memory
        a = build(alice, store).invoke({})
        print(f"  alice holds {a['task']}")
        b = build(bob, store).invoke({})  # alice has not released: bob is refused and moves on
        print(f"  bob holds {b['task']}")
        shared = store.get(("team", "findings"), a["task"])
        c = build_reader(store, "carol").invoke({})  # third agent: reads findings only, never claims
        print(f"  {c['finding']}")
        alice.release(a["task"])
        bob.release(b["task"])
    finally:
        mem.close()
    return {"alice": a["task"], "bob": b["task"], "bob_refused": b.get("refused", []),
            "bob_read_alices_finding": shared.value["text"] if shared else None,
            "carol_finding": c["finding"]}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        got = run(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(d))
    print(got)
