"""Proof: AI agent work counts only when Knos proves it.

A coding agent cannot say done, and a hired agent cannot get paid, until the proof is real. `claims` reads what an
agent's last message asserts, `checks` runs the evidence itself (never the agent's word), `engine` decides, `history`
keeps every verdict in the repo's Sibyl store and learns required checks from past false "done"s, `hook` is the
Claude Code / Codex Stop hook, and `receipt` turns a proven "done" into a Merkle root anyone can check.
"""
