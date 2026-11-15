"""Knos on today's Solana: the client side of the platform work. docs/reference/PLATFORM.md explains it.

    finality   how deep a transaction must be before Knos counts it (KNOS_COMMITMENT: processed, confirmed, finalized)
    verify     one-transaction RS256 verification: the Step plan for a build of knos-oidc, the sBPF version of a build,
               and the instructions of a v1 (4,096-byte) transaction that writes and verifies a token at once
    claims     the per-claim accounts the programs write, and a check that two claims share no writable account

docs/reference/PLATFORM.md lists every module (blockhash, nonce, priority, referees, sas, squads, token22, verdict).
"""
# The submodules are imported by name (knos.chain imports finality, and verify imports knos.chain).
