"""Cheats written OUTSIDE Knos: each one an account that is not Knos's (scripts/own_github_ids.json) submitted through
the `tamper` task (tasks/outside/tamper.json), and that the judge ACCEPTED, so it was paid 5 test USDC and joined the
tamper set here. A cheat the judge refused is not paid and is not added. None has been submitted yet.

Each case: (name, the author's GitHub account id, the pull request that carried it, the sample it attacks (a key of
scripts/tamper_bench.py SAMPLES), and a function that edits a copy of that sample's base as attacks.py's do). The
author's code is copied in as they wrote it, with a link to the pull request; scripts/tamper_bench.py --authors judges
every case again with the judge of this tree and reports it apart from the cheats Knos's authors wrote.
"""

from __future__ import annotations

CASES: list[tuple[str, int, str, str, object]] = []
