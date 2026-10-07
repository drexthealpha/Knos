"""The one thing that crosses from the job that runs a pull request's code to the job that signs: a verdict, as data.

    python -m knos.verdict_gate emit --base base --issue N --changed changed.txt     the judge job, after the suite passed
    python -m knos.verdict_gate check                                                the signing job, before anything signs
    python -m knos.verdict_gate shape                                                attest.yml's signing job: KNOS_RERUN, strictly

GitHub signs WHICH workflow ran. It does not sign what an earlier job told a later one. So the job that runs a
stranger's code (prove.yml's `judge`) is treated as lost the moment that code starts: it has no id-token, no secret and
a token that only reads. What it hands on is one line of JSON with FIXED keys, each a number, a boolean or a string of
a fixed shape (commit ids, hashes, one word of a short list). There is no free text in it: nothing to quote into a
shell, a comment or a sentence. The job that signs runs none of that code and takes none of its files. It

  1. reads the line as text (`read`): one small ASCII JSON object, no key twice, no nesting, exactly the keys of SCHEMA;
  2. holds it to what it knows itself (`holds`): this repository, this run, this pull request, this issue, this head
     commit, this base commit, this workflow commit. A verdict about anything else is another verdict;
  3. recomputes what it can (`recheck`), from GitHub's own record and never from the judge's machine: that the commit
     is the pull request's head, what the pull request changed and what the judge's rule says of every changed path
     (`knos.judge.classify_path`), and the hash of the acceptance bundle on the base commit;
  4. and only then lets the next step ask for the token, whose audience that step derives itself.

What it cannot recompute is said in docs/SECURITY.md ("Where untrusted code runs"): that the suite passed is the
judge machine's word. This module shrinks what that word can do to one bit about one pull request at one commit.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Mapping

MAX = 2048                      # bytes of one verdict: the largest honest one is under 700
MAX_FILES = 300                 # changed files GitHub lists for one comparison (its own limit)
MAX_PAGES = 30                  # pages of 100 files GitHub lists for one pull request (its own limit: 3,000 files)
MAX_BUNDLE = 200                # files of one acceptance bundle (knos.flow.MAX_BUNDLE)
RUNNERS = ("python", "node", "go", "rust", "ruby", "command", "blackbox")       # knos.judge.RUNNERS
_HEX40, _HEX64, _INT = r"[0-9a-f]{40}", r"[0-9a-f]{64}", (1, 2**53)
SCHEMA: dict[str, Any] = {     # every key a verdict has, and what its value may be: an (inclusive) range, a pattern, or a type
    "v": (2, 2), "kind": r"judge", "passed": bool,
    "repository_id": _INT, "run": _INT, "attempt": (1, 10_000), "workflow_sha": _HEX40,
    "pull": _INT, "issue": _INT, "head": _HEX40, "base": _HEX40,
    "accept": _HEX64,           # knos.judge.checks_hash of .knos/acceptance/<issue>/ in the base tree the suite ran from
    "changed": _HEX64,          # `changed_hash` of the paths the judge was told the pull request changed
    "changed_count": (0, 1_000_000),
    "runner": "|".join(RUNNERS),
    "image": r"[A-Za-z0-9._-]{0,48}",       # the runner image, as the machine names it (ImageOS-ImageVersion): a record, never a condition
}
_SHAPES = {"head": _HEX40, "base": _HEX40, "accept": _HEX64, "order": r"[1-9A-HJ-NP-Za-km-z]{32,44}", "repository": r"[\w.-]{1,100}/[\w.-]{1,100}"}
_RERUN_KEYS = {"v", "reexecuted", "passed", "sentence", "order", "repository", "pull", "issue", "head", "base", "accept", "assurance",
               "image", "artifact", "environment", "reasons", "verdict", "reason"}        # knos.flow._RERUN_KEYS, and the judge's word


class Refused(Exception):
    """Why a verdict carries nothing: one plain sentence."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    out: dict = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("a key is there twice")
        out[k] = v
    return out


