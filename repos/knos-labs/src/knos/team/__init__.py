"""Knos Team on Solana: one Solana Attestation Service credential per team, claims as attestations.

`sas` builds the instructions, byte for byte from the program's source; `rpc` is the small JSON-RPC client they are
sent with. Nothing here is imported on the memory or guard path unless a team is configured.
"""
