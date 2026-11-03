"""Knos as a Hermes Agent plugin: `register(ctx)` adds four tools (and the money engine's quote tools when this install
has knos.money.agent).

    knos_verify          run Knos on a committed change before a pull request: AI policy, cheat checks, tests twice, signed receipt
    knos_receipt         check a receipt: shape, digest, ed25519 signature, and what it says
    knos_bounty_claim    what a funded issue pays and the steps to claim it (the `/knos take` comment); sends nothing
    knos_outcome_check   whether an outcome's measurement drifted from what was funded (spec, window, salt, control share, data)

Loaded by Hermes from the pip entry point group "hermes_agent.plugins" (knos = "knos.hermes_plugin:register", in
knos's pyproject.toml), or from a directory plugin (hermes/plugin/knos/ in the Knos repository, which imports this).
Hermes's contract (hermes_cli/plugins.py, PluginContext.register_tool; website/docs/developer-guide/plugins/index.md):
a handler is `handler(args: dict, **kwargs) -> str` returning JSON, and never raises.

Nothing here posts, signs a transaction or opens a key file; knos_verify signs its receipt with the verify key
(knos.verify.receipt), which is not a wallet.
"""

from __future__ import annotations

import json
from pathlib import Path

TOOLSET = "knos"


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


SCHEMAS = {
    "knos_verify": _schema(
        "knos_verify",
        "Before opening a pull request: run Knos on the committed change. Reads the repository's AI policy at the base "
        "(stance banned means do not open one), runs the cheat checks and the repository's tests twice in a throwaway "
        "clone, and returns a signed receipt plus pr_markdown for the description (it discloses AI use). Public tests "
        "only; hidden tests run in the repository's Knos Gate, never here.",
        {"path": _str("the checkout, with the change committed"), "base": _str("the base branch (default: origin/HEAD, main or master)"),
         "tests": _str("the test command, when the repository's is not found"), "runs": {"type": "integer", "minimum": 1, "maximum": 3, "description": "test runs (default 2)"},
         "agent": _str("the agent's name for the AI-use line (default Hermes Agent)"), "out": _str("where to write the receipt JSON")},
        ["path"]),
    "knos_receipt": _schema(
        "knos_receipt",
        "Check a Knos verify receipt file: well formed, digest and ed25519 signature verify, and what it says.",
        {"file": _str("the receipt JSON file")}, ["file"]),
    "knos_bounty_claim": _schema(
        "knos_bounty_claim",
        "What a funded GitHub issue pays (test USDC on Solana devnet) and the steps to claim it: the `/knos take` comment "
        "to post, then knos_verify, then a pull request that says `Fixes #<issue>`. Sends nothing.",
        {"issue": _str("the issue, as owner/repo#number")}, ["issue"]),
    "knos_outcome_check": _schema(
        "knos_outcome_check",
        "Whether an outcome measurement drifted from what was funded: spec hash, measurement window, salt, control share "
        "(tolerance 0.02 by default), measurement code and data hashes. Two JSON files; reads only.",
        {"funded": _str("JSON file: the outcome as committed at funding"), "now": _str("JSON file: the outcome as seen at measurement")},
        ["funded", "now"]),
}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _guard(fn):
    """A Hermes handler: args in, JSON text out, never an exception."""
    def handler(args: dict, **kwargs) -> str:
        try:
            return _json(fn(args if isinstance(args, dict) else {}))
        except Exception as why:  # noqa: BLE001 - Hermes's contract: never raise
            return _json({"error": f"{type(why).__name__}: {' '.join(str(why).split())[:300]}"})
    handler.__name__ = getattr(fn, "__name__", "handler")
    return handler


def verify_tool(args: dict) -> dict:
    from .verify import tools
    if not args.get("path"):
        return {"error": "path is required: the checkout with the change committed"}
    return tools.knos_verify({"agent": "Hermes Agent", **args})


def receipt_tool(args: dict) -> dict:
    from .verify import tools
    if not args.get("file"):
        return {"error": "file is required"}
    return tools.knos_receipt(args)


