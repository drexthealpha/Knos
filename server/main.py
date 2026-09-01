"""Entry point for the Claude Desktop extension.

The extension does not carry a copy of knos. It runs the one you installed
with `pip install knos`, so there is one memory on this machine rather than a
second one living inside an extension bundle. That also sidesteps the thing
the packaging format warns about: a Python bundle cannot portably ship
compiled dependencies, and the MCP SDK needs some.

If knos is not importable, say so in a sentence a person can act on rather
than letting an import error surface as a failed connection.
"""

import sys

try:
    from knos.mcp import main
except ModuleNotFoundError:
    sys.stderr.write(
        "knos is not installed for this Python.\n"
        "Install it:  pip install knos\n"
        "Then set this extension's Python to the one you installed it into.\n"
    )
    raise SystemExit(1)

if __name__ == "__main__":
    main()
