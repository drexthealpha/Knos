# A judge whose run is proved

An experiment. It is in no package, no wheel and no workflow, and nothing in Knos reads its output.
[docs/ATTESTOR.md](../../docs/ATTESTOR.md), rung e, says what it proves, what it does not, and what was measured.

| File | What it is |
|---|---|
| `checks.txt` | the task's seven cases: `<input> => <expected output>` |
| `fixtures/` | three submissions: all right, one wrong, too short |
| `guest/` | the judge, compiled for the RISC Zero zkVM; `guest/src/judge.rs` is the rule |
| `host/` | wraps the guest, proves a run through `r0vm`, verifies a receipt |
| `reference.py` | the same rule in plain Python, for a reader without the toolchain |
| `measure.py` | wall-clock seconds and peak memory of a command |
| `run.sh` | build, prove, verify, print |
| `results.json` | what one run here measured on 2026-10-07 |

## Run it

It needs a nightly Rust with `rust-src`, a stable Rust, and the `r0vm` binary of RISC Zero 3.0.6 (in
`cargo-risczero-x86_64-unknown-linux-gnu.tgz` of that release). About 1.2 GB of disk; 21 minutes to build on two
busy CPUs; then one to four minutes a proof.

```sh
R0VM=/path/to/r0vm ./run.sh fixtures/honest.txt succinct
python reference.py checks.txt fixtures/honest.txt     # the journal, with no proof
```

`RISC0_DEV_MODE` must be unset or 0: with it on, the receipt is a placeholder that proves nothing.

## The journal

70 bytes: version `01`, SHA-256 of the submission, SHA-256 of `checks.txt`, verdict (`01` passed, `00` not), cases
passed and cases, each two bytes little endian.

## Not here

A Groth16 receipt, a verifier on any chain, the supplier's function run inside the proof. The image id changes
with the compiler: `results.json` names the one that gave this id, and no build here is claimed reproducible.
