"""`python -m knos ...` and the `knos` console script: the same commands.

The words a repository's workflow runs (knos.flow.WORDS), and `relay`, which the public worker runs, are handed to
knos.flow before the rest of the command line is imported: the jobs that sign or relay install only solders
(requirements/sign.txt), and the rest needs typer and rich.

Nothing is imported until the command line says it is needed: `knos --version` answers from the package's metadata
alone, and knos.flow (which brings solders) is imported only for a word that could be its own. FLOW_FIRST repeats
knos.flow's WORDS and MORE so that asking does not cost the import; tests/test_startup.py holds the two equal."""

from __future__ import annotations

import sys


FLOW_FIRST = ("command", "settle", "review", "check", "attest", "canary", "relay")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        from . import version
        sys.stdout.write(f"knos {version()}\n")
        return 0
    if args and args[0] in FLOW_FIRST:
        from . import flow
        if flow.takes(args):
            return flow.main(args)
    from .cli import main as rest
    return rest(args)


if __name__ == "__main__":
    raise SystemExit(main())
