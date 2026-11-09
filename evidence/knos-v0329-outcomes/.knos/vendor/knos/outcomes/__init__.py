"""Knos Outcomes: pay for a result measured from data, not only for tests that pass.

    spec      outcome.yaml: the metric, the data, the window, a randomized control group, the bar, tiers under a cap
    assign    who is in control: a hash of a public salt and the item id, recomputable by either side
    measure   treated vs control, lift, a bootstrap lower bound with a fixed seed, the cheat checks, one result JSON
    escrow    one knos_pay order per tier, pinned to the buyer's prove.yml at the commit that holds the spec
    sign      both parties sign the spec's hash; the hash goes on the orders' issue
    recordio  Knos Record entries for every measurement, cheat, payment and refund

docs/reference/MEASURED.md says it in plain words. Modules are imported on use: `measure` needs nothing beyond the
standard library, so the reusable workflow's measuring job installs nothing else.
"""
