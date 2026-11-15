# OK7-HERMES delivery (internal dogfooding)

## Delivery
Worker: OK-LIVE for the TASK-ONE-KNOS area agents. The work landed in drexthealpha/Knos branch `knos-0.3.34`, commit
169cfc08b337641b6cdc0556732525c94aba36c6 (base 511fb84b6027be0803393af5d99903a92e99a6e6):
https://github.com/drexthealpha/Knos/commit/169cfc08b337641b6cdc0556732525c94aba36c6

- Delivered patch (git diff --binary 511fb84b 169cfc08): 1133 files, sha256 4c9f4ea63213037a5b63b828f0f3c1de544bba663cd5dea55914f102b2d2a2bf. Knos's judge refuses it outright
  ("touches protected path": .github/**, .knos/**, and the integrator's home-only edits of existing tests).
- Judged patch = the same minus those paths (the product part): 505 files, sha256 84c88f6bede5b28c80f18054621a13eec2c42cf1f8ff449b71bb617d7fe58ee9.

## Knos's verdict (referee = Knos at 169cfc08, the buyer's sealed tests, cheat rules on, two runs)
- run 1: REFUSED; run 2: REFUSED; the runs agree: True.
- Hidden tests alone (diagnostic, cheat rules off): FAIL: OK7-HERMES: rules not met: 2.
- Cheat findings (refusing): hardcoded_answers @ check.py x1, hardcoded_answers @ evidence/knos-v0329-outcomes x10, references_sealed_bundle @ evidence/knos-v0329-outcomes x1, references_sealed_bundle @ scripts x1, references_sealed_bundle @ words.py x1, skip_added @ tests x1; the cheat findings are the same on every task and come from what the fold copies byte for byte: hardcoded_answers on evidence/knos-v0329-outcomes/.knos/vendor (a copy of another repository, with SOURCE.json) and on the playground's check.py; references_sealed_bundle on words.py, scripts/small_repos.py and that vendored recordio.py (code that writes or reads .knos/acceptance by design: the playground fold); skip_added on tests/test_fold_workflows_cutover.py:102 (`pytest.skip("needs git")` only when git is missing, which never happens where Knos runs).

## Buyer's decision: BUYER OVERRIDE (labelled)
Hidden rule 2 fails on one line: hermes/knos-hermes/SOURCE.json records the copy's source ("url": "https://github.com/drexthealpha/knos-hermes"), a provenance record tests/test_evidence_copies.py requires, not a live page (the public rule says "no live page links"). Rules 1 and 3 pass. Checked by the buyer: hermes/knos-hermes/pyproject.toml Homepage = drexthealpha/Knos/tree/knos-0.3.34/hermes/knos-hermes (PyPI shows it at the next upload), and the one comment on 0xNyk/awesome-hermes-agent#382 was posted 2026-10-15 11:06 UTC.
