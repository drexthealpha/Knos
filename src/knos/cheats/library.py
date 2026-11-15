"""The cheat library: every way of making a check pass without doing the work that Knos has caught, as a named rule.

A rule reads a change (two trees, or a unified diff) and never runs the change's code. Each rule has an id, a category
(the word Knos Record keeps as `cheat`), a severity ("refuse": the work is refused; "flag": said, not refused) and at
least one known-bad case it must catch (src/knos/cheats/tamper63.py holds the first 63; tests/test_referee_cheats.py
runs every case). The judge's own path rule (knos.judge.classify: protected tests, the terms, the workflows) is the
first rule here, word for word; the library adds what that rule allows and a cheat still uses: code that knows it is
under test, runner options, forged reports, answers copied from the visible tests, and the outcome cheats (window,
salt, spec hash, control share, measurement code, data).

A new cheat type caught anywhere becomes a rule with `add_rule` and a case in the same change; nothing is ever removed
from the library, and `red_team` says how many of the known cases a scanner catches (the regression gate for any
change to the referee).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

CATEGORIES = ("test_edited", "out_of_scope", "runner_tampering", "runner_forgery", "workflow_edited", "spec_tampering",
              "hardcoded_answers", "no_change", "core_path", "assertion_removed", "data_tampering", "salt_changed",
              "window_changed", "spec_hash_changed", "control_drift", "measurement_code_drift", "judge_drift",
              "sealed_tests_changed", "rerun_mismatch", "rule_error")
SEVERITIES = ("refuse", "flag")


@dataclass(frozen=True)
class Finding:
    """One rule that fired on one path."""
    rule: str
    category: str
    path: str = ""
    detail: str = ""
    severity: str = "refuse"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Rule:
    """A named cheat rule. `check(change) -> list[Finding]` for the change rules; outcome rules are in outcome.py and
    have check=None here (they read funded/now specs, not a change)."""
    id: str
    category: str
    title: str
    severity: str = "refuse"
    check: Callable | None = None
    kind: str = "change"            # "change" (a PR's diff) or "outcome" (a measurement's committed inputs)

    def __post_init__(self):
        if self.category not in CATEGORIES:
            raise ValueError(f"rule {self.id}: category {self.category!r} is not one of {', '.join(CATEGORIES)}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"rule {self.id}: severity {self.severity!r}")
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", self.id):
            raise ValueError(f"rule id {self.id!r}: lower case words joined by _")


# ---- a change, whichever way it arrives ----------------------------------------------------------------------------------

@dataclass
class FileChange:
    path: str
    status: str                     # added | modified | removed
    before: str | None = None       # whole text when known
    after: str | None = None
    added: list[str] = field(default_factory=list)      # lines the change added
    removed: list[str] = field(default_factory=list)    # lines the change removed


@dataclass
class Change:
    files: list[FileChange]
    runner: str = "python"          # the repository's language (its test runner)
    test_dirs: tuple = ("tests",)
    terms: dict = field(default_factory=dict)
    scope: tuple = ()               # allowed path globs; () = no scope given
    core: tuple = ()                # paths no contributor may touch at all (SELF's trusted core)
    claim: bool = True              # the change claims to do the work (a bounty, a sealed task): a no-op is a cheat
    visible_literals: frozenset = frozenset()   # groups of string literals, one per line of the tests the author could read
    errors: list = field(default_factory=list)  # what could not be read (an unparseable diff header): each refuses
    # group -> the Reach of the test files that hold it (what those tests import). A group with no entry here is
    # taken to exercise every file (the strict reading, for a Change built by hand).
    literal_tests: dict = field(default_factory=dict)

    def paths(self) -> list[str]:
        return [f.path for f in self.files]


_TEXT_MAX = 2_000_000


def _read(p: Path) -> str | None:
    try:
        if p.stat().st_size > _TEXT_MAX:
            return None
        raw = p.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", "replace")


def _line_diff(before: str | None, after: str | None) -> tuple[list[str], list[str]]:
    import difflib
    a = (before or "").splitlines()
    b = (after or "").splitlines()
    added, removed = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += a[i1:i2]
        if tag in ("replace", "insert"):
            added += b[j1:j2]
    return added, removed


def _proof_toml(base: Path | None) -> dict:
    if base is None:
        return {}
    from ..judge import proof_config
    p = Path(base) / ".knos" / "proof.toml"
    return proof_config(p.read_text(encoding="utf-8")) if p.is_file() else {}


def guess_runner(base: Path | None, paths: Iterable[str] = (), terms: dict | None = None) -> str:
    """The repository's language, for the test-file rules: proof.toml's runner when it names a language, else the
    BASE tree's files. `paths` (the change's own) is accepted and never read: a pull request that adds one .js or .rb
    file must not change which directories count as tests. With no base, python (whose test directories are
    tests/ and test/)."""
    terms = terms or {}
    named = terms.get("runner") or (terms.get("judge") or {}).get("runner")
    if named in ("python", "node", "go", "rust", "ruby"):
        return named
    names: set = set()
    if base is not None:
        names |= {p.name for p in Path(base).iterdir()} if Path(base).is_dir() else set()
    if "package.json" in names or any(n.endswith((".js", ".ts", ".mjs", ".cjs")) for n in names):
        return "node"
    if "Gemfile" in names or any(n.endswith(".gemspec") or n.endswith(".rb") for n in names):
        return "ruby"
    if "go.mod" in names:
        return "go"
    if "Cargo.toml" in names:
        return "rust"
    return "python"


def _string_literals(text: str) -> set[str]:
    """Every quoted string of a line, read left to right (so the text BETWEEN two strings is never taken for one),
    kept when 4 to 80 characters long."""
    return {m.group(2) for m in LITERAL.finditer(text) if 4 <= len(m.group(2)) <= 80}


LITERAL = re.compile(r"""(["'])((?:(?!\1)[^\\\n]|\\.)*)\1""")
# a line of a test that states an expectation: only such lines give the pairs an author could copy as answers
EXPECTS = re.compile(r"(\bassert\w*\b|\bexpect\(|\.must_|\.should\b|==|\bequal\w*\(|\bstrictEqual\(|\bt\.(Error|Fatal)|\bassert_eq!)")


def visible_literals(base: Path | None, test_dirs: Iterable[str]) -> frozenset:
    """The string literals of the tests an author could read, one group per line that holds two or more (an input
    and the answer a test expects for it): the base's test directories and the acceptance bundles that are in the
    repository. A sealed bundle kept outside the repository is not visible, and is not read here."""
    return frozenset(visible_literal_tests(base, test_dirs))


# ---- what a test exercises (P-cheatfp): the modules it imports, requires or runs -------------------------------

@dataclass(frozen=True)
class Reach:
    """What one test file (with the runner's helpers) reaches: Python dotted names it imports, its import/require
    lines (lower case, for the other languages), its text. `everything`: no way to tell, so it exercises every file."""
    names: frozenset = frozenset()
    lines: str = ""
    text: str = ""
    everything: bool = False


_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([\w.]+(?:[ \t]+as[ \t]+\w+)?(?:[ \t]*,[ \t]*[\w.]+(?:[ \t]+as[ \t]+\w+)?)*)", re.M)
_PY_FROM = re.compile(r"^[ \t]*from[ \t]+(\.*[\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^\n#]+)", re.M)
_PY_DYNAMIC = re.compile(r"""(?:import_module|__import__)\(\s*['"]([\w.]+)""")
# an import/require line of JavaScript or Ruby (Python's are read by name above)
_IMPORT_LINE = re.compile(r"""^\s*(import\b|export\b.*\bfrom\b|load\s+['"])|\brequire(_relative)?\b\s*\(?\s*['"]|\bimport\s*\(\s*['"]""")
_RUNS_PROGRAM = re.compile(r"\bsubprocess\b|\bPopen\b|\bos\.system\(|child_process|\bexec(File)?Sync\(|\bspawnSync\(|\bOpen3\b|%x\(")
# what a program-running test names: a source file ("calc.py", "bin/x.js") or a module after -m ("-m", "knos")
_PROGRAM_FILE = re.compile(r"^(\./)?[A-Za-z_][\w./-]*\.(py|js|mjs|cjs|ts|rb)$")
_DASH_M = re.compile(r"""['"]-m['"]\s*,\s*['"]([\w.]+)['"]|-m\s+([\w.]+)""")
HELPER_NAME = re.compile(r"(^|/)(conftest\.py|test_helper\.rb|spec_helper\.rb|[^/]*helpers?\.[cm]?[jt]s|setup[^/]*\.[cm]?[jt]s)$")


def reach_of(text: str, path: str = "", strings: bool = True) -> Reach:
    """What a test (or a source file, for the one-hop closure) imports. Data files and Go/Rust tests (which reach
    their package without an import line) exercise everything, as does a file with no import line at all.
    `strings`: a test also reaches the source files its strings name ("calc.py", "web/task.js": a page a browser
    loads, a script it runs) and, when it runs a program, the module after -m. Off for the runner's helpers (their
    set-up commands are not the code under test) and for source files (the closure follows imports only)."""
    if path.endswith((".json", ".go", ".rs")):
        return Reach(text=text, everything=True)
    names: set = set()
    for m in _PY_IMPORT.finditer(text):
        names |= {part.split()[0] for part in m.group(1).split(",") if part.strip()}
    for m in _PY_FROM.finditer(text):
        mod = m.group(1).lstrip(".")
        for item in m.group(2).strip().strip("()").split(","):
            item = item.split()[0] if item.strip() else ""
            if item == "*" or (mod and not item):
                names.add(mod)
            elif item:
                names.add(f"{mod}.{item}" if mod else item)
    names |= set(_PY_DYNAMIC.findall(text))
    lines = [ln for ln in text.splitlines() if _IMPORT_LINE.search(ln)]
    if strings:
        for s in {m.group(2) for ln in text.splitlines() for m in LITERAL.finditer(ln) if len(m.group(2)) <= 80}:
            if _PROGRAM_FILE.match(s):
                lines.append(s)
                names.add(re.sub(r"\.(py|js|mjs|cjs|ts|rb)$", "", s.removeprefix("./")).replace("/", "."))
        for m in _DASH_M.finditer(text) if _RUNS_PROGRAM.search(text) else ():
            names.add(m.group(1) or m.group(2))
    if not names and not lines:
        return Reach(text=text, everything=True)
    return Reach(frozenset(n for n in names if n), "\n".join(lines).lower(), text)


# a field name, not an input or an answer: a subscript key (x["amount"]), a .get("key") / .pop("key"), a dict key
# ({"Content-Type": ...}). Protocol shapes shared by any two modules are made of these (P-cheatfp).
_FIELD_BEFORE = re.compile(r"""(?:[\w\])"']\s*\[|\.(?:get|pop|setdefault)\()\s*$""")
_FIELD_AFTER = re.compile(r"\s*:(?!:)")


def _value_literals(line: str) -> set[str]:
    """The literals of a test line that can be an input or an expected answer (field names left out), 4-80 chars."""
    out = set()
    for m in LITERAL.finditer(line):
        if not 4 <= len(m.group(2)) <= 80:
            continue
        if _FIELD_BEFORE.search(line[:m.start()]) or _FIELD_AFTER.match(line[m.end():]):
            continue
        out.add(m.group(2))
    return out


def _merge(a: Reach, b: Reach) -> Reach:
    return Reach(a.names | b.names, a.lines + "\n" + b.lines, a.text + "\n" + b.text, a.everything or b.everything)


def visible_literal_tests(base: Path | None, test_dirs: Iterable[str]) -> dict:
    """visible_literals, each group mapped to the Reach of the test files that hold it (the runner's helpers,
    conftest.py / test_helper.rb / ..., load code for every test, so their imports count for every test)."""
    if base is None:
        return {}
    base = Path(base)
    roots = [base / d for d in test_dirs] + [base / ".knos" / "acceptance"]
    groups: dict[frozenset, list] = {}
    refs: dict[str, Reach] = {}
    helpers = Reach()
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".go", ".rs", ".json"):
                text = _read(p) or ""
                rel = p.relative_to(base).as_posix()
                refs[rel] = reach_of(text, rel)
                if HELPER_NAME.search(rel):
                    own = reach_of(text, rel, strings=False)
                    helpers = _merge(helpers, Reach(own.names, own.lines)) if not own.everything else helpers
                for line in text.splitlines():
                    if not EXPECTS.search(line):
                        continue
                    group = frozenset(s for s in _value_literals(line)
                                      if any(c.isalnum() for c in s) and not s.startswith(("./", "../", "node:")))
                    if len(group) >= 2:
                        groups.setdefault(group, [])
                        if rel not in groups[group]:
                            groups[group].append(rel)
    tests = [r for r in refs if _TEST_FILE.search(r) or r.startswith(".knos/acceptance/")]

    def resolved(rel: str) -> Reach:
        r = refs[rel]
        if not r.everything or (rel in tests and not rel.endswith(".json")):
            return r                           # a test file with no import line (a black box, Go, Rust): everything
        if rel.endswith(".json"):              # test data: what the tests that read it reach (by name, else its folder's)
            name, folder = rel.rsplit("/", 1)[-1], rel.rsplit("/", 1)[0]
            readers = [refs[t] for t in tests if name in refs[t].text] or [refs[t] for t in tests if t.rsplit("/", 1)[0] == folder]
            out = Reach()
            for x in readers:
                out = _merge(out, x)
            return out
        return Reach()                         # sample code kept under tests/ that no test imports: reaches nothing
    return {g: tuple(_merge(resolved(r), helpers) for r in rels) for g, rels in groups.items()}


_TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test|[^/]*[._-](test|spec)|conftest|blackbox)\.[a-z]+$")


def change_from_trees(base_dir, pr_dir, *, changed=None, scope=(), core=(), terms=None, claim=True) -> Change:
    from ..judge import changed_files
    base, pr = Path(base_dir), Path(pr_dir)
    terms = dict(terms) if terms is not None else _proof_toml(base)
    paths = changed_files(base, pr) if changed is None else sorted(changed)
    files = []
    for rel in paths:
        a, b = base / rel, pr / rel
        status = "added" if not a.is_file() else "removed" if not b.is_file() else "modified"
        before = _read(a) if a.is_file() else None
        after = _read(b) if b.is_file() else None
        added, removed = _line_diff(before, after)
        files.append(FileChange(rel, status, before, after, added, removed))
    runner = guess_runner(base, (), terms)
    test_dirs = tuple(terms.get("test_dirs") or _default_dirs(runner))
    seen = visible_literal_tests(base, test_dirs)
    return Change(files, runner, test_dirs, terms, tuple(scope or ()), tuple(core or ()), claim,
                  frozenset(seen), literal_tests=seen)


def _default_dirs(runner: str) -> tuple:
    from ..judge import TEST_DIRS
    return tuple(TEST_DIRS.get(runner, ("tests", "test")))


