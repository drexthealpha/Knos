"""The agent's own key and what its credentials may do: `knos agent init | show | rotate`, and `knos work list`.

An agent that takes paid work needs two things of its own, and this module holds both to their narrowest:

    a payout address   a Solana key made here, kept in KNOS_HOME/agent/key.json with mode 0600. It RECEIVES: nothing in
                       Knos's flow asks it to sign (the relayer pays every chain fee, and a wallet is bound to a GitHub
                       account by a GitHub-signed run, never by the wallet's signature). The file is written once and
                       never opened again by Knos: the address is kept beside it in agent.json, and that is all any
                       command or MCP tool reads. No command prints the key, and no tool result holds a byte of it.
    a GitHub token     KNOS_AGENT_TOKEN, else GH_TOKEN, else GITHUB_TOKEN. `narrow` says whether it is one the tools may
                       post with (PERMISSIONS says what it needs); a classic token that carries `repo` (every private
                       repository the account can reach) is refused unless the operator allowed it.

Nothing is posted unless the operator turned the acting tools on: `KNOS_AGENT_ACT=1`, or `knos agent init
--allow-actions` (kept in agent.json). Reading (finding work, what is held or paid) needs neither a key nor a token.
"""

from __future__ import annotations

import json
import os
import stat
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import paths

API = "https://api.github.com/"

# What the agent's GitHub token needs, as GitHub names the permissions. A fine-grained token has ONE resource owner and
# GitHub does not let it contribute to a public repository its user is not a member of (docs.github.com: "Managing your
# personal access tokens", the list of what fine-grained tokens do not support). So which token is the narrowest depends
# on who owns the repository that funded the work.
PERMISSIONS = (
    "The agent uses a GitHub account of its own (type User: `/knos take` is refused for a bot account), with a fork of the "
    "repository it works on and, to be paid, a repository named `knos-claim`.",
    "Repository the account is a member of (its own, or an organisation's it belongs to): a fine-grained token whose "
    "resource owner is that owner, limited to that repository, with Issues: Read and write (the `/knos take` comment), "
    "Pull requests: Read and write (opening the pull request) and Metadata: Read-only.",
    "Somebody else's public repository: GitHub gives a fine-grained token no write there, so the narrowest token is a "
    "classic one with the single scope `public_repo` (public repositories only; no private repository, no organisation "
    "administration, no deleting). Give it to an account that owns nothing but the fork and `knos-claim`.",
    "The fork and `knos-claim`, in the agent's own account: a fine-grained token limited to those two repositories with "
    "Contents: Read and write (pushing the branch), Workflows: Read and write (the claim workflow file), Actions: Read "
    "and write (starting the claim run) and Metadata: Read-only; Administration: Read and write only if Knos is to "
    "create `knos-claim` itself.",
    "Refused: a classic token with the `repo` scope, because it reaches every private repository the account can; "
    "`--allow-broad-token` (or KNOS_AGENT_BROAD_TOKEN=1) lets it through. The token of a plain `gh auth login` is one.",
)


class Cannot(Exception):
    """Why the agent's key or token cannot be used, in a sentence that says what to do next."""