def bounty_claim(args: dict, server=None) -> dict:
    """knos_bounty and knos_take of the MCP server, in one answer, with the steps in order."""
    from . import mcp
    issue = str(args.get("issue") or "").strip()
    if not mcp._ISSUE.fullmatch(issue):
        return {"error": "issue must be owner/repo#number, e.g. octo/widgets#7"}
    srv = server or mcp.Server()

    def call(name: str, a: dict) -> dict:
        got = srv._call({"name": name, "arguments": a})
        text = got["content"][0]["text"] if got.get("content") else ""
        return got.get("structuredContent") or {"error": text}
    bounty = call("knos_bounty", {"issue": issue})
    take = call("knos_take", {"issue": issue})
    number = issue.rsplit("#", 1)[-1]
    return {"issue": issue, "bounty": bounty, "take": take,
            "steps": ["post the `take` comment on the issue (as the account that will open the pull request), if the bounty takes reservations",
                      "make the change and commit it",
                      "run knos_verify on the checkout; open nothing unless its verdict is pass",
                      f"open the pull request with `Fixes #{number}` and the receipt's pr_markdown in its description",
                      "payment goes to the wallet bound to the author's GitHub account (`knos claim <address>`), else it is held for the account"],
            "sends": "nothing"}


_OUTCOME_KEYS = ("spec_hash", "window", "salt", "measurement_commit")


def outcome_check(args: dict) -> dict:
    """The referee's knos.cheats.scan_outcome when this install has it; else the same comparisons, locally."""
    funded = json.loads(Path(str(args["funded"])).expanduser().read_text(encoding="utf-8"))
    now = json.loads(Path(str(args["now"])).expanduser().read_text(encoding="utf-8"))
    try:
        from . import cheats  # type: ignore[attr-defined]
        found = cheats.scan_outcome(funded, now)
        rows = [f if isinstance(f, dict) else {k: getattr(f, k, "") for k in ("rule", "category", "path", "detail", "severity")} for f in found]
        return {"engine": "knos.cheats", "findings": rows, "drifted": bool(rows)}
    except (ImportError, AttributeError):
        pass
    rows = []
    names = {"spec_hash": "spec_hash_changed", "window": "window_changed", "salt": "salt_changed", "measurement_commit": "measurement_code_drift"}
    for key in _OUTCOME_KEYS:
        if funded.get(key) != now.get(key):
            rows.append({"rule": names[key], "category": names[key], "path": key, "detail": f"{key} differs from what was funded", "severity": "refuse"})
    try:
        if abs(float(funded.get("control_share", 0)) - float(now.get("control_share", 0))) > 0.02:
            rows.append({"rule": "control_drift", "category": "control_drift", "path": "control_share", "detail": "control share moved more than 0.02", "severity": "refuse"})
    except (TypeError, ValueError):
        rows.append({"rule": "control_drift", "category": "control_drift", "path": "control_share", "detail": "control share is not a number", "severity": "refuse"})
    a, b = funded.get("data_hashes") or {}, now.get("data_hashes") or {}
    for path in sorted(set(a) | set(b)):
        if a.get(path) != b.get(path):
            rows.append({"rule": "data_tampering", "category": "data_tampering", "path": str(path), "detail": "a data file's hash changed", "severity": "refuse"})
    return {"engine": "local", "findings": rows, "drifted": bool(rows)}


HANDLERS = {"knos_verify": verify_tool, "knos_receipt": receipt_tool, "knos_bounty_claim": bounty_claim,
            "knos_outcome_check": outcome_check}


def _register_tools(ctx) -> None:
    """The tools `register` adds."""
    for name, fn in HANDLERS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=SCHEMAS[name], handler=_guard(fn),
                          description=SCHEMAS[name]["description"], emoji="")
    try:                                    # MONEY's quote and plan tools (knos.money.agent), when this install has them
        from .money import agent as money_agent  # type: ignore[attr-defined]
    except ImportError:
        return
    for t in getattr(money_agent, "TOOLS", []):
        schema = t.get("inputSchema") or {"type": "object", "properties": t.get("properties", {}), "required": t.get("required", [])}
        ctx.register_tool(name=t["name"], toolset=TOOLSET,
                          schema={"name": t["name"], "description": t["description"], "parameters": schema},
                          handler=_guard(lambda a, n=t["name"]: money_agent.call(n, a)), description=t["description"])


