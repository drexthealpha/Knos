"""The cheat checks Gate runs on a pull request's diff, before and apart from any test. No pull request code runs here.

REFEREE owns the cheat library (`knos.cheats`, docs/reference/REFEREE.md). When it is installed, `scan` calls
`cheats.scan_diff(diff, base_dir=, scope=, core=)` and keeps every finding. Gate then adds the rules only its own
config can say (what `.knos/gate.yml` denies and protects, the folder the hidden tests are placed in), and when
`knos.cheats` is not installed it runs the small local set below, which gives findings of the same shape:

    rule id                      category              severity  what
    gate.workflow_edited         workflow_edited       refuse    a change under .github/ (GitHub runs the PR's copy)
    gate.sealed_config_changed   sealed_tests_changed  refuse    a change under .knos/ (the Gate config and its seal)
    gate.hidden_dir_written      sealed_tests_changed  refuse    a file where the hidden tests are placed
    gate.test_edited             test_edited           refuse    an existing test edited or deleted (knos.judge's rule)
    gate.runner_tampering        runner_tampering      refuse    conftest.py, pytest.ini, tox.ini, setup.cfg, sitecustomize.py,
                                                                 usercustomize.py, noxfile.py, *.pth, pyproject.toml's [tool.pytest]
    gate.out_of_scope            out_of_scope          refuse    a path scope.deny matches, or scope.allow does not
    gate.data_tampering          data_tampering        refuse    a path `protect` matches
    gate.core_path               core_path             refuse    a path `core` matches
    gate.no_change               no_change             refuse    the diff changes nothing
    gate.unreadable_path         out_of_scope          refuse    a `diff --git` line whose file names cannot be read

A finding is a dict {rule, category, path, detail, severity}; `refused(findings)` is true when one has severity
"refuse". `library()` says which library ran, and the receipt carries it."""
from __future__ import annotations

import re
from functools import lru_cache

RULES = {
    "gate.workflow_edited": ("workflow_edited", "changes a GitHub workflow or action, which GitHub would run as the pull request wrote it"),
    "gate.sealed_config_changed": ("sealed_tests_changed", "changes .knos/, where the Gate config and its seal live"),
    "gate.hidden_dir_written": ("sealed_tests_changed", "writes into the folder the hidden tests are placed in"),
    "gate.test_edited": ("test_edited", "edits or deletes an existing test"),
    "gate.runner_tampering": ("runner_tampering", "changes how tests are found or run"),
    "gate.out_of_scope": ("out_of_scope", "changes a file outside the scope the maintainer set"),
    "gate.data_tampering": ("data_tampering", "changes data or fixtures the maintainer protected"),
    "gate.core_path": ("core_path", "changes a path only a maintainer changes"),
    "gate.no_change": ("no_change", "changes nothing"),
    "gate.unreadable_path": ("out_of_scope", "names a file Gate cannot read from the diff, so no rule could check it"),
}
_RUNNER = re.compile(r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|sitecustomize\.py|usercustomize\.py|noxfile\.py)$|\.pth$")


