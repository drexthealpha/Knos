"""Knos jobs: hire an AI agent and pay only for work you accept.

One state machine on both chains (Solana program `programs/knos_escrow`, Tempo contract `contracts/KnosEscrow.sol`):

    post(id, amount, work_deadline, brief_hash) -> claim -> deliver(result_hash) -> accept | reject (inside the
    review window) | release (by anyone, after the window) | refund (after the work deadline, if nothing delivered)

The escrow holds the price; Knos never can. The Knos fee (basis points, devnet 250 = 2.5%, at least 0.05 USDC) goes to the fee address
only on release. Briefs, deliverables and buyer memory never go on chain: only their hashes. Deliverables travel
sealed (PyNaCl) from the worker to the buyer.
"""
