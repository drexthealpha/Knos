""".knos/gate.yml: the maintainer's config of Knos Gate, its schema and its loader.

    version: 1
    hidden_tests:                      # the sealed suite the pull request's author cannot read
      source: secret                   # secret (a repository secret holding the bundle) or repo (a private repository)
      secret: KNOS_GATE_HIDDEN         # source: secret - the secret's name (`knos gate seal DIR` prints its value)
      repo: owner/private-tests        # source: repo - the private repository, read with the token in token_secret
      ref: <40-hex commit>             # source: repo - pinned commit
      token_secret: KNOS_GATE_HIDDEN_TOKEN
      sha256: <64-hex>                 # the seal: sha256 of the bundle. A bundle with another hash is refused.
      into: tests/hidden               # where the bundle is placed in the pull request's tree
      command: python -m pytest -q tests/hidden
      timeout: 600
    public_tests:                      # optional: the repository's own tests, run the same way
      command: python -m pytest -q tests
    scope:
      allow: ["src/**", "*.py"]        # empty: anything not denied
      deny: [".github/**", ".knos/**"]
    protect: ["data/**"]               # data and fixtures a pull request may not change
    core: []                           # paths only a maintainer changes (REFEREE's core_path rule)
    setup: python -m pip install pytest -r requirements.txt
                                       # run from the BASE tree, with network, before any pull request code is
                                       # there: installs what the tests need into the test environment
    on_fail: comment                   # comment | label | close
    label: knos-gate-failed
    pass_label: ""                     # e.g. knos-verified: an opt-in bypass signal for other pull request tools
    outside_only: true                 # judge only pull requests from outside collaborators
    receipt: true
    bounties:
      enabled: false
      cluster: devnet
      mint: <devnet USDC mint>

The file is read from the BASE commit, never from the pull request (a pull request that edits it is refused by the
cheat library as `sealed_tests_changed`). PyYAML reads it when installed; otherwise a strict reader of the subset
above (block mappings, block and flow lists, scalars, comments) does, so the runtime needs no extra package.
`load` returns the config with every default filled in, or raises ConfigError naming every problem."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PATH = ".knos/gate.yml"
ON_FAIL = ("comment", "label", "close")
SOURCES = ("secret", "repo")
_HEX40, _HEX64 = re.compile(r"^[0-9a-f]{40}$"), re.compile(r"^[0-9a-f]{64}$")
_REPO = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
_SECRET = re.compile(r"^[A-Z_][A-Z0-9_]{0,99}$")
_LABEL = re.compile(r"^[^\x00-\x1f,]{0,50}$")

SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://raw.githubusercontent.com/drexthealpha/Knos/main/src/knos/gate/gate.schema.json",
    "title": "Knos Gate config (.knos/gate.yml)",
    "type": "object",
    "additionalProperties": False,
    "required": ["version"],
    "properties": {
        "version": {"const": 1},
        "hidden_tests": {
            "type": "object", "additionalProperties": False, "required": ["sha256", "command"],
            "properties": {
                "source": {"enum": list(SOURCES)},
                "secret": {"type": "string", "pattern": _SECRET.pattern},
                "repo": {"type": "string", "pattern": _REPO.pattern},
                "ref": {"type": "string", "pattern": _HEX40.pattern},
                "token_secret": {"type": "string", "pattern": _SECRET.pattern},
                "sha256": {"type": "string", "pattern": _HEX64.pattern},
                "into": {"type": "string"},
                "command": {"type": "string", "minLength": 1},
                "timeout": {"type": "integer", "minimum": 10, "maximum": 3600},
            },
        },
        "public_tests": {
            "type": "object", "additionalProperties": False, "required": ["command"],
            "properties": {"command": {"type": "string", "minLength": 1},
                           "timeout": {"type": "integer", "minimum": 10, "maximum": 3600}},
        },
        "scope": {
            "type": "object", "additionalProperties": False,
            "properties": {"allow": {"type": "array", "items": {"type": "string"}},
                           "deny": {"type": "array", "items": {"type": "string"}}},
        },
        "protect": {"type": "array", "items": {"type": "string"}},
        "core": {"type": "array", "items": {"type": "string"}},
        "setup": {"type": "string"},
        "on_fail": {"enum": list(ON_FAIL)},
        "label": {"type": "string"},
        "pass_label": {"type": "string"},
        "outside_only": {"type": "boolean"},
        "receipt": {"type": "boolean"},
        "bounties": {
            "type": "object", "additionalProperties": False,
            "properties": {"enabled": {"type": "boolean"}, "cluster": {"enum": ["devnet", "localnet"]},
                           "mint": {"type": "string"}},
        },
    },
}

DEFAULT_DENY = (".github/**", ".knos/**")


class ConfigError(ValueError):
    """The config is not one Knos Gate can run: every problem, one per line."""


def defaults() -> dict:
    return {"version": 1, "hidden_tests": None, "public_tests": None,
            "scope": {"allow": [], "deny": list(DEFAULT_DENY)}, "protect": [], "core": [],
            "on_fail": "comment", "label": "knos-gate-failed", "pass_label": "", "outside_only": True, "receipt": True, "setup": "",
            "bounties": {"enabled": False, "cluster": "devnet", "mint": ""}}


# ---- a strict reader of the YAML subset gate.yml uses ----------------------------------------------------------------

def _scalar(text: str) -> Any:
    t = text.strip()
    if t == "" or t in ("~", "null"):
        return None
    if t[0] in "\"'":
        q = t[0]
        if len(t) < 2 or t[-1] != q:
            raise ConfigError(f"unclosed quote: {t}")
        body = t[1:-1]
        return body.replace("''", "'") if q == "'" else json.loads(t) if "\\" in body else body
    if t in ("true", "True", "yes"):
        return True
    if t in ("false", "False", "no"):
        return False
    if re.fullmatch(r"-?[0-9]+", t):
        return int(t)
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [] if not inner else [_scalar(p) for p in _split_flow(inner)]
    if t.startswith("{") or t.startswith("&") or t.startswith("*") or t.startswith("|") or t.startswith(">"):
        raise ConfigError(f"not supported without PyYAML: {t}")
    return t


def _split_flow(inner: str) -> list[str]:
    out, cur, q = [], "", ""
    for ch in inner:
        if q:
            cur += ch
            if ch == q:
                q = ""
        elif ch in "\"'":
            q, cur = ch, cur + ch
        elif ch == ",":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _strip_comment(line: str) -> str:
    q = ""
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = ""
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def mini_yaml(text: str) -> Any:
    """Block mappings, block lists of scalars, flow lists, scalars and comments. Anything else raises ConfigError."""
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ConfigError(f"line {n}: a tab in the indentation")
        s = _strip_comment(raw)
        if s.strip() and s.strip() != "---":
            lines.append((n, len(s) - len(s.lstrip()), s.strip()))

    def block(i: int, indent: int) -> tuple[Any, int]:
        if i >= len(lines):
            return None, i
        if lines[i][2].startswith("- ") or lines[i][2] == "-":
            out_l: list = []
            while i < len(lines) and lines[i][1] == indent and (lines[i][2].startswith("- ") or lines[i][2] == "-"):
                out_l.append(_scalar(lines[i][2][1:]))
                i += 1
            return out_l, i
        out: dict = {}
        while i < len(lines) and lines[i][1] == indent:
            n, _ind, s = lines[i]
            m = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*:(?:\s+(.*))?", s) or re.fullmatch(r"([A-Za-z0-9_.-]+):()", s)
            if not m:
                raise ConfigError(f"line {n}: expected `key: value`")
            key, rest = m.group(1), (m.group(2) or "").strip()
            if key in out:
                raise ConfigError(f"line {n}: `{key}` twice")
            i += 1
            if rest:
                out[key] = _scalar(rest)
            elif i < len(lines) and lines[i][1] > indent:
                out[key], i = block(i, lines[i][1])
            elif i < len(lines) and lines[i][1] == indent and lines[i][2].startswith("- "):
                out[key], i = block(i, indent)
            else:
                out[key] = None
        return out, i

    if not lines:
        return None
    got, end = block(0, lines[0][1])
    if end != len(lines):
        raise ConfigError(f"line {lines[end][0]}: unexpected indentation")
    return got


def parse(text: str) -> Any:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return mini_yaml(text)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as why:
        raise ConfigError(f"not YAML: {why}") from None


# ---- validation ------------------------------------------------------------------------------------------------------

def _strings(v, where: str, errs: list[str]) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        errs.append(f"{where}: a list of path globs")
        return []
    bad = [x for x in v if x.startswith("/") or ".." in x.split("/")]
    if bad:
        errs.append(f"{where}: a glob is relative to the repository root, with no `..`: {bad[0]}")
    return list(v)


def validate(raw: Any) -> dict:
    """The config with its defaults, or ConfigError listing every problem."""
    errs: list[str] = []
    if not isinstance(raw, dict):
        raise ConfigError(f"{PATH} is not a mapping")
    known = set(SCHEMA["properties"])
    for k in raw:
        if k not in known:
            errs.append(f"unknown key `{k}` (known: {', '.join(sorted(known))})")
    if raw.get("version") != 1:
        errs.append("version: must be 1")
    cfg = defaults()
    h = raw.get("hidden_tests")
    if h is not None:
        if not isinstance(h, dict):
            errs.append("hidden_tests: a mapping")
        else:
            hk = set(SCHEMA["properties"]["hidden_tests"]["properties"])
            errs += [f"hidden_tests: unknown key `{k}`" for k in h if k not in hk]
            src = h.get("source", "secret")
            if src not in SOURCES:
                errs.append("hidden_tests.source: secret or repo")
            if not _HEX64.match(str(h.get("sha256") or "")):
                errs.append("hidden_tests.sha256: the seal, 64 lowercase hex (`knos gate seal DIR` prints it)")
            if not isinstance(h.get("command"), str) or not h["command"].strip():
                errs.append("hidden_tests.command: how the hidden tests run, e.g. `python -m pytest -q tests/hidden`")
            secret = h.get("secret", "KNOS_GATE_HIDDEN")
            if src == "secret" and not _SECRET.match(str(secret)):
                errs.append("hidden_tests.secret: a secret name (A-Z, 0-9, _)")
            if src == "repo":
                if not _REPO.match(str(h.get("repo") or "")):
                    errs.append("hidden_tests.repo: owner/name of the private repository")
                if not _HEX40.match(str(h.get("ref") or "")):
                    errs.append("hidden_tests.ref: the pinned commit (40 hex): a branch could change under the seal")
            into = str(h.get("into", "tests/hidden")).strip("/")
            if not into or into.startswith(".") or ".." in into.split("/"):
                errs.append("hidden_tests.into: a relative folder inside the repository")
            timeout = h.get("timeout", 600)
            if not isinstance(timeout, int) or isinstance(timeout, bool) or not 10 <= timeout <= 3600:
                errs.append("hidden_tests.timeout: seconds, 10..3600")
            cfg["hidden_tests"] = {"source": src, "secret": secret, "repo": h.get("repo", ""), "ref": h.get("ref", ""),
                                   "token_secret": h.get("token_secret", "KNOS_GATE_HIDDEN_TOKEN"),
                                   "sha256": h.get("sha256"), "into": into, "command": h.get("command"), "timeout": timeout}
    p = raw.get("public_tests")
    if p is not None:
        if not isinstance(p, dict) or not isinstance(p.get("command"), str) or not p["command"].strip():
            errs.append("public_tests: a mapping with `command`")
        else:
            cfg["public_tests"] = {"command": p["command"], "timeout": p.get("timeout", 600)}
    s = raw.get("scope") or {}
    if not isinstance(s, dict):
        errs.append("scope: a mapping with allow and deny")
    else:
        errs += [f"scope: unknown key `{k}`" for k in s if k not in ("allow", "deny")]
        cfg["scope"]["allow"] = _strings(s.get("allow"), "scope.allow", errs)
        deny = _strings(s.get("deny"), "scope.deny", errs)
        cfg["scope"]["deny"] = list(dict.fromkeys([*DEFAULT_DENY, *deny]))
    cfg["protect"] = _strings(raw.get("protect"), "protect", errs)
    cfg["core"] = _strings(raw.get("core"), "core", errs)
    if "setup" in raw:
        if not isinstance(raw["setup"], str) or not raw["setup"].strip():
            errs.append("setup: one command line, e.g. `python -m pip install pytest -r requirements.txt`")
        else:
            cfg["setup"] = raw["setup"]
    on_fail = raw.get("on_fail", "comment")
    if on_fail not in ON_FAIL:
        errs.append(f"on_fail: one of {', '.join(ON_FAIL)}")
    cfg["on_fail"] = on_fail
    for k in ("label", "pass_label"):
        if k in raw:
            if not isinstance(raw[k], str) or not _LABEL.match(raw[k]):
                errs.append(f"{k}: a label name (no comma, at most 50 characters)")
            else:
                cfg[k] = raw[k]
    for k in ("outside_only", "receipt"):
        if k in raw:
            if not isinstance(raw[k], bool):
                errs.append(f"{k}: true or false")
            else:
                cfg[k] = raw[k]
    b = raw.get("bounties")
    if b is not None:
        if not isinstance(b, dict):
            errs.append("bounties: a mapping")
        else:
            errs += [f"bounties: unknown key `{k}`" for k in b if k not in ("enabled", "cluster", "mint")]
            if b.get("cluster", "devnet") not in ("devnet", "localnet"):
                errs.append("bounties.cluster: devnet or localnet (no mainnet in this version)")
            if not isinstance(b.get("enabled", False), bool):
                errs.append("bounties.enabled: true or false")
            cfg["bounties"] = {"enabled": bool(b.get("enabled", False)), "cluster": b.get("cluster", "devnet"),
                               "mint": str(b.get("mint") or "")}
    if cfg["hidden_tests"] is None and cfg["public_tests"] is None:
        errs.append("neither hidden_tests nor public_tests: Gate would run no test at all")
    if errs:
        raise ConfigError("\n".join(errs))
    return cfg


def loads(text: str) -> dict:
    return validate(parse(text))


def load(root: Path | str) -> dict:
    """The config at <root>/.knos/gate.yml (root: the BASE commit's tree)."""
    p = Path(root) / PATH
    if not p.is_file():
        raise ConfigError(f"no {PATH} on the base commit: Knos Gate is not set up in this repository")
    return loads(p.read_text(encoding="utf-8"))