@lru_cache(maxsize=256)
def _glob_re(glob: str) -> re.Pattern:
    out, i = "", 0
    g = glob.strip().lstrip("./") if glob.startswith("./") else glob.strip()
    while i < len(g):
        if g.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif g.startswith("**", i):
            out, i = out + ".*", i + 2
        elif g[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif g[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(g[i]), i + 1
    if g.endswith("/"):
        out += ".*"
    return re.compile(f"^{out}$")


def matches(path: str, glob: str) -> bool:
    return bool(_glob_re(glob).match(path))


_Q = r'"((?:[^"\\]|\\.)*)"'
_GIT_LINE = [re.compile(p) for p in (rf"^{_Q} {_Q}$", rf"^{_Q} (b/.*)$", rf"^(a/.*) {_Q}$", r"^(a/.*) (b/.*)$")]
_ESC = {"n": 10, "t": 9, '"': 34, "\\": 92, "a": 7, "b": 8, "f": 12, "r": 13, "v": 11}


def _unquote(s: str) -> str:
    """git's C-style quoting of a path (core.quotePath): \\303\\251 is the UTF-8 of an accented letter."""
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in "01234567" and i + 3 < len(s) + 1 and all(ch in "01234567" for ch in s[i + 1:i + 4]) and len(s[i + 1:i + 4]) == 3:
                out.append(int(s[i + 1:i + 4], 8) & 0xFF)
                i += 4
                continue
            out.append(_ESC.get(nxt, ord(nxt) if ord(nxt) < 128 else 63))
            i += 2
            continue
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", "replace")


def _path(token: str) -> str:
    return _unquote(token[1:-1]) if len(token) >= 2 and token[0] == token[-1] == '"' else token


def _git_paths(rest: str) -> tuple[str, str] | None:
    """(old, new) of what follows `diff --git `, quoted or not; None when it cannot be read."""
    for i, rx in enumerate(_GIT_LINE):
        m = rx.match(rest)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        a = _unquote(a) if i in (0, 1) else a
        b = _unquote(b) if i in (0, 2) else b
        if a.startswith("a/") and b.startswith("b/"):
            return a[2:], b[2:]
    return None


def changed_files(diff: str) -> list[dict]:
    """[{path, status, old}] of a unified git diff: status added, modified, removed or renamed (a rename names both).
    Names git quoted (non-ASCII, tabs, quotes) are unquoted; a `diff --git` line that cannot be read is kept with
    status "unreadable", so the caller refuses it instead of skipping it."""
    out: list[dict] = []
    cur: dict | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            got = _git_paths(line[len("diff --git "):])
            if got:
                cur = {"path": got[1], "old": got[0], "status": "modified", "added": [], "removed": []}
            else:
                cur = {"path": line[len("diff --git "):][:120], "old": "", "status": "unreadable", "added": [], "removed": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("new file mode"):
            cur["status"] = "added"
        elif line.startswith("deleted file mode"):
            cur["status"] = "removed"
        elif line.startswith("rename from ") and cur["status"] != "unreadable":
            cur["status"], cur["old"] = "renamed", _path(line[len("rename from "):])
        elif line.startswith("rename to ") and cur["status"] != "unreadable":
            cur["path"] = _path(line[len("rename to "):])
        elif line.startswith("+") and not line.startswith("+++"):
            cur["added"].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            cur["removed"].append(line[1:])
    return out


def _finding(rule: str, path: str, detail: str = "", severity: str = "refuse") -> dict:
    cat, said = RULES[rule]
    return {"rule": rule, "category": cat, "path": path, "detail": detail or said, "severity": severity}


def local_scan(diff: str, cfg: dict) -> list[dict]:
    """The local rule set (see the module's table)."""
    from .. import judge
    files = changed_files(diff)
    if not files:
        return [_finding("gate.no_change", "")]
    out = []
    for f in files:
        if f["status"] == "unreadable":
            out.append(_finding("gate.unreadable_path", f["path"]))
            continue
        names = [f["path"]] + ([f["old"]] if f["status"] == "renamed" and f["old"] != f["path"] else [])
        for path in names:
            out += _config_rules(path, cfg)
            if path.startswith(".github/") or path.startswith(".knos/"):
                continue
            if _RUNNER.search(path):
                out.append(_finding("gate.runner_tampering", path))
                continue
            if path == "pyproject.toml" and any("[tool.pytest" in ln or "addopts" in ln for ln in f["added"] + f["removed"]):
                out.append(_finding("gate.runner_tampering", path, "changes pyproject.toml's pytest settings"))
                continue
            status = "removed" if path == f["old"] and f["status"] == "renamed" else ("modified" if f["status"] == "renamed" else f["status"])
            try:
                kind = judge.classify_path(path, {}, status)
            except ValueError:
                kind = "allowed"
            if kind.startswith("refused:protected_test"):
                out.append(_finding("gate.test_edited", path))
    return out


def _config_rules(path: str, cfg: dict) -> list[dict]:
    """What only .knos/gate.yml can say about one path."""
    out = []
    if path.startswith(".github/"):
        out.append(_finding("gate.workflow_edited", path))
    elif path.startswith(".knos/"):
        out.append(_finding("gate.sealed_config_changed", path))
    hidden = (cfg.get("hidden_tests") or {}).get("into")
    if hidden and (path == hidden or path.startswith(hidden.rstrip("/") + "/")):
        out.append(_finding("gate.hidden_dir_written", path))
    prot = next((g for g in cfg.get("protect", []) if matches(path, g)), None)
    if prot:
        out.append(_finding("gate.data_tampering", path, f"changes {path}, which `protect` covers ({prot})"))
    core = next((g for g in cfg.get("core", []) if matches(path, g)), None)
    if core:
        out.append(_finding("gate.core_path", path, f"changes {path}, a core path ({core})"))
    scope = cfg.get("scope") or {}
    denied = next((g for g in scope.get("deny", []) if matches(path, g)), None)
    if denied and not path.startswith((".github/", ".knos/")):
        out.append(_finding("gate.out_of_scope", path, f"changes {path}, which scope.deny excludes ({denied})"))
    elif scope.get("allow") and not any(matches(path, g) for g in scope["allow"]) and not path.startswith((".github/", ".knos/")):
        out.append(_finding("gate.out_of_scope", path, f"changes {path}, outside scope.allow"))
    return out


def _referee():
    try:
        from .. import cheats  # type: ignore[attr-defined]
    except ImportError:
        return None
    return cheats if hasattr(cheats, "scan_diff") else None


def library() -> str:
    return "knos.cheats" if _referee() is not None else "knos.gate.cheatlib (local rules)"


def _as_dict(f) -> dict:
    if isinstance(f, dict):
        d = dict(f)
    else:
        d = {k: getattr(f, k, "") for k in ("rule", "category", "path", "detail", "severity")}
    d.setdefault("severity", "refuse")
    return {k: str(d.get(k) or "") for k in ("rule", "category", "path", "detail", "severity")}


def scan(diff: str, cfg: dict, base_dir=None, *, lib=None) -> list[dict]:
    """Every finding on the diff: REFEREE's library when installed (or `lib`, a module with scan_diff), then Gate's
    own rules, always (both names of a rename, quoted names, the config's deny/protect/core and the hidden folder),
    so a path one parser misses the other still checks. One finding per (category, path), the library's first."""
    lib = lib if lib is not None else _referee()
    found = []
    if lib is not None:
        scope = (cfg.get("scope") or {}).get("allow") or None
        found = [_as_dict(f) for f in lib.scan_diff(diff, base_dir=base_dir, scope=scope, core=cfg.get("core") or None)]
    found += local_scan(diff, cfg)
    seen, out = set(), []
    for f in found:
        key = (f["category"], f["path"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def refused(findings: list[dict]) -> bool:
    return any(f.get("severity", "refuse") == "refuse" for f in findings)


def rules_run(lib=None) -> list[str]:
    lib = lib if lib is not None else _referee()
    if lib is not None and hasattr(lib, "RULES"):
        return sorted({*map(str, lib.RULES), *(r for r in RULES if r != "gate.test_edited" and r != "gate.runner_tampering")})
    return sorted(RULES)
