# upgrade_gate: which commit were these bytes built from

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

A program that writes one record, `["build", program, executable hash]`, only when GitHub signed that one build
workflow, on `main` or a release tag, on a GitHub-hosted runner, built exactly those bytes. `knos-oidc` checks
GitHub's signature on chain; this program reads the claims. A multisig's members read the record before they vote
for an upgrade.

The copy deployed on devnet (`2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW`) takes Knos's own workflow and no other.
For a program of yours, make your own:

```bash
python examples/upgrade_gate/adopt.py init --repo-id 123456789 --workflow OWNER/REPO/.github/workflows/build.yml --gate-id GATE_ADDRESS --out my_gate
```

`python examples/upgrade_gate/adopt.py --help` lists its commands.
`tests/test_upgrade_gate.py` runs the program in a simulator; `tests/test_gate_adopt.py` runs `adopt.py`.
