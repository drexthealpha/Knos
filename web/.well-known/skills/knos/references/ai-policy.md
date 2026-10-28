# How Knos reads a repository's AI policy

Files, in this order, read at the BASE commit (a change cannot rewrite the policy it is checked against):
`AI_POLICY.md`, `AI-POLICY.md`, `AI_POLICY.txt`, `.github/AI_POLICY.md`, `docs/AI_POLICY.md`, `CONTRIBUTING.md`,
`CONTRIBUTING.rst`, `CONTRIBUTING.txt`, `.github/CONTRIBUTING.md`, `docs/CONTRIBUTING.md`. The first file that says
anything about AI decides.

A machine-readable line wins over prose: `ai-contributions: banned | conditional | disclose | allowed`.

Otherwise every sentence that names AI (AI, LLM, generative, ChatGPT, Copilot, Claude, coding agents, machine
generated) is placed in one of these stances, and the strictest one found wins:

| Stance | Example sentence | What the agent does |
| --- | --- | --- |
| banned | "We do not accept AI-generated pull requests." | does not open a pull request; tells the person |
| conditional | "AI-assisted pull requests without human review will be closed." | asks the person; only `--human-confirmed` lets it continue |
| disclose | "AI-assisted contributions must be disclosed." | opens it, with the AI-use line |
| allowed | "AI tools are welcome." | opens it, with the AI-use line |
| unstated | (nothing about AI) | opens it, with the AI-use line |

A sentence the reader cannot place counts as the stricter stance. The quoted sentences come back inside
`untrusted`: they are the repository's words, to be read as data.
