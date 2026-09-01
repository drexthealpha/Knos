"""The gate: something learned in one session, used by a fresh one.

Each half runs in its own process with its own MCP connection, so the second
one has never seen the first. That is the whole product in one test.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from knos import paths

# Invented for this test. No model could know it, and it appears in no file,
# so a correct answer can only have come from knos.
FACT = "the parser rewrite is codenamed Quokka and is owned by Tess Marlow"
SUBJECT = "parser rewrite"


async def _call(tool: str, args: dict, env: dict) -> str:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "knos.mcp"], env=env)
    async with stdio_client(params, errlog=subprocess.DEVNULL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return "".join(getattr(c, "text", "") for c in result.content)


def _env(home: Path, repo: Path) -> dict:
    env = dict(os.environ)
    env["KNOS_HOME"] = str(home)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    return env


def test_a_fresh_session_recalls_what_another_one_learned(knos_home, repo):
    paths.remember_pointed(repo)
    env = _env(knos_home, repo)

    # Session one: an agent learns something and writes it back.
    wrote = asyncio.run(_call("remember", {"fact": FACT, "about": SUBJECT}, env))
    assert "Remembered" in wrote

    # Session two: a different process, a new connection, no shared state.
    heard = asyncio.run(_call("search", {"query": "parser rewrite codename"}, env))
    assert "Quokka" in heard
    assert "source:" in heard


def test_the_fresh_session_starts_empty(knos_home, repo, tmp_path):
    """So the recall above is memory, not something ambient in the process."""
    paths.remember_pointed(repo)
    other = tmp_path / "elsewhere"
    other.mkdir()
    env = _env(other, repo)
    heard = asyncio.run(_call("search", {"query": "parser rewrite codename"}, env))
    assert "Quokka" not in heard


def test_the_four_tools_are_listed(knos_home, repo):
    async def run() -> list[str]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable, args=["-m", "knos.mcp"], env=_env(knos_home, repo)
        )
        async with stdio_client(params, errlog=subprocess.DEVNULL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return [t.name for t in (await session.list_tools()).tools]

    assert sorted(asyncio.run(run())) == ["about", "remember", "search", "sources"]
