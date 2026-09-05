"""Entry point for the Claude Desktop extension.

The bundle declares `knos` as a dependency in the pyproject.toml beside this
file, and the host resolves it with uv when the extension is installed. That
is the whole reason this path is one click: the older bundle shipped no code
and asked the person to find and paste the Python they had installed knos
into, which is not an install, it is homework.

Nothing here reimplements anything. It hands straight over to the same
`knos.mcp` the pip install and the Claude Code plugin both run, so there is
one memory on this machine rather than a second one living inside a bundle.
"""

import sys

try:
    from knos.mcp import main
except ModuleNotFoundError:  # pragma: no cover - the host resolves this
    # Reachable only if the host skipped dependency resolution. Say the one
    # thing a person can act on rather than letting an import error surface
    # as a connection that silently failed.
    sys.stderr.write(
        "knos is not installed for this Python.\n"
        "The extension declares it in pyproject.toml and the host normally\n"
        "installs it. If you are running this file by hand: pip install knos\n"
    )
    raise SystemExit(1)

if __name__ == "__main__":
    main()