def _no(text: str):
    raise ValueError("not a number a verdict has")


def strict(text: str, most: int = MAX) -> dict:
    """`text` as one JSON object, or Refused: at most `most` bytes, printable ASCII only, no key twice, no fraction,
    no NaN. What a lenient reader would accept and two readers would read differently is refused here."""
    if not isinstance(text, str) or len(text.encode("utf-8", "replace")) > most:
        raise Refused("the verdict is larger than a verdict is")
    if not text.strip():
        raise Refused("there is no verdict")
    if re.search(r"[^\x20-\x7e\n]", text):
        raise Refused("the verdict holds characters a verdict does not have")
    try:
        v = json.loads(text, object_pairs_hook=_pairs, parse_float=_no, parse_constant=_no)
    except (ValueError, RecursionError):
        raise Refused("the verdict is not one JSON object with each key once") from None
    if not isinstance(v, dict):
        raise Refused("the verdict is not one JSON object with each key once")
    return v


def read(text: str) -> dict:
    """The judge job's verdict, or Refused: exactly the keys of SCHEMA, each of its type, range or shape."""
    v = strict(text)
    if set(v) != set(SCHEMA):
        raise Refused("the verdict does not have exactly the fields a verdict has")
    for k, rule in SCHEMA.items():
        x = v[k]
        if rule is bool:
            ok = isinstance(x, bool)
        elif isinstance(rule, tuple):
            ok = type(x) is int and rule[0] <= x <= rule[1]
        else:
            ok = isinstance(x, str) and re.fullmatch(rule, x) is not None
        if not ok:
            raise Refused(f"the verdict's `{k}` is not what a verdict's is")
    return v


