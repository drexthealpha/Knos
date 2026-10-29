# The score proof's setup

`zk/score_circuit` proves that a score passed its threshold without showing the score, and `programs-v2/knos_zk`
verifies that proof on Solana devnet.

The proving key comes from a toy setup with a fixed seed (`TOY_SETUP_SEED` in `zk/score_circuit/src/lib.rs`). Anyone
can recompute that seed's secret values, so anyone could forge a proof against this key. That is why the build is for
devnet and tests only.

A build that pays real money needs a key from a multi-party setup ceremony, where the secret is safe as long as one
participant destroys their share. No such ceremony has been run, and no money moves on a proof from the toy key.
