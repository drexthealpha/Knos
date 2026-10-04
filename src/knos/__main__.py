"""`python -m knos ...` and the `knos` console script: the same commands.

The words a repository's workflow runs (knos.flow.WORDS), and `relay`, which the public worker runs, are handed to
knos.flow before the rest of the command line is imported: the jobs that sign or relay install only solders
(requirements/sign.txt), and the rest needs typer and rich."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    from . import flow
    if flow.takes(args):
        return flow.main(args)
    from .cli import main as rest
    return rest(args)


if __name__ == "__main__":
    raise SystemExit(main())
