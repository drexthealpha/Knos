"""Proof: compares what a change claims with what the repository and its checks show.

`claims` reads what an agent's last message asserts, `checks` runs the evidence itself (never the agent's word),
`engine` decides, `history` keeps every verdict in the repo's Sibyl store and learns required checks from past false
"done"s, and `hook` is the Stop hook for Claude Code, Codex and other hosts.
"""
