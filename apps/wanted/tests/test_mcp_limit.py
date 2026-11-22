"""An agent's MCP session is dozens of messages (initialize, tools/list, reading a round, claiming, submitting): they
have their own allowance, and only the tools that run a check count against the 30 checks per 10 minutes. Before, every
message drew on the check limit and an agent was cut off halfway through one paid task (a measured run)."""
from test_round9 import app, call  # noqa: F401 - the app fixture

from knos_wanted import server


def test_forty_tool_listings_from_one_address_are_not_rate_limited(app):  # noqa: F811
    base, _st = app
    codes = [call(base, "/mcp", {"jsonrpc": "2.0", "id": i, "method": "tools/list"})[0] for i in range(40)]
    assert codes.count(429) == 0, codes


def test_the_tools_that_run_a_check_still_count_as_checks():
    assert "knos_demand_check" in server.MCP_CHECK_TOOLS and server.LIMITS["check"][0] < server.LIMITS["mcp"][0]
