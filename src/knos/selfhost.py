"""Knos in the buyer's own cloud: one image, three roles, one config file (deploy/, docs/SELFHOST.md).

    knos selfhost check CONFIG [--files]   validate knos.toml; print what will run and which key files it needs
    knos selfhost plan [CONFIG]            the compose services that config starts, and the command that starts them
    python -m knos.selfhost run ROLE --config CONFIG     what each container runs (record, relay or site)

THE ROLES. One image (deploy/Dockerfile), run three ways:

    record   the record API, `knos record serve` (knos.record_api), on the buyer's records
    relay    the relay worker (`knos relay --serve`, knos.settle.v2.relayq) paying fees from the BUYER'S own fee payer
    site     the static site, built into the image, the approver included (#approve); it reads files the reader
             drops and asks no host but itself

THE CONFIG. TOML. Chain (cluster, RPC, program ids), keys BY FILE PATH (never inline: a value that looks like a key
is refused), and one table per role. Nothing here holds a secret: `run` reads each key file when the container starts
and hands it to the role in the variable the role already reads (KNOS_RELAY_KEY, KNOS_RELAY_KEYS, GH_TOKEN).

Knos runs none of this and hosts nothing: the buyer runs it. It has not been run in any cloud. There is no single
sign-on in it: the ports are bound to 127.0.0.1 and docs/SELFHOST.md says how to put an identity proxy in front.

ONE BUYER A DEPLOYMENT. Each deployment reads its own records folder and keeps its counts in its own tenant of the
memory store (record.tenant): two deployments sharing one memory folder never read each other's counts, and the
record API serves no file outside its own folder (no link, no `..`). The record API limits each client (record.rate
requests a second, record.burst at once) and checks every input (knos.record_api, ROUTES).

Standard library at import (tomllib, or tomli before 3.11, as .knos/proof.toml is read).
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROLES = ("record", "relay", "site")
CLUSTERS = ("devnet", "localnet")          # knos.chain refuses mainnet; so does this, before anything starts
PROGRAMS = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")     # what knos.settle.v2.load_ids lets a file replace
STATE = Path("/var/lib/knos")              # the container's writable folder (a volume per service)
SITE = Path("/srv/knos/site")              # where the image keeps the built site
CONFIG = Path("/etc/knos/knos.toml")       # where compose mounts the config
PORTS = {"record": 8402, "site": 8080}     # inside the container; compose publishes them on 127.0.0.1 only
KEYS = {    # name in [keys]: (which role needs it, what it is for)
    "relay": ("relay", "the fee payer: a Solana keypair file; it pays transaction fees and holds no one's money"),
    "relay_more": ("relay", "more fee payers (a list of keypair files): one fee account per order in flight"),
    "github_token": ("relay", "a file with a GitHub token that may read the buyer's repositories' comments"),
    "record": ("record", "the operator's signing key for paid answers (a keypair file); without it answers are unsigned"),
}
_TABLES = {"chain", "keys", *ROLES}
_SECRETISH = re.compile(r"(key|token|secret|password)", re.I)
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@dataclass
class Checked:
    """What `check` found: `errors` stop it; `missing` are files not on this machine (an error only with --files)."""
    config: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def roles(self) -> list[str]:
        return [r for r in ROLES if isinstance(self.config.get(r), dict) and self.config[r].get("enabled", True)]

    def ok(self, files: bool = False) -> bool:
        return not self.errors and not (files and self.missing)


def _toml(text: str) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib
    else:       # pragma: no cover - the wheel names tomli for these
        import tomli as tomllib
    return tomllib.loads(text)


def address(text: object) -> bool:
    """A Solana address: base58 of 32 bytes."""
    if not isinstance(text, str) or not 32 <= len(text) <= 44 or any(c not in _B58 for c in text):
        return False
    n = 0
    for c in text:
        n = n * 58 + _B58.index(c)
    pad = len(text) - len(text.lstrip("1"))
    return pad + (n.bit_length() + 7) // 8 == 32


def _inline(value: str) -> bool:
    """Whether a string is a key itself rather than the path of one: a JSON array of numbers, or a long run of base58
    or base64 with no slash."""
    v = value.strip()
    return v.startswith("[") or (len(v) >= 40 and "/" not in v and re.fullmatch(r"[A-Za-z0-9+=_\-]+", v) is not None)


def check(text: str, base: Path | None = None) -> Checked:
    """Validate a knos.toml. `base`: the folder relative paths are read from (the config's own)."""
    try:
        cfg = _toml(text)
    except ValueError as why:
        return Checked({}, [f"not TOML: {why}"])
    c = Checked(cfg)
    err = c.errors.append
    for name in cfg:
        if name not in _TABLES:
            err(f"[{name}] is not a table this file has (it has {', '.join(sorted(_TABLES))})")
    chain: dict[str, Any] = cfg["chain"] if isinstance(cfg.get("chain"), dict) else {}
    if "chain" not in cfg:
        err("[chain] is missing: name the cluster and the RPC endpoint")
    cluster = chain.get("cluster", "devnet")
    if cluster not in CLUSTERS:
        err(f"chain.cluster is {cluster!r}: Knos runs on {' or '.join(CLUSTERS)} only (the programs are not on mainnet)")
    rpc = chain.get("rpc")
    if not isinstance(rpc, str) or not re.match(r"https?://[^\s/]+", rpc):
        err("chain.rpc must be the RPC endpoint's URL (https://...)")
    elif "mainnet" in rpc:
        err(f"chain.rpc {rpc} names mainnet: Knos runs on devnet only")
    programs = chain.get("programs", {})
    if not isinstance(programs, dict):
        err("chain.programs is a table of program ids (leave it out to use the pinned ones)")
        programs = {}
    for name, value in programs.items():
        if name not in PROGRAMS:
            err(f"chain.programs.{name}: only {', '.join(PROGRAMS)} can be named; the rest are fixed by the programs")
        elif not address(value):
            err(f"chain.programs.{name} = {value!r} is not a Solana address")
    keys = cfg.get("keys", {})
    if not isinstance(keys, dict):
        err("[keys] is a table of file paths")
        keys = {}
    for name, value in keys.items():
        if name not in KEYS:
            err(f"keys.{name} is not a key any role reads (they are {', '.join(KEYS)})")
            continue
        for one in value if isinstance(value, list) else [value]:
            if not isinstance(one, str) or not one.strip():
                err(f"keys.{name} must be a file path")
            elif _inline(one):
                err(f"keys.{name} holds a key itself: name the FILE that holds it; a key never goes in this file")
            elif not _file(one, base).is_file():
                c.missing.append(f"keys.{name}: {one}")
    for table, body in cfg.items():
        if table in ("keys",) or not isinstance(body, dict):
            continue
        for k, v in body.items():
            if _SECRETISH.search(k) and isinstance(v, str) and _inline(v):
                err(f"{table}.{k} looks like a secret written inline: keys go in [keys], by file path")
    roles = c.roles()
    if not roles:
        err("no role is enabled: add [record], [relay] or [site]")
    for role in roles:
        body = cfg[role]
        for k in body:
            if k not in _ROLE_FIELDS[role]:
                err(f"{role}.{k} is not a setting of {role} (it has {', '.join(sorted(_ROLE_FIELDS[role]))})")
        for name, (who, _what) in KEYS.items():
            if who == role and name in _NEEDED[role] and name not in keys:
                err(f"{role} needs keys.{name}: {KEYS[name][1]}")
    if "record" in roles:
        r = cfg["record"]
        if not isinstance(r.get("offer"), str):
            err("record.offer must be the path of the seller's offer file (knos.record_api.offer as JSON)")
        for k in ("offer", "suppliers"):
            if isinstance(r.get(k), str) and not _file(r[k], base).is_file():
                c.missing.append(f"record.{k}: {r[k]}")
        t = r.get("tenant")
        if t is not None and (not isinstance(t, str) or len(t) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", t)):
            err("record.tenant names this deployment: lower-case letters, digits and single dashes, 64 at most")
        for k, lo, hi in (("rate", 1, 1000), ("burst", 1, 10000), ("ttl", 60, 86400)):
            v = r.get(k)
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi):
                err(f"record.{k} must be a whole number from {lo} to {hi}")
    if "relay" in roles:
        r = cfg["relay"]
        repos = r.get("repos")
        if not isinstance(repos, list) or not repos or not all(isinstance(x, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", x) for x in repos):
            err("relay.repos must list the buyer's repositories as owner/name: the relay reads tokens posted there")
        for k, lo, hi in (("workers", 1, 64), ("every", 1, 3600), ("serve", 60, 86400)):
            v = r.get(k)
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi):
                err(f"relay.{k} must be a whole number from {lo} to {hi}")
    return c


_ROLE_FIELDS = {
    "record": {"enabled", "offer", "records", "history", "suppliers", "ttl", "tenant", "rate", "burst"},
    "relay": {"enabled", "repos", "workers", "every", "serve"},
    "site": {"enabled"},
}
_NEEDED = {"record": (), "relay": ("relay", "github_token"), "site": ()}


def _file(path: str, base: Path | None) -> Path:
    p = Path(path)
    return p if p.is_absolute() or base is None else base / p


def needs(c: Checked) -> list[tuple[str, str, str]]:
    """(role, key name, path) of every key file the enabled roles read."""
    keys = c.config.get("keys", {})
    got = []
    for name, (role, _what) in KEYS.items():
        if role in c.roles() and name in keys:
            for one in keys[name] if isinstance(keys[name], list) else [keys[name]]:
                got.append((role, name, one))
    return got


def services(c: Checked) -> list[dict[str, Any]]:
    """The compose services this config starts (deploy/compose.yaml defines all three; these are the ones to name)."""
    out = []
    for role in c.roles():
        out.append({"service": role, "command": ["run", role, "--config", CONFIG.as_posix()],
                    "port": PORTS.get(role), "state": f"knos-{role}:{STATE}" if role != "site" else None,
                    "keys": [path for r, _n, path in needs(c) if r == role]})
    return out


def describe(c: Checked, files: bool = False) -> list[str]:
    """What `check` prints."""
    if c.errors:
        return ["This config is refused:"] + [f"  - {e}" for e in c.errors]
    chain = c.config.get("chain", {})
    progs = chain.get("programs") or {}
    lines = [f"Chain: {chain.get('cluster', 'devnet')} through {chain['rpc']}; programs: "
             + (", ".join(f"{k} {v}" for k, v in progs.items()) + " (a staging deployment; the rest pinned)" if progs else "the pinned ids"),
             "Will run:"]
    what = {"record": "the record API (knos record serve), port 8402",
            "relay": "the relay worker (knos relay --serve), paying fees from the buyer's own key",
            "site": "the static site with the approver (#approve), port 8080"}
    for role in c.roles():
        lines.append(f"  {role:<7} {what[role]}")
    lines.append("Key files it reads (by path; nothing secret is in the config):")
    for role, name, path in needs(c) or [("-", "-", "none")]:
        lines.append(f"  {role:<7} keys.{name:<13} {path}")
    for m in c.missing:
        lines.append(f"  {'MISSING' if files else 'not on this machine'}: {m}")
    lines.append("Knos hosts none of this. No single sign-on: put the ports behind your identity proxy (docs/SELFHOST.md).")
    return lines


def plan_lines(c: Checked) -> list[str]:
    names = [s["service"] for s in services(c)]
    lines = ["Services (deploy/compose.yaml):"]
    for s in services(c):
        port = f"127.0.0.1:{s['port']}" if s["port"] else "no port"
        lines.append(f"  {s['service']:<7} {port:<16} {' '.join(s['command'])}")
    lines.append("Start them: KNOS_COMMIT=$(git rev-parse HEAD) docker compose -f deploy/compose.yaml up -d --build " + " ".join(names))
    return lines


def environment(c: Checked, role: str, base: Path | None = None, state: Path = STATE) -> dict[str, str]:
    """The variables a role reads, with each key file's content read now. Refused when a file is missing."""
    chain = c.config["chain"]
    env = {"KNOS_CLUSTER": chain.get("cluster", "devnet"), "KNOS_RPC": chain["rpc"], "KNOS_HOME": str(state / "home")}
    if chain.get("programs") and role != "site":      # the site carries the ids it was built with
        ids = state / "program_ids.json"
        ids.parent.mkdir(parents=True, exist_ok=True)
        ids.write_text(json.dumps(chain["programs"], indent=1) + "\n", encoding="utf-8")
        env["KNOS_PROGRAM_IDS"] = str(ids)
    keys = c.config.get("keys", {})

    def read(name: str, one: str) -> str:
        try:
            return _file(one, base).read_text(encoding="utf-8").strip()
        except OSError as why:
            raise SystemExit(f"keys.{name}: {one} cannot be read ({why.strerror}). Mount the file there, read-only.") from None

    if role == "relay":
        r = c.config["relay"]
        first = read("relay", keys["relay"])
        more = [read("relay_more", p) for p in keys.get("relay_more", [])]
        env["KNOS_RELAY_KEY"] = first
        if more:
            env["KNOS_RELAY_KEYS"] = json.dumps([_as_json(k) for k in [first, *more]])
        env["GH_TOKEN"] = read("github_token", keys["github_token"])
        env["KNOS_RELAY_REPOS"] = ",".join(r["repos"])
        env["KNOS_RELAY_WORKERS"] = str(r.get("workers", 4))
    return env


def _as_json(key: str) -> Any:
    return json.loads(key) if key.startswith("[") else key


def argv_of(c: Checked, role: str, base: Path | None = None, state: Path = STATE, site: Path = SITE) -> list[str]:
    """The arguments the role's own entry takes."""
    if role == "record":
        r, keys = c.config["record"], c.config.get("keys", {})
        args = [str(_file(r["offer"], base)), "--host", "0.0.0.0", "--port", str(PORTS["record"]), "--memory", str(state / "record-memory"),
                "--records", str(_file(r.get("records", str(state / "records")), base))]
        for k in ("history", "suppliers"):
            if r.get(k):
                args += [f"--{k}", str(_file(r[k], base))]
        for k in ("ttl", "tenant", "rate", "burst"):
            if r.get(k):
                args += [f"--{k}", str(r[k])]
        if keys.get("record"):
            args += ["--key", str(_file(keys["record"], base))]
        return args
    if role == "relay":
        r = c.config["relay"]
        return ["relay", "--serve", str(r.get("serve", 3600)), "--every", str(r.get("every", 3))]
    return [str(site), str(PORTS["site"])]


def serve_site(folder: Path, port: int, host: str = "0.0.0.0"):
    """The built site, as files: no directory listing, nothing sniffed, no referrer sent on."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Handler(SimpleHTTPRequestHandler):
        def list_directory(self, path):     # type: ignore[override]
            self.send_error(404, "Not found")
            return None

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

    return ThreadingHTTPServer((host, port), functools.partial(Handler, directory=str(folder)))


def _load(path: Path) -> Checked:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as why:
        raise SystemExit(f"{path} cannot be read ({why.strerror}).") from None
    return check(text, path.parent)


def run(role: str, config: Path) -> int:
    """What a container runs: refuse a bad config before anything starts, then hand over to the role."""
    c = _load(config)
    if not c.ok(files=True):
        print("\n".join(describe(c, files=True)), file=sys.stderr)
        return 2
    if role not in c.roles():
        print(f"{role} is not enabled in {config}: this container has nothing to do.", file=sys.stderr)
        return 2
    os.environ.update(environment(c, role, config.parent))
    args = argv_of(c, role, config.parent)
    if role == "record":
        from . import record_api
        return record_api.main(args)
    if role == "relay":
        from . import flow
        return flow.main(args)
    httpd = serve_site(Path(args[0]), int(args[1]))
    print(f"Serving the site from {args[0]} on port {args[1]} (the approver is #approve). Knos hosts none of this.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m knos.selfhost", description="Knos in the buyer's own cloud (docs/SELFHOST.md).")
    sub = ap.add_subparsers(dest="what", required=True)
    s = sub.add_parser("check", help="validate the config; print what will run and which key files it needs")
    s.add_argument("config", type=Path)
    s.add_argument("--files", action="store_true", help="also require every named file to exist here")
    s = sub.add_parser("plan", help="the compose services the config starts")
    s.add_argument("config", type=Path, nargs="?", default=None)
    s = sub.add_parser("run", help="run one role (what each container runs)")
    s.add_argument("role", choices=ROLES)
    s.add_argument("--config", type=Path, default=CONFIG)
    a = ap.parse_args(argv)
    if a.what == "run":
        return run(a.role, a.config)
    if a.what == "plan" and a.config is None:
        c = Checked({r: {} for r in ROLES})
    else:
        c = _load(a.config)
    if a.what == "check":
        print("\n".join(describe(c, a.files)))
        return 0 if c.ok(a.files) else 1
    if c.errors:
        print("\n".join(describe(c)))
        return 1
    print("\n".join(plan_lines(c)))
    return 0


def register(app: Any, help_lines: list | None = None) -> None:
    """`knos selfhost check | plan`. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("selfhost", "For money", "Run the record API, relay and approver in your own cloud."))
    group = typer.Typer(help="Knos in the buyer's own cloud: one image, three roles, one config file (docs/SELFHOST.md).", no_args_is_help=True)
    app.add_typer(group, name="selfhost", rich_help_panel="For money")

    @group.command("check")
    def check_(config: Path = typer.Argument(..., metavar="CONFIG", help="the knos.toml"),
               files: bool = typer.Option(False, "--files", help="also require every named file to exist here")) -> None:
        """Validate the config; print what will run and which key files it needs."""
        rc = main(["check", str(config)] + (["--files"] if files else []))
        if rc:
            raise typer.Exit(rc)

    @group.command("plan")
    def plan_(config: Path = typer.Argument(None, metavar="[CONFIG]", help="the knos.toml (default: every role)")) -> None:
        """The compose services the config starts, and the command that starts them."""
        rc = main(["plan"] + ([str(config)] if config else []))
        if rc:
            raise typer.Exit(rc)


if __name__ == "__main__":
    raise SystemExit(main())