_QUOTED = r'"(?:[^"\\]|\\.)*"'
_DIFF_FILE = re.compile(rf"^diff --git ({_QUOTED}|a/.*?) ({_QUOTED}|b/.*)$")
_ESC = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def unquote_path(text: str) -> str:
    """A path as git writes it in a diff: plain, or C-quoted with octal bytes when it holds non-ASCII or special
    characters ("t\\303\\251st.py" is tést.py, unless core.quotePath is off). A trailing tab and timestamp (diff -u
    headers) is cut."""
    text = text.strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        raw, body, i = bytearray(), text[1:-1], 0
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                n = body[i + 1]
                if n in "01234567":
                    j = i + 1
                    while j < len(body) and j < i + 4 and body[j] in "01234567":
                        j += 1
                    raw.append(int(body[i + 1:j], 8) & 0xFF)
                    i = j
                    continue
                raw.append(_ESC.get(n, ord(n)))
                i += 2
                continue
            raw += c.encode("utf-8")
            i += 1
        return raw.decode("utf-8", "replace")
    return text.split("\t", 1)[0]


def _side(text: str, prefix: str) -> str:
    p = unquote_path(text)
    return p[len(prefix):] if p.startswith(prefix) else p


def parse_diff(diff_text: str, errors: list | None = None) -> list[FileChange]:
    """A unified git diff, as `git diff` writes it, into one FileChange per path (renames: the old path removed and
    the new one added). Quoted paths (non-ASCII, spaces, quotes) are read; a `---`/`+++` pair with no `diff --git`
    line before it is a file too. A `diff --git` line that cannot be read is put in `errors` (the caller refuses)."""
    files: list[FileChange] = []
    cur: FileChange | None = None
    old_path = None
    minus = None                          # the path of the last `--- ` header
    left = right = 0                      # lines still to come in the current hunk (old side, new side)
    for line in (diff_text or "").splitlines():
        if left > 0 or right > 0:         # inside a hunk: every line is content, whatever it starts with
            if cur is not None:
                if line.startswith("+"):
                    cur.added.append(line[1:])
                    right -= 1
                elif line.startswith("-"):
                    cur.removed.append(line[1:])
                    left -= 1
                elif line.startswith("\\"):
                    pass                  # "\ No newline at end of file"
                else:
                    left, right = left - 1, right - 1
            continue
        hunk = _HUNK.match(line)
        if hunk:
            left = int(hunk.group(2) if hunk.group(2) is not None else 1)
            right = int(hunk.group(4) if hunk.group(4) is not None else 1)
            continue
        if line.startswith("diff --git "):
            m = _DIFF_FILE.match(line)
            if not m:
                if errors is not None:
                    errors.append(f"unreadable diff header: {line[:200]}")
                cur = None
                continue
            old_path = _side(m.group(1), "a/")
            cur = FileChange(_side(m.group(2), "b/"), "modified")
            files.append(cur)
            minus = None
            continue
        if line.startswith("--- "):
            minus = line[4:]
            continue
        if line.startswith("+++ ") and minus is not None:
            new = line[4:]
            path = None if unquote_path(new) == "/dev/null" else _side(new, "b/")
            gone = None if unquote_path(minus) == "/dev/null" else _side(minus, "a/")
            if cur is None or (path or gone) != cur.path:       # a file the `diff --git` lines did not announce
                cur = FileChange(path or gone or "", "added" if gone is None else "removed" if path is None else "modified")
                files.append(cur)
            minus = None
            continue
        if cur is None:
            continue
        if line.startswith("new file mode"):
            cur.status = "added"
        elif line.startswith("deleted file mode"):
            cur.status = "removed"
            cur.path = old_path or cur.path
        elif line.startswith(("rename from ", "copy from ")):
            if line.startswith("rename from "):
                files.insert(len(files) - 1, FileChange(unquote_path(line[len("rename from "):]), "removed"))
        elif line.startswith(("rename to ", "copy to ")):
            cur.path, cur.status = unquote_path(line.split(" to ", 1)[1]), "added"
        elif line.startswith("+"):            # content past a hunk's stated length: still read, never dropped
            cur.added.append(line[1:])
        elif line.startswith("-"):
            cur.removed.append(line[1:])
    return files


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def change_from_diff(diff_text: str, *, base_dir=None, scope=(), core=(), terms=None, claim=True) -> Change:
    base = Path(base_dir) if base_dir is not None else None
    errors: list = []
    files = parse_diff(diff_text, errors)
    if base is not None:
        for f in files:
            if (base / f.path).is_file():
                f.before = _read(base / f.path)
                if f.status == "added":          # the diff says new, the base has it: the strict answer, an edit
                    f.status = "modified"
    terms = dict(terms) if terms is not None else _proof_toml(base)
    runner = guess_runner(base, (), terms)
    test_dirs = tuple(terms.get("test_dirs") or _default_dirs(runner))
    seen = visible_literal_tests(base, test_dirs)
    return Change(files, runner, test_dirs, terms, tuple(scope or ()), tuple(core or ()), claim,
                  frozenset(seen), errors, seen)