def folder() -> Path:
    d = paths.home() / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _config() -> dict:
    try:
        got = json.loads((folder() / "agent.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _write(path: Path, text: str, new: bool = False) -> None:
    """Write `text` to a file only its owner can read (0600 from the moment it exists). `new`: refuse to replace one."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | (os.O_EXCL if new else os.O_TRUNC), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)      # an existing file keeps its mode through O_TRUNC


def _make(allow_actions: bool, allow_broad: bool) -> str:
    from solders.keypair import Keypair
    key = Keypair()
    address = str(key.pubkey())
    _write(folder() / "key.json", json.dumps(list(bytes(key))), new=True)      # the form `solana-keygen` writes: a wallet can import it
    _write(folder() / "agent.json", json.dumps({"address": address, "created": int(time.time()), "allow_actions": bool(allow_actions),
                                                 "allow_broad_token": bool(allow_broad)}, indent=1) + "\n")
    return address


def init(allow_actions: bool = False, allow_broad: bool = False) -> dict:
    """Make the agent's key, once. With a key already there only the two switches are written again: a second `init`
    never replaces a key that money may be on its way to (`rotate` does, and keeps the old file)."""
    have = _config()
    if have.get("address") and (folder() / "key.json").exists():
        have.update(allow_actions=bool(allow_actions), allow_broad_token=bool(allow_broad))
        _write(folder() / "agent.json", json.dumps(have, indent=1) + "\n")
        return {**show(), "made": False}
    return {**show(_make(allow_actions, allow_broad)), "made": True}


def rotate() -> dict:
    """A new key. The old file is kept beside it under its address (what was paid there is still that key's), and the
    GitHub account stays bound to the old address until `knos_collect` or `knos claim <new address>` binds the new one."""
    have = _config()
    old, key = have.get("address"), folder() / "key.json"
    if not old or not key.exists():
        raise Cannot("There is no agent key to rotate. `knos agent init` makes one.")
    key.rename(folder() / f"key.{old}.json")
    return {**show(_make(bool(have.get("allow_actions")), bool(have.get("allow_broad_token")))), "made": True, "replaced": old}


def address() -> str | None:
    """The agent's payout address, from agent.json. The key file is not opened."""
    got = _config().get("address")
    return got if isinstance(got, str) and got else None


def show(known: str | None = None) -> dict:
    """What there is to say about the key without reading it: its address, where it is, whether only its owner can
    read it, and the two switches."""
    key = folder() / "key.json"
    try:
        mode = stat.S_IMODE(key.stat().st_mode)
    except OSError:
        mode = None
    return {"address": known or address(), "key_file": str(key), "key_mode": None if mode is None else f"{mode:04o}",
            "only_owner_can_read": mode is not None and not mode & 0o077, "actions": actions(), "broad_token_allowed": broad_allowed(),
            "signs": "nothing: it is the address payments arrive at; the relayer pays chain fees"}


def actions() -> bool:
    """Whether the tools that post (take, submit, bind) are on."""
    return os.environ.get("KNOS_AGENT_ACT") == "1" or bool(_config().get("allow_actions"))


def broad_allowed() -> bool:
    return os.environ.get("KNOS_AGENT_BROAD_TOKEN") == "1" or bool(_config().get("allow_broad_token"))


def token() -> str | None:
    return os.environ.get("KNOS_AGENT_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None


def scopes_of(tok: str) -> list[str] | None:
    """A classic token's scopes, as GitHub states them in `X-OAuth-Scopes` on any answer. None: GitHub did not say."""
    req = urllib.request.Request(API + "user", headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": "knos"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - api.github.com
            said = resp.headers.get("X-OAuth-Scopes")
    except OSError:
        return None
    return None if said is None else [s.strip() for s in said.split(",") if s.strip()]


def narrow(tok: str | None, scopes: Callable[[str], list[str] | None] = scopes_of) -> str:
    """What kind of token this is, once it is known to be one the tools may post with. Raises Cannot for none, for a
    classic token that carries `repo`, and for one whose scopes GitHub did not state (not known is not narrow)."""
    if not tok:
        raise Cannot("no GitHub token is set (KNOS_AGENT_TOKEN, GH_TOKEN or GITHUB_TOKEN). `knos agent show` lists what it needs")
    if tok.startswith("github_pat_"):
        return "fine-grained"       # limited to the repositories and permissions its owner chose
    if tok.startswith(("ghs_", "ghu_")):
        return "app"                # an app's token: limited to where the app is installed
    if broad_allowed():
        return "classic, allowed by the operator"
    got = scopes(tok)
    if got is None:
        raise Cannot("GitHub did not say which scopes this token has, so it is not known to be a narrow one. Use a fine-grained token, "
                     "or allow it with `knos agent init --allow-broad-token`")
    if "repo" in got:
        raise Cannot("this is a classic token with the `repo` scope: it can write to every repository the account reaches, private ones "
                     "included. Use a fine-grained token or a classic one with only `public_repo` (`knos agent show` says which), or allow "
                     "this one with `knos agent init --allow-broad-token`")
    return "classic: " + (", ".join(got) or "no scopes")


def send(method: str, path: str, body: dict) -> dict:
    """One write to api.github.com with the agent's token. The MCP tools return exactly what was given here."""
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method=method,
                                 headers={"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json", "User-Agent": "knos"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - api.github.com
        return json.loads(resp.read() or b"{}")


def register(app) -> None:
    """`knos agent init | show | rotate` and `knos work list`."""
    import typer

    agent = typer.Typer(no_args_is_help=True, help="A coding agent's own payout key, and what its GitHub token may do.")
    work = typer.Typer(no_args_is_help=True, help="Funded work an agent can take: open, unreserved orders, from the chain.")

    def said(got: dict) -> None:
        typer.echo(f"Payout address: {got['address']}\nKey file: {got['key_file']} (mode {got['key_mode']}; "
                   f"{'only you can read it' if got['only_owner_can_read'] else 'OTHERS CAN READ IT: run chmod 600 on it'})\n"
                   f"It signs {got['signs']}.\nTools that post (take, submit, bind): {'on' if got['actions'] else 'off (KNOS_AGENT_ACT=1 or --allow-actions)'}.\n"
                   f"A classic token with `repo`: {'allowed' if got['broad_token_allowed'] else 'refused'}.")

    @agent.command("init")
    def _init(allow_actions: bool = typer.Option(False, "--allow-actions", help="let the MCP tools post: take, submit, bind"),
              allow_broad_token: bool = typer.Option(False, "--allow-broad-token", help="accept a classic token that has the `repo` scope")) -> None:
        """Make the agent's payout key (once) and set what the tools may do. The key is never printed."""
        got = init(allow_actions, allow_broad_token)
        typer.echo("Made a new key." if got["made"] else "The key was already there; it was not replaced.")
        said(got)

    @agent.command("show")
    def _show() -> None:
        """The payout address, the key file's permissions, the switches, and the permissions a GitHub token needs."""
        if not address():
            typer.echo("There is no agent key yet. `knos agent init` makes one.")
            raise typer.Exit(1)
        said(show())
        typer.echo("\nThe GitHub token:\n" + "\n".join("  - " + p for p in PERMISSIONS))

    @agent.command("rotate")
    def _rotate() -> None:
        """A new key; the old file is kept. Bind the new address before the next payment (`knos_collect` does)."""
        try:
            got = rotate()
        except Cannot as why:
            typer.echo(str(why))
            raise typer.Exit(1) from None
        typer.echo(f"The old key is kept as key.{got['replaced']}.json; the account stays bound to it until the new address is bound.")
        said(got)

    @work.command("list")
    def _list(repo: str = typer.Option("", "--repo", help="only this repository, as owner/name"),
              label: str = typer.Option("", "--label", help="only issues with this label (a language label such as python)"),
              min_usdc: int = typer.Option(0, "--min", help="at least this many test USDC"),
              mode: str = typer.Option("", "--mode", help="merge, tests or auto"),
              limit: int = typer.Option(20, "--limit", min=1, max=50),
              as_json: bool = typer.Option(False, "--json")) -> None:
        """Open, unreserved, funded work, largest first: what `knos_find_work` answers. Reads only; needs no key."""
        from . import mcp
        args = {"limit": limit, **({"repo": repo} if repo else {}), **({"label": label} if label else {}),
                **({"min_usdc": min_usdc} if min_usdc else {}), **({"mode": mode} if mode else {})}
        try:
            got = mcp.Server()._find_work(args)
        except mcp.Failed as why:
            typer.echo(str(why))
            raise typer.Exit(1) from None
        if as_json:
            typer.echo(json.dumps(got, indent=1))
            return
        for w in got["work"]:
            typer.echo(f"{w['amount_usdc'] or w['amount_units']} {w['money']}  {w['repo'] or w['repo_id']}#{w['issue']}  {w['mode']}  "
                       f"until {w['deadline']}\n    {w['acceptance']['command'] or w['acceptance']['note']}")
        typer.echo(got["said"])

    app.add_typer(agent, name="agent")
    app.add_typer(work, name="work")
