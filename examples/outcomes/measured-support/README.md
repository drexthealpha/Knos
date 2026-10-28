# Measured outcome: support tickets resolved without a person (SYNTHETIC)

Every ticket here is made up (`knos.outcomes.synth`). An "AI agent" handles the treated tickets and people the
control tickets; the chance that a ticket is solved without escalation or reopening is a parameter of the generator
(0.45 for control, 0.53 for treated in the sample), so the lift is chosen, not found. This folder shows how a measured
result is specified, measured and paid; it says nothing about any real agent, help desk or customer.

| File | What it is |
|---|---|
| `outcome.yaml.in` | the spec the devnet sample funded, as `outcome.yaml` (written by `demo.py prepare`; `.in` so no workflow test reads it as one of this repository's files): metric, data, window, control, tiers, held money |
| `prove.yml.in` | the buyer's workflow, to install as `.github/workflows/prove.yml`: the reusable `knos-outcome.yml` measures, then one GitHub token per passed tier |
| `demo.py` | the devnet sample, one step per command: prepare, fund, data, run, relay, refund, status |
| `demo.json` | what the chain said after the sample: every order, every transaction signature, the measurement |

Run the measurement yourself on made-up data, with no network:

    knos outcome sample examples/outcomes/measured-support/outcome.yaml.in --out tickets.csv
    knos outcome lock examples/outcomes/measured-support/outcome.yaml.in --no-orders --out /tmp/lock.json
    knos outcome measure examples/outcomes/measured-support/outcome.yaml.in --lock /tmp/lock.json --data tickets.csv

The page in plain words: [docs/reference/OUTCOMES.md](../../../docs/reference/OUTCOMES.md).