def read_file(path: str | os.PathLike, most: int = MAX) -> str:
    """A verdict handed over as a file (an artifact), or Refused: one regular file with one name, not a link, not a
    folder, not a device, at most `most` bytes. It is opened once and what was opened is what is checked."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        if os.path.islink(path):
            raise Refused("the verdict file is a link, and a verdict is a plain file")
        fd = os.open(path, flags)
    except OSError:
        raise Refused("the verdict file is not a plain file that can be read") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
            raise Refused("the verdict file is not a plain file with one name")
        if st.st_size > most:
            raise Refused("the verdict is larger than a verdict is")
        raw = os.read(fd, most + 1)
    finally:
        os.close(fd)
    if len(raw) > most:
        raise Refused("the verdict is larger than a verdict is")
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        raise Refused("the verdict holds characters a verdict does not have") from None


def from_folder(folder: str | os.PathLike, name: str = "verdict.json") -> str:
    """A downloaded artifact's one file, or Refused: the folder holds exactly `name` and nothing beside it (an
    artifact two jobs wrote into, or one with a second file, is not a verdict)."""
    try:
        held = sorted(os.listdir(folder))
    except OSError:
        raise Refused("there is no verdict") from None
    if held != [name]:
        raise Refused("the verdict's artifact holds something other than the one verdict file")
    return read_file(os.path.join(folder, name))


def changed_hash(paths) -> str:
    """One hash of a set of changed paths: sorted, each once, as git names them (forward slashes), one a line."""
    names = sorted({str(p).strip().replace("\\", "/").removeprefix("./") for p in paths if str(p).strip()})
    return hashlib.sha256("".join(n + "\n" for n in names).encode("utf-8", "surrogateescape")).hexdigest()


def expected(env: Mapping[str, str], pull: str, head: str, issue: str) -> dict[str, Any]:
    """What the signing job knows itself, before it reads anything of the judge's: where it runs (GitHub's own
    variables of the run) and which pull request, commit and issue the review named. Refused when it does not know."""
    try:
        want: dict[str, Any] = {"repository_id": int(env["GITHUB_REPOSITORY_ID"]), "run": int(env["GITHUB_RUN_ID"]), "attempt": int(env.get("GITHUB_RUN_ATTEMPT") or 1),
                "workflow_sha": str(env.get("GITHUB_WORKFLOW_SHA") or ""), "base": str(env["GITHUB_SHA"]), "pull": int(pull), "issue": int(issue), "head": str(head)}
    except (KeyError, ValueError):
        raise Refused("this job does not know which run, pull request and commit it is for") from None
    if not re.fullmatch(_HEX40, want["head"]) or not re.fullmatch(_HEX40, want["base"]) or want["pull"] < 1 or want["issue"] < 1:
        raise Refused("this job does not know which run, pull request and commit it is for")
    return want


def holds(v: dict, want: dict) -> None:
    """Refused unless the verdict `v` (from `read`) is about exactly what this job is for (`expected`) and passed.
    The attempt may be an earlier one of the same run (the signing job run again alone), never a later one."""
    said = {"repository_id": "repository", "run": "run", "pull": "pull request", "issue": "issue", "head": "head commit", "base": "base commit"}
    for k, word in said.items():
        if v[k] != want[k]:
            raise Refused(f"the verdict is of another {word} than this job signs for")
    if want.get("workflow_sha") and v["workflow_sha"] != want["workflow_sha"]:
        raise Refused("the verdict is from another commit of the workflow than this job runs")
    if v["attempt"] > want["attempt"]:
        raise Refused("the verdict is from a later attempt of the run than this job's")
    if v["passed"] is not True:
        raise Refused("the acceptance checks did not pass")


def runner_from(cfg: dict, bundle_names, root_names) -> str:
    """knos.judge.runner_of, from names alone (the acceptance bundle's file names and the base commit's top folder),
    so the job that signs can work it out from GitHub's record with no tree in hand. tests/test_verdict_gate.py holds
    the two to the same answer."""
    j: dict = cfg["judge"] if isinstance(cfg.get("judge"), dict) else {}
    named = cfg.get("runner") or j.get("runner")
    if named:
        if named not in RUNNERS:
            raise Refused("the repository's .knos/proof.toml names a runner Knos does not have")
        return str(named)
    if j.get("run"):
        return "command"
    names = [str(n).rsplit("/", 1)[-1] for n in bundle_names]
    if any(n in ("blackbox", "blackbox.sh", "blackbox.py") for n in names):
        return "blackbox"
    if any(n in ("check", "check.sh") for n in names):
        return "command"
    for ext, runner in ((".py", "python"), ("_test.go", "go"), (".rs", "rust")):
        if any(n.endswith(ext) for n in names):
            return runner
    if any(re.search(r"\.[cm]?[jt]s$", n) for n in names):
        return "node"
    if any(n == "Gemfile" or str(n).endswith(".gemspec") for n in root_names):
        return "ruby"
    return "python"


def refused_paths(changes: list[tuple[str, str]], cfg: dict, runner: str) -> list[tuple[str, str]]:
    """[(path, refusal code)] for every changed path the judge's rule refuses: `changes` is [(path, "added" |
    "modified" | "removed")] as GitHub records the pull request. The rule is knos.judge.classify_path, unchanged."""
    from . import judge
    terms = {k: cfg[k] for k in ("test_dirs", "protected") if k in cfg}
    out = []
    for path, status in changes:
        word = judge.classify_path(path, {**terms, "runner": runner}, status)
        if word.startswith("refused:"):
            out.append((path, word.split(":", 1)[1]))
    return out


def _changes(files) -> list[tuple[str, str]]:
    """GitHub's list of a comparison's files as [(path, status)], a rename under both its names (as `git diff
    --no-renames` has it: the judge's own list)."""
    out: list[tuple[str, str]] = []
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("filename"), str):
            raise OSError("GitHub's list of the changed files was not understood")
        status = str(f.get("status") or "")
        out.append((f["filename"], "added" if status in ("added", "copied", "renamed") else "removed" if status == "removed" else "modified"))
        if status == "renamed" and isinstance(f.get("previous_filename"), str):
            out.append((f["previous_filename"], "removed"))
    return out