# -- the pre_tool_call hook: stop a write Knos would refuse to pay, before the agent spends the work on it ----------------
# Hermes plugin hooks (hermes-agent.nousresearch.com/docs/user-guide/features/hooks, read 14 Oct 2026): a callback gets
# keyword arguments (tool_name, args, task_id, ...) and may return {"action": "block", "message": ...}. Off unless
# KNOS_HERMES_GUARD=block (or warn: never blocks, logs to stderr). It reads the path a file-writing tool names and
# applies the rules no maintainer pays past: a workflow (.github/), the Gate config and seal (.knos/), the test runner's
# configuration, and an existing test file edited (knos.gate.cheatlib's categories). A new test file is not blocked.
_PATH_KEYS = ("path", "file_path", "filepath", "file", "target", "filename")
_RUNNER_FILES = ("conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "sitecustomize.py", "usercustomize.py", "noxfile.py")


def _paths(args) -> list[str]:
    if not isinstance(args, dict):
        return []
    out = [str(args[k]) for k in _PATH_KEYS if isinstance(args.get(k), str)]
    for k in ("paths", "files"):
        if isinstance(args.get(k), list):
            out += [str(x) for x in args[k] if isinstance(x, str)]
    return out


def refused_write(path: str, root: str | None = None) -> str | None:
    """Why Knos would refuse a change that writes `path` (repository-relative or absolute under `root`), or None."""
    import os
    p = path.replace("\\", "/")
    if root:
        r = os.path.abspath(root).replace("\\", "/").rstrip("/") + "/"
        if os.path.abspath(p).replace("\\", "/").startswith(r):
            p = os.path.abspath(p).replace("\\", "/")[len(r):]
    # normalised as a path, never stripped as characters: "./.github/x".lstrip("./") was "github/x" and passed the guard
    import posixpath
    p = posixpath.normpath(p) if p else p
    while p.startswith("./"):
        p = p[2:]
    name = p.rsplit("/", 1)[-1]
    if p.startswith(".github/") or "/.github/" in p:
        return "workflow_edited: GitHub would run the pull request's own copy of a workflow; Knos refuses the change"
    if p.startswith(".knos/") or "/.knos/" in p:
        return "sealed_tests_changed: .knos/ holds the Gate config and its seal; Knos refuses the change"
    if name in _RUNNER_FILES or name.endswith(".pth"):
        return "runner_tampering: this file changes how tests are found or run; Knos refuses the change"
    is_test = name.startswith("test_") or name.endswith(("_test.py", ".test.js", ".test.ts", ".spec.ts", ".spec.js")) or "/tests/" in f"/{p}"
    if is_test and root and os.path.exists(os.path.join(root, p)):
        return "test_edited: an existing test is edited; Knos pays for code that passes the tests, not for changed tests"
    return None


def pre_tool_call(tool_name: str = "", args=None, **kwargs):
    import os
    import sys
    how = (os.environ.get("KNOS_HERMES_GUARD") or "").strip().lower()
    if how not in ("block", "warn"):
        return None
    root = kwargs.get("cwd") or os.getcwd()
    for p in _paths(args):
        why = refused_write(p, root)
        if why:
            msg = f"Knos: writing {p} would get this work refused ({why}). Change the code under test instead."
            if how == "block":
                return {"action": "block", "message": msg}
            print(msg, file=sys.stderr)
    return None


def register(ctx) -> None:
    """Hermes calls this once when the plugin loads: the tools, then the hook (a Hermes without register_hook gets the
    tools only)."""
    _register_tools(ctx)
    hook = getattr(ctx, "register_hook", None)
    if callable(hook):
        hook("pre_tool_call", pre_tool_call)
