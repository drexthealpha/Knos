# Knos conformance kit, version 1

Test vectors for Knos's formats, with expected results, and a runner that feeds them to any implementation:

    python conformance/run.py --impl "<the command that runs your implementation>"

- `manifest.json`: the kit's version, the formats, and the sha256 of each format's vectors.
- `vectors/`: the vectors of terms, ledger, audiences and statement. The receipt's are `docs/receipt/vectors.json`.
- `run.py`: the runner and the protocol (one line of JSON in for each case, one line out). Python 3.10, nothing else.
- `impl/knos_python.py`, `impl/knos_js.mjs`: Knos's own Python and its JavaScript client, as two examples.

What each format is, what is promised about it and what is not: [docs/CONFORMANCE.md](../docs/CONFORMANCE.md).