# ---- the registry ----------------------------------------------------------------------------------------------------

RULES: dict[str, Rule] = {}


def add_rule(rule: Rule) -> Rule:
    """A newly caught cheat type becomes a named rule. Ids are never reused and rules are never replaced."""
    if rule.id in RULES:
        raise ValueError(f"rule {rule.id} exists; the library only grows (pick a new id)")
    RULES[rule.id] = rule
    return rule


def rules(category: str | None = None, kind: str | None = None) -> list[Rule]:
    return [r for r in RULES.values() if (category is None or r.category == category) and (kind is None or r.kind == kind)]


def run(change: Change, only: Iterable[str] | None = None) -> list[Finding]:
    """Every change rule (or only those named) on one change. Rules never raise into the caller, and never pass
    silently either: a rule that crashes, or a diff that could not be read, is a refusing `rule_error` finding
    (fail closed: a cheat must not get through by making a rule crash)."""
    out: list[Finding] = [Finding("rule_error", "rule_error", "", e, "refuse") for e in change.errors]
    wanted = set(only) if only is not None else None
    for r in RULES.values():
        if r.kind != "change" or r.check is None or (wanted is not None and r.id not in wanted):
            continue
        try:
            got = r.check(change) or []
        except Exception as why:  # noqa: BLE001 - said as a refusal, never swallowed
            out.append(Finding("rule_error", "rule_error", "", f"rule {r.id} could not run: {type(why).__name__}: {str(why)[:160]}", "refuse"))
            continue
        for f in got:
            out.append(Finding(r.id, r.category, f.path, f.detail, r.severity))
    seen, unique = set(), []
    for f in out:
        key = (f.rule, f.path)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def scan(base_dir, pr_dir, *, changed=None, scope=(), core=(), terms=None, claim=True) -> list[Finding]:
    """The cheat rules on two trees (the base, the pull request). Runs none of the pull request's code."""
    return run(change_from_trees(base_dir, pr_dir, changed=changed, scope=scope, core=core, terms=terms, claim=claim))


def scan_diff(diff_text: str, *, base_dir=None, scope=(), core=(), terms=None, claim=True) -> list[Finding]:
    """The cheat rules on a unified git diff (Gate, the free maintainer mode, the self loop). With `base_dir`, the
    base's tests are read for the literals an author could copy, and the base's proof.toml for the test directories."""
    return run(change_from_diff(diff_text, base_dir=base_dir, scope=scope, core=core, terms=terms, claim=claim))


def refused(findings: Iterable[Finding]) -> bool:
    return any(f.severity == "refuse" for f in findings)


def categories(findings: Iterable[Finding]) -> list[str]:
    return sorted({f.category for f in findings})


def matches(path: str, globs: Iterable[str]) -> bool:
    path = path.replace("\\", "/").removeprefix("./")
    for g in globs:
        g = str(g).replace("\\", "/").removeprefix("./")
        if g.endswith("/**") and (path + "/").startswith(g[:-2]):
            return True
        if fnmatch.fnmatchcase(path, g) or (g.startswith("**/") and fnmatch.fnmatchcase(path, g[3:])):
            return True
        if not any(c in g for c in "*?[") and (path == g or path.startswith(g.rstrip("/") + "/")):
            return True
    return False
