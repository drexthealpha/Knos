# Knos conformance kit, version 4

Test vectors for Knos's formats, with expected results, and a runner that feeds them to any implementation:

    python conformance/run.py --impl "<the command that runs your implementation>"

- `manifest.json`: the kit's version, the formats, and the sha256 of each format's vectors.
- `vectors/`: the vectors of terms, ledger (formats 1 and 2), audiences, statement and ids. Receipt vectors live in `docs/receipt/`:
  `vectors.json` (receipt versions 1 to 3), `vectors.v4.json` (version 4: four verdicts, the four ids, limitations)
  and `vectors.v5.json` (version 5: the assurance level and the declared control relationships).
- Kit history: version 2 added receipt version 4 (`receipt4`) and `ids`. Version 3 added ledger format 2 (`ledger2`),
  the batch commitment that hashes each whole event (written by `make_ledger2.py`). Version 4 added receipt version 5
  (`receipt5`). No version changed an earlier vector.
- `run.py`: the runner and the protocol (one line of JSON in for each case, one line out). Python 3.10, nothing else.
- `impl/knos_python.py`, `impl/knos_js.mjs`: Knos's own Python and its JavaScript client, as two examples.

What each format is, what is promised about it and what is not: [docs/reference/CONFORMANCE.md](../docs/reference/CONFORMANCE.md).
