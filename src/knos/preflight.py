"""`knos preflight`: what an order will hold a change to, said in the supplier's checkout before anything is submitted.

    knos preflight --terms terms.json                 offline: the terms from a file, the change from git
    knos preflight --issue owner/repo#12              the terms from the funded issue's `knos-terms:` line
    knos preflight --terms terms.json --changed FILE  no git: the change as `git diff --name-status` printed it

It reads the order's terms and the change, and says:

    protected   which paths the change may not touch (the terms' `deny`; in tests mode also what the judge protects)
    checks      which checks the order names (they run on the pull request; nothing here can pass them for you)
    changes     each changed file as one of three: allowed; allowed and not counted (a test file you ADD: the judge
                runs the buyer's tests, so yours is welcome and decides nothing); refused, with the refusal's code,
                its two sentences (knos.ghwords.REFUSALS) and the exact line of the terms that says so
    ready       true, or the list of fixes. The command exits 0 only when ready.

What it does not do: it does not run the acceptance checks (`knos proof judge --base ... --pr ... --issue N` does, and
the report names that command for a tests-mode order), and it cannot know whether the named checks will pass.

Memory (knos.proof.history, the memory engine; no side file): before answering it recalls what was refused before
under the SAME terms hash in this repository ("3 earlier submissions were refused for touching tests/conftest.py"),
and it remembers each preflight's result. With the engine absent it works the same and says memory is off.

`knos keep <order or transaction> --out DIR` writes the supplier's own copy of everything about a deliverable: the
evidence bundle (`knos bundle make`, called as it is), and what memory holds of their preflights, refusals and appeals.

    read_terms(text)                   the terms, their hash and where each clause is written
    changes_from_git(tree, base)       [(status, path)] of the change against the base branch, untracked files included
    run(terms, changes, ...)           the report (a dict; `words(report)` prints it)
    MCP_TOOL, mcp(args)                the same as a tool an agent calls (knos.mcp registers it)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from . import ghwords
from . import terms as bounty

KIND, VERSION = "knos-preflight", 1
CLASSES = ("allowed", "allowed_not_counted", "refused")
TERMS_LINE = re.compile(r"^knos-terms: (\{.*\})\s*$", re.M)
_ISSUE = re.compile(r"([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100})#([1-9][0-9]{0,9})")
BASES = ("origin/HEAD", "origin/main", "origin/master", "main", "master")


class Unreadable(ValueError):
    """The terms or the change could not be read. The message is one sentence and says what to give instead."""


# ---- the terms -------------------------------------------------------------------------------------------------------

def read_terms(text: str) -> dict:
    """{"terms", "hash", "text", "source"} from a terms file: the canonical bytes (a `knos-terms:` line's JSON), the same
    object written over several lines, or a published template (terms/<name>/<version>.json, whose `terms` it holds).
    Raises Unreadable."""
    try:
        got = json.loads(text)
    except ValueError:
        raise Unreadable("the terms file is not JSON. Give the JSON of the order's `knos-terms:` line, or a file from terms/.") from None
    source = "terms file"
    if isinstance(got, dict) and isinstance(got.get("terms"), dict):
        got, source = got["terms"], f"template {got.get('name', '')} {got.get('version', '')}".strip()
    try:
        raw = bounty.canonical(got)
    except bounty.Refused as why:
        raise Unreadable(f"these are not an order's terms: {why}.") from None
    return {"terms": bounty.parse(raw), "hash": bounty.terms_hash(raw), "text": text, "source": source}


def terms_from_issue(issue: str, get) -> dict:
    """The terms of the newest funding of `owner/repo#N`: the `knos-terms:` line Knos wrote when it was funded, read
    with `get(path)` (knos.judge.github). Raises Unreadable when the issue has none or GitHub does not answer."""
    m = _ISSUE.fullmatch(issue.strip())
    if not m:
        raise Unreadable("--issue is owner/repo#number, like acme/app#12.")
    repo, number = m.group(1), m.group(2)
    path = f"repos/{repo}/issues/{number}/comments"
    rows = bounty.pages(path, get)
    if rows is None:
        raise Unreadable(f"GitHub did not give the comments of {issue}; {ghwords.RATE}, or give --terms FILE.")
    found = [m2.group(1) for row in rows if isinstance(row, dict) for m2 in TERMS_LINE.finditer(str(row.get("body") or ""))]
    if not found:
        raise Unreadable(f"{issue} has no `knos-terms:` line: it is not funded, or its terms are kept elsewhere. Give --terms FILE.")
    got = read_terms(found[-1])
    return {**got, "source": issue}


def _cite(read: dict, key: str, value: str) -> dict:
    """Where the terms say it: the clause, its line number in the text given, and that line (or, for terms written on
    one line, the clause's own text out of it)."""
    text, needle = read["text"], json.dumps(value)
    lines = text.splitlines() or [text]
    at = next((i for i, line in enumerate(lines, 1) if needle in line and (len(lines) > 1 or f'"{key}"' in line)), None)
    exact = lines[at - 1].strip() if at else ""
    if at and len(exact) > 160:                       # one long line: quote the clause out of it, as it is written there
        m = re.search(r'"%s":\s*(\[[^\]]*\]|"[^"]*")' % re.escape(key), exact)
        exact = m.group(0) if m else exact[:160]
    return {"source": read["source"], "clause": f"{key}: {value}", "line": at, "text": exact}


# ---- the change ------------------------------------------------------------------------------------------------------

def _git(tree: Path, *args: str) -> tuple[int, str]:
    try:
        got = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return got.returncode, got.stdout


def read_changed(text: str) -> list[tuple[str, str]]:
    """[(status, path)] from `git diff --name-status` output (a rename gives its old name as D and its new one as A),
    or from a plain list of paths, one a line (each then counts as modified)."""
    out: list[tuple[str, str]] = []
    for line in text.replace("\0", "\n").splitlines():
        parts = line.rstrip("\r").split("\t")
        if not line.strip():
            continue
        if len(parts) >= 3 and parts[0][:1] in "RC":
            out += [("D", parts[1])] if parts[0][0] == "R" else []
            out.append(("A", parts[2]))
        elif len(parts) == 2 and re.fullmatch(r"[ACDMRTU][0-9]{0,3}", parts[0]):
            out.append((parts[0][0] if parts[0][0] in "AD" else "M", parts[1]))
        else:
            out.append(("M", line.strip()))
    return sorted(set(out), key=lambda sp: (sp[1], sp[0]))


def base_of(tree: Path, base: str = "") -> str | None:
    """The commit the change is measured against: the merge base with `base`, else with the first of BASES that exists."""
    for ref in ([base] if base else BASES):
        code, got = _git(tree, "merge-base", "HEAD", ref)
        if code == 0 and got.strip():
            return got.strip()
    return None


def changes_from_git(tree: Path, base: str = "") -> tuple[list[tuple[str, str]], str]:
    """([(status, path)], the base commit) for the checkout at `tree`: what is committed since the base, what is edited
    and not committed yet, and the files git does not track yet (they count as added). Raises Unreadable."""
    at = base_of(tree, base)
    if at is None:
        raise Unreadable(f"no base branch was found in {tree} (tried {base or ', '.join(BASES)}). Give --base <branch>, or --changed FILE.")
    code, diff = _git(tree, "diff", "--name-status", "-M", at)
    if code != 0:
        raise Unreadable(f"git could not compare {tree} with {at[:12]}. Give --changed FILE.")
    _code, new = _git(tree, "ls-files", "--others", "--exclude-standard")
    return read_changed(diff + "".join(f"A\t{p}\n" for p in new.splitlines() if p.strip())), at


def _base_text(tree: Path | None, base: str | None, path: str) -> str | None:
    if tree is None or not base:
        return None
    code, got = _git(tree, "show", f"{base}:{path}")
    return got if code == 0 else None


# ---- what the judge protects, and the three classes ------------------------------------------------------------------

def _pytest_changed(tree: Path | None, base: str | None, name: str) -> bool:
    """Whether the change alters the pytest section of pyproject.toml or setup.cfg (the judge refuses that and nothing
    else in those files). True when it cannot be told: a preflight never says ready on a guess."""
    from . import judge
    before = _base_text(tree, base, name)
    if tree is None or before is None:
        return True
    with tempfile.TemporaryDirectory(prefix="knos-preflight-") as tmp:
        (Path(tmp) / name).write_text(before, encoding="utf-8")
        return judge._pytest_section(Path(tmp), name) != judge._pytest_section(tree, name)


def judge_rule(path: str, status: str, patterns: list[str], tree: Path | None = None, base: str | None = None,
               runner: str = "python", test_dirs: list[str] | None = None) -> str | None:
    """What the judge does with one changed path in tests mode: None (it is not protected), `allowed_not_counted` (a
    test the change ADDS, or test configuration the run takes from the base), or the refusal's code. The rule is the
    judge's own, `knos.judge.classify_path`, and the codes are those of `judge.REFUSALS`; this module holds no copy.
    One thing needs the two trees and is asked here: whether pyproject.toml or setup.cfg changed its pytest section."""
    from . import judge
    dirs = list(test_dirs if test_dirs is not None else judge.TEST_DIRS[runner])
    said = judge.classify_path(path, {"runner": runner, "protected": patterns, "test_dirs": dirs}, {"A": "added", "D": "removed"}.get(status, "modified"))
    if said == judge.ALLOWED:
        if path in ("pyproject.toml", "setup.cfg") and runner in ("python", "command", "blackbox") and status != "A" and _pytest_changed(tree, base, path):
            return judge.NOT_COUNTED if judge.restored(path, dirs, runner) else ghwords.judge_code("not_from_base")
        return None
    return said if said == judge.NOT_COUNTED else ghwords.judge_code(said.split(":", 1)[1])


def _proof_cfg(tree: Path | None, base: str | None) -> tuple[dict, str]:
    """(the base's .knos/proof.toml, its text): the base's, because the change may not edit it."""
    from . import judge
    text = _base_text(tree, base, ".knos/proof.toml")
    if text is None and tree is not None:
        try:
            text = (tree / ".knos" / "proof.toml").read_text(encoding="utf-8")
        except OSError:
            text = None
    return judge.proof_config(text), text or ""


def _judge_cite(pattern: str, cfg: dict, cfg_text: str, read: dict) -> dict:
    if isinstance(cfg.get("protected"), list):
        at = next((i for i, line in enumerate(cfg_text.splitlines(), 1) if json.dumps(pattern) in line or f"'{pattern}'" in line or "protected" in line), None)
        return {"source": ".knos/proof.toml", "clause": f"protected: {pattern}", "line": at,
                "text": cfg_text.splitlines()[at - 1].strip()[:160] if at else ""}
    cited = _cite(read, "mode", "tests")
    return {**cited, "clause": f"mode: tests (the judge protects {pattern})"}


def _pattern_of(path: str, patterns: list[str]) -> str:
    from . import judge
    return next((p for p in patterns if judge.is_protected(path, [p])), path)


def _refusal(code: str, path: str, cite: dict) -> dict:
    happened, do = ghwords.refusal(code)
    return {"path": path, "class": "refused", "code": code, "happened": happened, "do": do, "says": cite}


def run(read: dict, changes: list[tuple[str, str]] | None, *, tree: Path | None = None, base: str | None = None, issue: str = "",
        store=None, repo: str = "", supplier: str = "", memory: dict | None = None, now: float | None = None) -> dict:
    """The preflight's report. `read`: read_terms' answer. `changes`: [(status, path)], or None when the change is not
    known (then only the rules are said, and it is not ready). `store`: the memory to recall from and remember in
    (knos.proof.history; None or a NullStore: no memory). Nothing here asks the network for anything."""
    from . import judge
    from .proof import history
    terms, thash = read["terms"], read["hash"]
    tests = terms["mode"] == "tests"
    cfg, cfg_text = _proof_cfg(tree, base) if tests else ({}, "")
    patterns: list[str] = []
    runner = "python"
    if tests:
        try:
            runner = judge.runner_of(tree if tree is not None else Path("."), {**cfg, "issue": issue})
        except ValueError:
            runner = "python"
        patterns = judge.protected_patterns(cfg, runner)
    rows, fixes = [], []
    for status, path in changes or []:
        denied = next((g for g in terms["deny"] if bounty.matches(path, g)), None)
        outside = bool(terms["paths"]) and not any(bounty.matches(path, g) for g in terms["paths"])
        rule = judge_rule(path, status, patterns, tree, base, runner, cfg.get("test_dirs")) if tests else None
        if denied:
            row = _refusal("terms.denied-path", path, _cite(read, "deny", denied))
        elif outside:
            row = _refusal("terms.out-of-scope", path, _cite(read, "paths", terms["paths"][0]) | {"clause": "paths: " + ", ".join(terms["paths"])})
        elif rule == "allowed_not_counted":
            row = {"path": path, "class": "allowed_not_counted", "why": "A test you add is welcome. The judge runs the buyer's tests; yours decides nothing."
                   if status == "A" else "The judge takes this file from the base. Your edit decides nothing."}
        elif rule:
            row = _refusal(rule, path, _judge_cite(_pattern_of(path, patterns), cfg, cfg_text, read))
        else:
            row = {"path": path, "class": "allowed"}
        rows.append({**row, "status": status})
        if row["class"] == "refused":
            fixes.append(f"{path}: {row['do']} ({row['code']})")
    if changes is None:
        fixes.append("The change could not be read: run this in your checkout, or give --changed FILE.")
    elif not changes:
        fixes.append("Nothing is changed against the base branch yet: commit or stage your work, then run this again.")
    counted = [r for r in rows if r["class"] == "allowed"]
    if changes and not counted and not any(r["class"] == "refused" for r in rows):
        fixes.append("Only new tests are changed, and they are not counted: the change needs the code that makes the buyer's checks pass.")
    ready = not fixes
    refused_rows = [r for r in rows if r["class"] == "refused"]
    memory = dict(memory or {"on": False, "said": "Memory is off: nothing is recalled or remembered."})
    warnings, record = [], None
    if store is not None and memory.get("on"):
        name = repo or (tree.resolve().name if tree is not None else "")
        held = getattr(store, "held", None)
        try:
            with held() if held is not None else contextlib.nullcontext(store):      # the recall and the remembering on one connection
                touched = {r["path"] for r in rows}
                for b in history.refused_before(store, name, thash):
                    n = b["count"]
                    what = f"touching {b['path']}" if b["path"] else ghwords.refusal(b["code"])[0].rstrip(".").lower()
                    warnings.append({"code": b["code"], "path": b["path"], "count": n, "yours": b["path"] in touched,
                                     "said": f"{n} earlier submission{'s were' if n != 1 else ' was'} refused for {what}"
                                             + (": your change touches it too." if b["path"] in touched else ".")})
                tree_id = hashlib.sha256(json.dumps([thash, sorted(changes or [])]).encode()).hexdigest()[:24]
                history.preflight_seen(store, name, thash, ready, [(r["code"], r["path"]) for r in refused_rows], supplier, tree_id, now)
                memory["remembered"] = True
                if supplier:
                    record = history.supplier_record(store, name, supplier)
        except Exception as why:  # noqa: BLE001 - a memory that fails never stops a preflight; it is said, as memory being off
            memory = {"on": False, "said": f"Memory is off: the memory engine did not answer ({ghwords.first_line(why, 80)})."}
    protected = [{"pattern": g, "says": _cite(read, "deny", g)} for g in terms["deny"]] + \
                [{"pattern": p, "says": _judge_cite(p, cfg, cfg_text, read)} for p in patterns if p not in terms["deny"]]
    nxt = []
    if tests:
        nxt.append(f"Run the acceptance checks yourself: knos proof judge --base <a checkout of the default branch> --pr . --issue {issue or '<issue>'}")
    if terms["checks"]:
        nxt.append("The named checks run on your pull request. Nothing here can pass them for you.")
    nxt.append("A refusal you think is wrong costs nothing to contest: /knos appeal <reason>")
    return {"kind": KIND, "v": VERSION, "ready": ready, "terms_hash": thash, "terms_source": read["source"], "mode": terms["mode"],
            "sentences": bounty.describe(terms), "checks": [c["name"] for c in terms["checks"]],
            "paths": list(terms["paths"]), "protected": protected,
            "allowed_not_counted": "A test file you add." if tests else "Nothing: this order is paid on a merge, and every allowed file counts.",
            "changes": rows, "fixes": fixes, "memory": {**memory, "warnings": warnings, **({"record": record} if record else {})},
            "next": nxt, "at": int(now if now is not None else time.time())}


def words(report: dict) -> str:
    """The report for a terminal: short lines, the fixes last."""
    out = [f"Terms {report['terms_hash'][:12]} ({report['terms_source']}, paid on {'acceptance checks' if report['mode'] == 'tests' else 'a merge'})",
           "", "Checked: " + (", ".join(report["checks"]) or "no named check"),
           "Allowed paths: " + (", ".join(report["paths"]) or "any, except the protected ones"),
           "Protected: " + ", ".join(p["pattern"] for p in report["protected"]),
           f"Allowed, not counted: {report['allowed_not_counted']}", ""]
    mark = {"allowed": "ok      ", "allowed_not_counted": "ok (not counted)", "refused": "REFUSED "}
    for r in report["changes"]:
        out.append(f"  {mark[r['class']]} {r['status']} {r['path']}")
        if r["class"] == "refused":
            says = r["says"]
            where = f"{says['source']}" + (f" line {says['line']}" if says["line"] else "") + (f": {says['text']}" if says["text"] else f": {says['clause']}")
            out += [f"           {r['happened']} {r['do']} ({r['code']})", f"           The terms say so here: {where}"]
    if report["changes"]:
        out.append("")
    for w in report["memory"]["warnings"]:
        out.append(f"Remembered: {w['said']}")
    record = report["memory"].get("record")
    if record:
        out.append(f"Your record here: {record['accepted']} accepted, {record['rejected']} rejected, {record['appealed']} appealed, {record['overturned']} overturned.")
    out += [report["memory"]["said"], ""]
    out += ["Ready: nothing in this change would be refused by the terms."] if report["ready"] else ["Not ready. Fix:", *(f"  - {f}" for f in report["fixes"])]
    out += ["", *report["next"]]
    return "\n".join(out)


# ---- memory ----------------------------------------------------------------------------------------------------------

def memory(tree: Path) -> tuple[object, dict]:
    """(the store, {"on", "said"}) for the checkout at `tree`: its tenant in the memory engine, or a store that keeps
    nothing when the engine is not installed or does not open. The second says which, in one sentence."""
    from .proof import history
    try:        # the engine is imported where the store is opened (knos.store): without it there is no memory, and that is said
        return history.SibylStore.for_repo(Path(tree)), {"on": True, "said": "Memory is on: this result is remembered in the memory engine."}
    except ImportError:
        return history.NullStore(), {"on": False, "said": "Memory is off: the memory engine (sibyl-memory-client) is not installed. Nothing is recalled or remembered."}
    except Exception as why:  # noqa: BLE001 - a store that does not open is no memory, never a failed preflight
        return history.NullStore(), {"on": False, "said": f"Memory is off: the memory engine did not open ({ghwords.first_line(why, 80)})."}


def repo_name(tree: Path) -> str:
    """owner/name from the checkout's `origin`, else the folder's name."""
    code, url = _git(tree, "remote", "get-url", "origin")
    m = re.search(r"[:/]([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]+?)(?:\.git)?/?\s*$", url) if code == 0 else None
    return m.group(1) if m else Path(tree).resolve().name


def check(tree: Path, terms_file: Path | None = None, issue: str = "", base: str = "", changed_file: Path | None = None,
          supplier: str = "", get=None, use_memory: bool = True) -> dict:
    """Everything `knos preflight` does, as one call: read the terms, read the change, recall, answer, remember."""
    tree = Path(tree)
    if terms_file is not None:
        try:
            read = read_terms(Path(terms_file).read_text(encoding="utf-8"))
        except OSError as why:
            raise Unreadable(f"{terms_file} could not be read: {ghwords.first_line(why, 80)}.") from None
    elif issue:
        if get is None:
            from . import judge
            get = judge.github
        read = terms_from_issue(issue, get)
    else:
        raise Unreadable("Name the terms: --terms FILE (works offline), or --issue owner/repo#number.")
    m = _ISSUE.fullmatch(issue.strip()) if issue else None
    number = m.group(2) if m else (issue if issue.isdigit() else "")
    at: str | None = None
    if changed_file is not None:
        try:
            changes: list[tuple[str, str]] | None = read_changed(Path(changed_file).read_text(encoding="utf-8"))
        except OSError as why:
            raise Unreadable(f"{changed_file} could not be read: {ghwords.first_line(why, 80)}.") from None
        at = base_of(tree, base)
    else:
        try:
            changes, at = changes_from_git(tree, base)
        except Unreadable:
            changes = None
    store, mem = memory(tree) if use_memory else (None, {"on": False, "said": "Memory is off: --no-memory was given."})
    if m and mem["on"] and get is not None:         # the network is in use already: bring what the judge learned on GitHub into memory
        try:
            from .proof import memory as carried
            carried.pull(m.group(1), store, get)
        except Exception:  # noqa: BLE001 - what GitHub holds of the judge's lessons is a help, never a condition
            pass
    return run(read, changes, tree=tree, base=at, issue=number, store=store, repo=(m.group(1) if m else repo_name(tree)),
               supplier=supplier, memory=mem)


# ---- for an agent (knos.mcp registers these two) ---------------------------------------------------------------------

MCP_TOOL = {
    "name": "knos_preflight", "title": "Preflight a change against an order's terms",
    "description": "Before you open a pull request: which paths the order protects, which checks it names, which of your changed "
                   "files would be refused (with the exact line of the terms that says so and what to do), what is allowed and not "
                   "counted (a test file you add), what was refused before under the same terms, and `ready` or the list of fixes. "
                   "Reads your checkout and a terms file; with `terms` it asks the network for nothing.",
    "properties": {"path": {"type": "string", "description": "your checkout of the repository, a folder on this machine"},
                   "terms": {"type": "string", "description": "a terms file on this machine: the JSON of the order's `knos-terms:` line, or a file from terms/"},
                   "issue": {"type": "string", "description": "the funded issue, as owner/repo#number (read from GitHub when `terms` is not given)"},
                   "base": {"type": "string", "description": "the branch the change is measured against (default: the default branch)"},
                   "supplier": {"type": "string", "description": "your GitHub login, to recall your own record here"}},
    "required": ["path"],
}


def mcp(args: dict, get=None) -> dict:
    """The tool's answer: the report, or {"ready": false, "fixes": [one sentence]} when the terms cannot be read."""
    try:
        return check(Path(str(args["path"])).expanduser(), Path(str(args["terms"])).expanduser() if args.get("terms") else None,
                     str(args.get("issue") or ""), str(args.get("base") or ""), None, str(args.get("supplier") or ""), get)
    except Unreadable as why:
        return {"kind": KIND, "v": VERSION, "ready": False, "fixes": [str(why)]}


# ---- the command line ------------------------------------------------------------------------------------------------

def keep(target: str, out: Path, tree: Path, supplier: str = "", rpc: str = "", bundle=None) -> dict:
    """Write the supplier's own copy of everything about a deliverable into `out`: the evidence bundle of its payment
    (`knos bundle make`, called as it is: `bundle(argv)` returns its exit code), what the memory engine holds of this
    repository's preflights, refusals and appeals, and the refusal table. Returns {"files", "bundle", "memory"}."""
    from .proof import history
    out.mkdir(parents=True, exist_ok=True)
    if bundle is None:
        from . import cli
        bundle = cli.main
    tar = out / "evidence.bundle.tar"
    code = bundle(["bundle", "make", target, "--out", str(tar), *(["--rpc", rpc] if rpc else [])])
    store, mem = memory(tree)
    name = repo_name(tree)
    mine = {"kind": "knos-supplier-copy", "v": 1, "target": target, "repo": name, "memory": mem,
            "bundle": tar.name if code == 0 and tar.is_file() else None,
            "preflights": history.preflights(store, name), "appeals": history.appeals(store, name, supplier or None),
            "record": history.supplier_record(store, name, supplier) if supplier else None}
    (out / "supplier.json").write_text(json.dumps(mine, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "REFUSALS.md").write_text("# What each refusal means, and what to do\n\n" + ghwords.refusal_table(), encoding="utf-8")
    return {"files": sorted(p.name for p in out.iterdir() if p.is_file()), "bundle": mine["bundle"], "memory": mem}


def register(app, help_lines: list | None = None) -> None:
    """`knos preflight` and `knos keep`, on the main app. `help_lines`: cli._HELP, which gets their lines."""
    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    if help_lines is not None:
        help_lines.append(("preflight", "For suppliers", "Before you open a pull request: what the order checks, what it would refuse, and how to fix it."))
        help_lines.append(("keep", "For suppliers", "Write your own copy of everything about a deliverable: the evidence bundle and your record."))

    @app.command("preflight", rich_help_panel="For suppliers")
    def preflight_(terms_file: Path = typer.Option(None, "--terms", help="the order's terms: the JSON of its `knos-terms:` line, or a file from terms/ (works offline)"),
                   issue: str = typer.Option("", "--issue", help="the funded issue, as owner/repo#number (asks GitHub for its terms when --terms is not given)"),
                   tree: Path = typer.Option(Path("."), "--tree", help="your checkout (default: here)"),
                   base: str = typer.Option("", "--base", help="the branch your change is measured against (default: the default branch)"),
                   changed: Path = typer.Option(None, "--changed", help="the change as `git diff --name-status` printed it, when there is no git here"),
                   by: str = typer.Option("", "--by", help="your GitHub login: recalls your own record in this repository"),
                   no_memory: bool = typer.Option(False, "--no-memory", help="recall nothing and remember nothing"),
                   as_json: bool = typer.Option(False, "--json", help="print the report as JSON")) -> None:
        """Say, before anything is submitted, what the order's terms hold this change to: the protected paths, the named
        checks, each changed file as allowed, allowed and not counted, or refused (with the line of the terms that says
        so and what to do), and what was refused before under the same terms. Exit 0 only when ready."""
        from . import cli
        try:
            report = check(tree, terms_file, issue, base, changed, by, use_memory=not no_memory)
        except Unreadable as why:
            raise cli.Stop(f"Preflight did not run: {why}", "knos preflight --terms FILE") from None
        typer.echo(json.dumps(report, indent=1, sort_keys=True) if as_json else words(report))
        if not report["ready"]:
            raise typer.Exit(1)

    @app.command("keep", rich_help_panel="For suppliers")
    def keep_(target: str = typer.Argument(..., help="the order's address, or the paying transaction's signature"),
              out: Path = typer.Option(..., "--out", help="the folder to write your copy into"),
              tree: Path = typer.Option(Path("."), "--tree", help="your checkout: its memory is the one read"),
              by: str = typer.Option("", "--by", help="your GitHub login: adds your record and your appeals"),
              rpc: str = typer.Option("", "--rpc", help="the cluster's JSON-RPC URL (default: KNOS_RPC, then devnet)")) -> None:
        """Write your own copy of everything about a deliverable: the evidence bundle of its payment (`knos bundle make`),
        what memory holds of your preflights, refusals and appeals here, and the refusal table. The copy needs nobody
        else to stay readable: `knos bundle verify` checks the bundle offline."""
        got = keep(target, out, tree, by, rpc)
        typer.echo(f"{out}: {', '.join(got['files'])}. {got['memory']['said']}")
        if not got["bundle"]:
            typer.echo("No evidence bundle was written (the line above says why). The rest of your copy is there.")
            raise typer.Exit(1)
