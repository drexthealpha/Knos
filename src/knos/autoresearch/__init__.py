"""Autoresearch for anyone: an agent edits one file, each run has a fixed time budget, a change is kept only if Knos's
referee says it is better, and the best result must reproduce on data nobody saw before anyone is paid.

The pattern is Karpathy's autoresearch loop (agent edits one file, fixed-time run, keep-if-better). What Knos adds:

    the researcher writes program.md (plain English) + idea.md; the task's sealed spec is hashed and recorded first
    any agent proposes (proposers.LocalProposer by default: deterministic, no key, no network; CommandProposer runs
        Claude Code, Codex, Hermes or any command that reads a prompt on stdin and prints the new file)
    only the referee decides (judge.LocalJudge, the locked judging code): it runs the candidate in a bare sandbox,
        scores it on a sealed hidden dev set the agent never sees, re-runs it on a second seed within a tolerance,
        and refuses cheats (files outside scope, forbidden imports, reaching for sealed data, no change)
    graduation: baseline and best are scored once on a second sealed set (hidden_final) never used in the loop; the
        lift must clear the agreed bar on both seeds, with the judging code unchanged since sealing
    every experiment, verdict, cheat and the split plan go to Knos Record (knos.record when present, else the same
        hash-chained journal kept here in the local memory store and a JSONL file); the payout is a PLAN, devnet test units, no transfer

    python -m knos.autoresearch run examples/autoresearch --out /tmp/ar --iterations 12

Modules: task (spec + sealing), synth (the synthetic data, labelled synthetic), sandbox (running a candidate),
judge (the locked referee for metric tasks), proposers, recorder (Knos Record adapter), payout (outcome + split plan
hooks), loop (the loop itself).
"""
from __future__ import annotations

from .loop import Report, run
from .proposers import Candidate, CommandProposer, LocalProposer
from .task import Task, load

__all__ = ["Candidate", "CommandProposer", "LocalProposer", "Report", "Task", "load", "run"]
