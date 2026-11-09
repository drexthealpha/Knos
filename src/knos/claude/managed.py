"""Knos as the referee behind Claude Managed Agents: the platform's grader says "satisfied", Knos decides "paid".

Claude Managed Agents (beta header managed-agents-2026-04-01, set by the Anthropic SDK on client.beta.* calls; the
claude-api skill's shared/managed-agents-outcomes.md and python/managed-agents/README.md, platform.claude.com/docs/en/
managed-agents/define-outcomes, read 14 Oct 2026): an agent is created once (client.beta.agents.create: name, model,
system, tools) and run in sessions (client.beta.sessions.create(agent=..., environment_id=...)). A deliverable is
asked for with one `user.define_outcome` event {description, rubric: {type: "text", content}, max_iterations (default 3,
max 20)}; a grader "in a separate context window" scores each iteration and emits span.outcome_evaluation_end with
result satisfied | needs_revision | max_iterations_reached | failed | interrupted. The agent writes deliverables to
/mnt/session/outputs/, listed with client.beta.files.list(scope_id=session.id, betas=["managed-agents-2026-04-01"]).

The gap Knos fills: the grader belongs to the same platform as the worker and reads a rubric, not sealed tests. So
`satisfied` is necessary and never sufficient here. When the session is idle with a satisfied outcome, Knos downloads
the outputs and runs its own judge on them (the referee's sealed checks and re-runs, `judge(files) -> verdict`); only
Knos's verdict can release vault, and a refused verdict pays nothing whatever the grader said. The rubric Knos sends
holds only the task's public criteria: the sealed tests never enter the session.

Model: claude-opus-5-5 (the skill's default). Nothing here runs without ANTHROPIC_API_KEY; the tests drive it with a
stand-in client whose events have the documented shapes and are labelled synthetic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MODEL = "claude-opus-5-5"
BETA = "managed-agents-2026-04-01"
TERMINAL = {"satisfied", "max_iterations_reached", "failed", "interrupted"}


def agent_spec(name: str = "Knos research worker") -> dict:
    """What client.beta.agents.create takes, created once and stored by id (never in the request path)."""
    return {"name": name, "model": MODEL,
            "system": ("You work on one research task posted on Knos. Write the deliverable to /mnt/session/outputs/. An independent "
                       "referee re-runs your work against sealed checks you cannot see; editing tests or fixtures, hard-coding "
                       "expected answers or claiming results you did not compute are refused and never paid."),
            "tools": [{"type": "agent_toolset_20260401", "default_config": {"enabled": True}}]}


def rubric(task: dict) -> str:
    """A starter rubric from a Knos task's PUBLIC terms: what the deliverable is, its format, the public checks. The
    sealed checks are not in it (they stay with the referee)."""
    lines = [f"# Rubric for: {task.get('title', 'the task')} (starter, from the task's public terms)",
             f"- The deliverable is in /mnt/session/outputs/ as {task.get('deliverable', 'the files the task names')}"]
    lines += [f"- {c}" for c in task.get("public_criteria", [])]
    lines += ["- No test, fixture or expected-output file was changed or added to make a check pass",
              "- Every number reported is computed by code included in the outputs, which runs as delivered"]
    return "\n".join(lines) + "\n"


def outcome_event(task: dict, max_iterations: int = 5) -> dict:
    return {"type": "user.define_outcome", "description": task["description"],
            "rubric": {"type": "text", "content": rubric(task)}, "max_iterations": max(1, min(20, max_iterations))}


@dataclass
class Run:
    session_id: str
    outcome: str | None = None              # the grader's last terminal result
    explanation: str = ""
    outputs: list = field(default_factory=list)
    knos: dict | None = None                # Knos's verdict: {"accepted": bool, "reasons": [...]}

    @property
    def payable(self) -> bool:
        """Only Knos's acceptance releases money; the grader's `satisfied` is a precondition to asking Knos at all."""
        return self.outcome == "satisfied" and bool(self.knos and self.knos.get("accepted"))


def follow(events) -> tuple[str | None, str, bool]:
    """(last terminal outcome result, its explanation, idle) from a session's events, by the documented idle gate:
    session.status_idle whose stop_reason is not requires_action ends the drain; outcome_evaluation_end alone does not."""
    result, why, idle = None, "", False
    for ev in events:
        t = _get(ev, "type")
        if t == "span.outcome_evaluation_end" and _get(ev, "result") in TERMINAL:
            result, why = _get(ev, "result"), _get(ev, "explanation") or ""
        elif t == "session.status_idle":
            stop = _get(ev, "stop_reason")
            if not (stop and _get(stop, "type") == "requires_action"):
                idle = True
                break
        elif t == "session.status_terminated":
            break
    return result, why, idle


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def run(client, agent_id: str, environment_id: str, task: dict, judge, download=None) -> Run:
    """One attempt end to end: a session, the outcome, the stream to idle, the outputs, Knos's verdict.
    `judge(outputs) -> {"accepted": bool, "reasons": [...]}` is the Knos referee on the files; `download(file) -> bytes`
    fetches one output (default client.beta.files.download(id).read())."""
    session = client.beta.sessions.create(agent={"type": "agent", "id": agent_id}, environment_id=environment_id,
                                          title=f"knos: {task.get('title', 'task')}")
    sid = _get(session, "id")
    with client.beta.sessions.events.stream(session_id=sid) as stream:      # stream first, then send (documented ordering)
        client.beta.sessions.events.send(session_id=sid, events=[outcome_event(task)])
        result, why, _idle = follow(stream)
    out = Run(sid, result, why)
    if result != "satisfied":
        return out                                                          # nothing to judge: the platform's own loop did not finish
    files = client.beta.files.list(scope_id=sid, betas=[BETA])
    for f in _get(files, "data") or []:
        body = download(f) if download else client.beta.files.download(_get(f, "id")).read()
        out.outputs.append({"name": _get(f, "filename"), "bytes": body})
    out.knos = judge(out.outputs)
    return out
