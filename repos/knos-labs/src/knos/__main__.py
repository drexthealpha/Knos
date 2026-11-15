"""`python -m knos ...`: the same commands as the `knos` script.

Host configs written by knos 0.1 start the MCP server as `<python> -m knos plane mcp`; `cli.main` maps that to
`knos mcp`, so an old config still starts the server after an upgrade.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
