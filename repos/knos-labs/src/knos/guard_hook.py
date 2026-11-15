"""What a client's hook runner actually executes.

Its own module rather than a CLI subcommand, so a hook is one process that
imports almost nothing: `python -m knos.guard_hook` starts, reads one JSON
payload, prints one line and exits. Typer and rich are not on this path
because it runs before every edit an agent makes and a tenth of a second
there is a tenth of a second on every keystroke's worth of work.

Exit 2 is the refusal. Every client here honours it, and each also gets the
JSON shape it prefers on stdout, so a schema that moves under us costs the
nice message and not the refusal itself.

Anything unexpected exits 0. A guard that fails closed would put a broken
install between an agent and its own repository, which is worse than the
collision it exists to prevent.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    client = "claude"
    if "--client" in args:
        at = args.index("--client")
        if at + 1 < len(args):
            client = args[at + 1]

    try:
        said = sys.stdin.read()
    except (OSError, ValueError):
        return 0

    try:
        from . import guard

        out, code = guard.run(client, said)
    except Exception:
        # Import failure, an unreadable store, a repo that is not a repo.
        # None of those are grounds to stop somebody working.
        return 0

    if out:
        try:
            sys.stdout.write(out)
            sys.stdout.flush()
        except (OSError, ValueError, UnicodeError):
            # a closed pipe or a console code page that cannot encode a quoted path must not turn into a
            # traceback and a nonzero exit; the refusal (exit 2) or the allow (exit 0) still stands
            pass
    return code


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
