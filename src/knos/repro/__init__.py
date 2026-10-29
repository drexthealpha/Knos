"""knos.yml and "Reproduced by Knos": re-run a research repository's claims on a second machine and a held-out split.

    knos reproduce PATH [--spec knos.yml] [--heldout DIR] [--out DIR]

PATH is a research repository (a folder) holding knos.yml. The spec (knos.repro.spec) names the entry point, each claim
(metric, expected value, tolerance) and the compute budget. Knos runs it (knos.repro.run), judges each claim, and writes
the result to the PRIVATE folder first (knos.repro.publish). Only a reproduced result is published, with a badge and a
result page per claim; a contested one goes to the authors privately and is never published. docs/reference/REPRODUCE.md.
"""
from __future__ import annotations

from .publish import LABEL, NotPublishable, badge_svg, checks, keep  # noqa: F401  (publish: the module; knos.repro.publish.publish the function)
from .run import FORMAT, STATUSES, reproduce  # noqa: F401
from .spec import SpecError, load, normalise, parse  # noqa: F401
