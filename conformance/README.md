# Knos conformance kit, version 3

Test vectors for Knos's formats, with expected results, and a runner that feeds them to any implementation:

    python conformance/run.py --impl "<the command that runs your implementation>"

- `manifest.json`: the kit's version, the formats, and the sha256 of each format's vectors.
- `vectors/`: the vectors of terms, ledger (formats 1 and 2), audiences, statement and ids. The receipt's are `docs/receipt/vectors.json`
  (versions 1 to 3) and `docs/receipt/vectors.v4.json` (version 4: four verdicts, the four ids, limitations).
- Version 2 of the kit added `receipt4` and `ids`; version 3 added `ledger2`, the batch commitment that hashes each
  whole event (written by `make_ledger2.py`). Neither changed a vector of the version before.
- `run.py`: the runner and the protocol (one line of JSON in for each case, one line out). Python 3.10, nothing else.
- `impl/knos_python.py`, `impl/knos_js.mjs`: Knos's own Python and its JavaScript client, as two examples.

What each format is, what is promised about it and what is not: [docs/CONFORMANCE.md](../docs/CONFORMANCE.md).