def _content(got) -> str | None:
    try:
        return base64.b64decode(got["content"]).decode("utf-8") if got.get("encoding") == "base64" else None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _get(github: Callable, path: str, missing_ok: bool = False):
    try:
        return github(path)
    except OSError as why:
        if missing_ok and getattr(why, "code", None) == 404:
            return None
        raise


def recheck(v: dict, repo: str, github: Callable) -> list[str]:
    """What the signing job recomputes from GitHub's record, for a verdict that `holds`. Refused when the record and
    the verdict disagree; OSError when GitHub does not answer (nothing is signed, and the run can be started again).
    Returns what was checked, one short line each, for the run's summary."""
    from . import judge
    if not re.fullmatch(r"[\w.-]{1,100}/[\w.-]{1,100}", repo):
        raise Refused("this job does not know which repository it is for")
    base, head, issue, done = v["base"], v["head"], v["issue"], []
    pull = github(f"repos/{repo}/pulls/{v['pull']}")
    if not isinstance(pull, dict) or not isinstance(pull.get("head"), dict) or not isinstance(pull.get("base"), dict):
        raise OSError("GitHub's record of the pull request was not understood")
    if pull["head"].get("sha") != head:
        raise Refused("the pull request's head commit is no longer the one that was judged")
    if ((pull["base"].get("repo") or {}).get("id")) != v["repository_id"]:
        raise Refused("the pull request is not one of this repository")
    done.append(f"commit `{head[:7]}` is the head of pull request #{v['pull']} of this repository")
    # the acceptance bundle on the base commit, hashed here from GitHub's copy of each file
    listing = _get(github, f"repos/{repo}/contents/.knos/acceptance?ref={base}", missing_ok=True)
    tree = next((e.get("sha") for e in listing if isinstance(e, dict) and e.get("name") == str(issue) and e.get("type") == "dir"),
                None) if isinstance(listing, list) else None
    if not tree or not re.fullmatch(_HEX40, str(tree)):
        raise Refused("the base commit has no acceptance checks for this issue")
    got = github(f"repos/{repo}/git/trees/{tree}?recursive=1")
    if not isinstance(got, dict) or not isinstance(got.get("tree"), list):
        raise OSError("GitHub's listing of the acceptance checks was not understood")
    files = sorted((e for e in got["tree"] if isinstance(e, dict) and e.get("type") != "tree"), key=lambda e: str(e.get("path")))
    if got.get("truncated") or len(files) > MAX_BUNDLE or any(e.get("type") != "blob" or e.get("mode") == "120000" for e in files):
        raise Refused("the acceptance checks on the base commit are not a small folder of plain files")
    lines = []
    for e in files:
        blob = github(f"repos/{repo}/git/blobs/{e.get('sha')}")
        try:
            content = base64.b64decode(blob["content"]) if blob.get("encoding") == "base64" else None
        except (AttributeError, KeyError, TypeError, ValueError):
            content = None
        if content is None:
            raise OSError("GitHub's copy of an acceptance check was not understood")
        lines.append(f"{e.get('path')}\0{hashlib.sha256(content).hexdigest()}\n")
    if hashlib.sha256("".join(lines).encode()).hexdigest() != v["accept"]:
        raise Refused("the acceptance checks the judge ran are not the ones on the base commit")
    done.append(f"the acceptance checks the judge ran are the {len(files)} file(s) of `.knos/acceptance/{issue}/` at `{base[:7]}`")
    # the runner, from the repository's own configuration and the bundle's names
    text = _get(github, f"repos/{repo}/contents/.knos/proof.toml?ref={base}", missing_ok=True)
    cfg = judge.proof_config(_content(text) if isinstance(text, dict) else None)
    root = _get(github, f"repos/{repo}/contents?ref={base}", missing_ok=True)
    roots = [str(e.get("name")) for e in root if isinstance(e, dict) and e.get("type") == "file"] if isinstance(root, list) else []
    runner = runner_from(cfg, [str(e.get("path")) for e in files], roots)
    if runner != v["runner"]:
        raise Refused("the judge ran the checks with another runner than the base commit's files call for")
    # what the pull request changed, as GitHub records it, and what the judge's rule says of each path
    compared = github(f"repos/{repo}/compare/{base}...{head}?per_page=1")
    listed = compared.get("files") if isinstance(compared, dict) else None
    if not isinstance(listed, list):
        raise OSError("GitHub's comparison of the two commits was not understood")
    whole = len(listed) < MAX_FILES
    if not whole:       # more than one comparison lists: the pull request's own list, page by page
        listed = []
        for page in range(1, MAX_PAGES + 1):
            more = github(f"repos/{repo}/pulls/{v['pull']}/files?per_page=100&page={page}")
            if not isinstance(more, list):
                raise OSError("GitHub's list of the changed files was not understood")
            listed += more
            if len(more) < 100:
                break
        else:
            raise Refused("the pull request changes more files than GitHub lists, so its paths cannot be checked again here")
    changes = _changes(listed)
    bad = refused_paths(changes, cfg, runner)
    if bad:
        path, code = bad[0]
        raise Refused(f"the pull request changes a path the judge's rule refuses ({code}): {urllib.parse.quote(path, safe='/._-')[:120]}"
                      + (f", and {len(bad) - 1} more" if len(bad) > 1 else ""))
    done.append(f"none of the {len(changes)} changed path(s) GitHub records is one the judge's rule refuses (runner {runner})")
    if whole:
        if changed_hash(p for p, _s in changes) != v["changed"] or len({p for p, _s in changes}) != v["changed_count"]:
            raise Refused("the judge was told of other changed paths than GitHub records for these two commits")
        done.append("the paths the judge was told of are exactly those")
    else:
        done.append(f"the pull request changes {MAX_FILES} files or more: the judge's own list of them was not compared")
    return done


def emit(env: Mapping[str, str], base: Path, issue: str, changed: Path, pull: str, head: str) -> str:
    """The judge job's verdict line, written after the suite passed. Everything in it is a number, a hash or one word
    of a list; the job that signs believes none of it before it has checked it."""
    from . import judge
    try:
        text = (base / ".knos" / "proof.toml").read_text(encoding="utf-8")
    except OSError:
        text = None
    cfg = {**judge.proof_config(text), "issue": str(issue)}
    names = [ln for ln in changed.read_text(encoding="utf-8", errors="surrogateescape").splitlines() if ln.strip()]
    image = re.sub(r"[^A-Za-z0-9._-]", "", f"{env.get('ImageOS', '')}-{env.get('ImageVersion', '')}".strip("-"))[:48]
    v = {"v": 2, "kind": "judge", "passed": True, "repository_id": int(env["GITHUB_REPOSITORY_ID"]), "run": int(env["GITHUB_RUN_ID"]),
         "attempt": int(env.get("GITHUB_RUN_ATTEMPT") or 1), "workflow_sha": str(env.get("GITHUB_WORKFLOW_SHA") or ""), "pull": int(pull), "issue": int(issue),
         "head": str(head), "base": str(env["GITHUB_SHA"]), "accept": judge.checks_hash(base / ".knos" / "acceptance" / str(int(issue))),
         "changed": changed_hash(names), "changed_count": len({n.strip().replace("\\", "/").removeprefix("./") for n in names}),
         "runner": judge.runner_of(base, cfg), "image": image}
    line = json.dumps(v, sort_keys=True, separators=(",", ":"))
    read(line)          # what this job hands on is what the next one accepts, or nothing is handed on
    return line


def shape(text: str) -> None:
    """attest.yml's verdict (knos.flow._rerun_verdict), held to what any reader agrees on before `knos attest` reads it:
    small, printable ASCII, one object with each key once and only keys a verdict has, nothing nested deeper than
    one object of short strings. Refused otherwise. Which order it is about is `knos attest`'s to check."""
    v = strict(text, 8192)
    if set(v) - _RERUN_KEYS:
        raise Refused("the verdict has a field a verdict does not have")
    for k, x in v.items():
        if isinstance(x, dict):
            if len(x) > 16 or not all(isinstance(y, str) and len(y) <= 200 for y in x.values()):
                raise Refused(f"the verdict's `{k}` is not what a verdict's is")
        elif isinstance(x, list):
            if len(x) > 6 or not all(isinstance(y, str) and len(y) <= 200 for y in x):
                raise Refused(f"the verdict's `{k}` is not what a verdict's is")
        elif not isinstance(x, (bool, int, str)) or (isinstance(x, str) and len(x) > 300) or (type(x) is int and not 0 <= x <= 2**53):
            raise Refused(f"the verdict's `{k}` is not what a verdict's is")
        if k in _SHAPES and not (isinstance(x, str) and re.fullmatch(_SHAPES[k], x)):
            raise Refused(f"the verdict's `{k}` is not what a verdict's is")


def _say(env: Mapping[str, str], text: str) -> None:
    print(text)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None, github: Callable | None = None) -> int:
    import argparse
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(prog="python -m knos.verdict_gate", description=(__doc__ or "").split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit", help="the judge job: write the verdict line (the output `verdict`)")
    e.add_argument("--base", required=True)
    e.add_argument("--issue", required=True)
    e.add_argument("--changed", required=True)
    c = sub.add_parser("check", help="the signing job: read VERDICT (or --file), hold it to this run and check it again from GitHub's record")
    c.add_argument("--file", default="", help="the verdict as a file, or a folder that holds verdict.json and nothing else")
    c.add_argument("--offline", action="store_true", help="shape and binding only: nothing is read from GitHub")
    sub.add_parser("shape", help="attest.yml's signing job: KNOS_RERUN is text any reader reads the same way")
    a = p.parse_args(argv)
    try:
        if a.cmd == "emit":
            line = emit(env, Path(a.base), a.issue, Path(a.changed), str(env.get("PULL") or ""), str(env.get("HEAD") or ""))
            if env.get("GITHUB_OUTPUT"):
                with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
                    f.write(f"verdict={line}\n")
            print(line)
            return 0
        if a.cmd == "shape":
            text = str(env.get("KNOS_RERUN") or "")
            if text.strip():        # with none, `knos attest` says what is missing
                shape(text)
            print("Knos: the verdict handed to this job is one small object of the fields a verdict has.")
            return 0
        text = (from_folder(a.file) if os.path.isdir(a.file) and not os.path.islink(a.file) else read_file(a.file)) if a.file else str(env.get("VERDICT") or "")
        v = read(text)
        holds(v, expected(env, str(env.get("PULL") or ""), str(env.get("HEAD") or ""), str(env.get("ISSUE") or "")))
        done = ["the verdict is of this run, this pull request, this issue and these two commits"]
        if not a.offline:
            if github is None:
                from . import judge
                github = judge.github
            done += recheck(v, str(env.get("GITHUB_REPOSITORY") or ""), github)
        _say(env, "Knos: the judge's verdict was read as data and checked again here before anything is signed:\n" + "".join(f"- {d}\n" for d in done))
        return 0
    except Refused as why:
        _say(env, f"Knos: nothing is signed. {str(why)[0].upper()}{str(why)[1:]}.")
        return 1
    except (OSError, KeyError, ValueError) as why:
        _say(env, f"Knos: nothing is signed. This could not be checked just now ({type(why).__name__}). Run the workflow again.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
