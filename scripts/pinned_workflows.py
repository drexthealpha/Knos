"""The workflows a repository calls, as drexthealpha/knos-workflows publishes them, and the one commit of that
repository that everything here names.

    python scripts/pinned_workflows.py lock WHEEL [--write | --out FILE]   requirements/sign.txt plus this wheel's hash: the lock
    python scripts/pinned_workflows.py build DIR [--lock FILE]      write the published set into DIR (default lock: requirements/sign.txt)
    python scripts/pinned_workflows.py build DIR --source REQ       a rehearsal variant: knos installed from REQ
    python scripts/pinned_workflows.py tree [--lock FILE]           the git tree id of the published set: what a commit of it must hold
    python scripts/pinned_workflows.py stamp SHA                    name the published commit everywhere it is named
    python scripts/pinned_workflows.py check [DIR [--lock FILE | --source REQ]]   exit 1 unless all of it is consistent

The source of truth is this repository: .github/workflows/fund.yml, prove.yml, check.yml and attest.yml, where they are
tested. A repository names them by a commit of drexthealpha/knos-workflows, and a bounty records that commit on chain.
That repository holds copies and nothing else: the four files, requirements/sign.txt, a short README and the LICENSE.

What crosses between jobs. In prove.yml and attest.yml the job that runs a pull request's code cannot sign, and the job
that signs runs none of it. One line of data crosses, and a step of the signing job reads it with a module of the very
release that job installed (`python -m knos.verdict_gate`). `check` holds every such step to a module and a command the
wheel has (`modules_run`).

What the jobs install, and why a release has an order. A job that signs, or holds a secret, installs from a list in
which every file is named by its sha256 (`uv pip install --require-hashes --no-deps --no-build`): every third-party
package (compiled with `uv pip compile --generate-hashes` from requirements/sign.in), and the knos wheel of the
release as the last line. That list is requirements/sign.txt here once a release is locked, it is written into the
install step of each such job, and it is published as requirements/sign.txt of the workflows' repository: the commit
of the workflows names the hash of everything those jobs install. The source workflows hold the word KNOS_LOCK where
the list goes; `build` writes it in, and a file that still says KNOS_LOCK installs nothing, so it cannot be published
by mistake.

The wheel's hash exists only once the wheel is built, and the commit of the workflows exists only once the list is in
them. So the wheel is built FIRST and ONCE, from the final tree, and nothing the wheel contains may name that commit:
src/knos never does, and README.md (the wheel's description on PyPI) is not a file `stamp` writes. The order, which
docs/RELEASE.md gives with every command (scripts/release.py runs it):

    1. Build the wheel once, reproducibly (`release.py wheel`): SOURCE_DATE_EPOCH fixed, the build backend pinned by
       hash. `lock WHEEL --write`: requirements/sign.txt gets the line `knos==X.Y.Z --hash=sha256:<this wheel>`.
       (`lock` refuses a wheel that is not the release the workflows name.)
    2. `build DIR` into a checkout of drexthealpha/knos-workflows and commit it there: its sha, S, is the one commit
       everything names; its tree is `tree`. Nothing signs from these workflows before this commit exists.
    3. `stamp S` here, then `check DIR`. The wheel built again from the stamped tree has the same hash (tested), so
       the ONE commit of the release holds the lock, the pin and the sources of the wheel at once.
    4. That wheel goes to PyPI before the push (`release.py publish`); then the push and the tag. release.yml uploads
       nothing to PyPI: it builds the wheel again, holds it to the locked hash, and fails unless PyPI serves a file
       with exactly that hash.
    A new third-party release changes nothing that is published: the list names what it names. Moving a dependency
    is a new requirements/sign.txt, a new release and the four steps again.

`stamp` replaces the placeholder KNOS_WORKFLOWS_SHA (or the commit named before) in examples/, in Knos's own knos.yml
and knos-check.yml, in docs/ and in the JavaScript client's README, and regenerates the site's templates (scripts/front_workflow.py writes
web/front.js from the examples). `check` says every place that disagrees.

The jobs that sign nothing (review and judge in prove.yml, and check.yml) install knos as the exact PyPI release they
name, with dependencies no newer than UV_EXCLUDE_NEWER. Before that release exists nothing can install it, so a staging
repository rehearses with --source: REQ is one requirement uv can install, such as
"git+https://github.com/drexthealpha/Knos@<commit>" or the URL of a wheel. The variant differs from the published
workflows in that requirement and in how the signing jobs get it: their list holds the third-party packages by hash
and knos is installed from REQ after it, which no hash can cover. Its README says what it is. It is for rehearsal
only: a bounty funded through it is pinned to the staging repository's commit, not to the published one.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "drexthealpha/knos-workflows"
PACKAGE = ROOT / "src"                              # what the wheel is built from: where a module a published job runs must be
WORKFLOWS = ("fund.yml", "prove.yml", "check.yml", "attest.yml")
PLACEHOLDER = "KNOS_WORKFLOWS_SHA"                  # stands for the published commit until `stamp` names it
OWN = {"knos-workflow.yml": "knos.yml", "knos-check.yml": "knos-check.yml"}     # an example, and Knos's own copy of it
CLAIM_COPY = "src/knos/settle/knos-claim.yml"                                   # what `knos claim` commits: the example
# the install step's one line that names what is installed, the same in every job
LINE = re.compile(r'^(?P<lead> +run: uv tool install [^"\n]*)"knos==(?P<release>\d+\.\d+\.\d+)"$', re.M)
SIGN = "requirements/sign.txt"                      # every third-party package a signing job installs, by hash
KNOS_LOCK = "KNOS_LOCK"                             # in a signing job's install step: where the lock is written in
HOLE = re.compile(r"^(?P<indent> +)" + KNOS_LOCK + r"$", re.M)
HEREDOC_END = re.compile(r"^(?P<indent> +)LOCK\n", re.M)         # the line after which a rehearsal installs knos from source
WHEEL = re.compile(r"knos-(?P<release>\d+\.\d+\.\d+)-py3-none-any\.whl")
REQ = re.compile(r"[A-Za-z0-9][A-Za-z0-9 @+:/._=<>~!,\[\]-]*")      # one requirement; nothing a shell or YAML would read
KNOS_LINE = re.compile(r"knos==(?P<release>\d+\.\d+\.\d+) --hash=sha256:(?P<hash>[0-9a-f]{64})")   # the lock's last line: the wheel
RAW = re.compile(re.escape(REPO) + r"/(\w+)/" + re.escape(SIGN))      # the published lock, as a file at a commit
RUNS = re.compile(r"-m (knos(?:\.\w+)+)(?: (\w+))?")    # a module of the installed release that a published job runs: `python -m knos.x cmd`
NAMED = re.compile(re.escape(REPO) + r"/\.github/workflows/([\w.-]+)@(\w+)")


def _front():
    """scripts/front_workflow.py, which holds the site's templates and knows the commit the examples name."""
    spec = importlib.util.spec_from_file_location("front_workflow", Path(__file__).with_name("front_workflow.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT, mod.FRONT = ROOT, ROOT / "web" / "front.js"       # the same tree as this script works on
    return mod


def sources() -> dict[str, str]:
    return {name: (ROOT / ".github" / "workflows" / name).read_bytes().decode("utf-8") for name in WORKFLOWS}


def release(texts: dict[str, str]) -> str:
    """The one knos release every install line of a job that signs nothing names (the signing jobs take theirs from
    the lock, which `lock` and `build` hold to this one)."""
    named = {m.group("release") for text in texts.values() for m in LINE.finditer(text)}
    lines = sum(len(re.findall(r"^ +run: uv tool install ", text, re.M)) for text in texts.values())
    if len(named) != 1 or lines != sum(len(LINE.findall(text)) for text in texts.values()):
        raise SystemExit(f"the install lines of {', '.join(WORKFLOWS)} must all name one release as \"knos==X.Y.Z\"; "
                         f"they name {sorted(named) or 'none'}")
    return named.pop()


def readme(version: str, spec: str | None) -> str:
    note = "" if spec is None else (
        "> **REHEARSAL VARIANT.** These are not the published workflows: knos is installed from\n"
        f"> `{spec}`\n"
        "> instead of the PyPI release. For a staging repository only: a bounty funded through these files is pinned\n"
        "> to this repository's commit, not to the published one.\n\n")
    installs = f"knos {version} from PyPI, as exactly that release" if spec is None else "knos from the rehearsal source named above"
    return f"""# knos-workflows

{note}The workflows that [Knos](https://github.com/drexthealpha/Knos) bounties pin by commit. A comment funds an issue,
and the pull request that closes it is paid from an escrow on Solana when GitHub itself signs the facts. A bounty on
chain names this repository and one commit of it: the commit its `fund.yml` ran at. Only `prove.yml` of this
repository at that same commit can pay it.

| File | Called for | Runs |
|---|---|---|
| `.github/workflows/fund.yml` | a `/knos` comment, or a new issue that funds itself; in an organisation's attestor repository, a run by hand or a timer | `knos command` |
| `.github/workflows/prove.yml` | a merge, a run started by hand, `/knos settle`, and the review after the check; in an attestor repository, a timer | `knos settle`, `knos review`, `knos proof judge` |
| `.github/workflows/check.yml` | every pull request (optional, read-only) | `knos check` |
| `.github/workflows/attest.yml` | a seller, by hand, after a merge: GitHub signs that a work order's terms were met; a buyer, by hand: one evaluation for `knos_meter` (kind `eval`, posted as `knos-eval:`) | `knos attest` |

Call them by a full commit sha, never by a branch or a tag. The first three take no inputs; `attest.yml` takes a
repository, a pull request, an order, a kind and optional payees, which name facts and never code. Every job installs
{installs}, so a caller cannot change which code judges.

The jobs that sign (`fund.yml`, `settle` and `attest` in `prove.yml`, and `attest.yml`) install from a list in which every file is
named by its sha256, `uv pip install --require-hashes`: that list is written into the workflow and is also
`requirements/sign.txt` here, so this commit names the hash of everything they install.

The files to copy into your repository (`knos.yml`, and optionally `knos-check.yml`; for private repositories, `knos-attestor.yml` in one
repository of the organisation) are in
[drexthealpha/Knos/examples](https://github.com/drexthealpha/Knos/tree/main/examples). Their comments say what each
trigger does and what the file can and cannot do in your repository.

Nothing is edited here. These files are copied from `.github/workflows/` in drexthealpha/Knos at a release, where they
are tested. In a checkout of that repository, `python scripts/pinned_workflows.py check <a checkout of this one>`
shows that this copy is the same, byte for byte.
"""


def rehearsal(text: str, spec: str) -> str:
    """The workflow with knos installed from `spec`: in a job that signs nothing, the requirement and nothing else; in a
    job that signs, a line after the hashed install, because no hash covers a source."""
    text = LINE.sub(lambda m: f'{m.group("lead")}"{spec}"', text)
    return HEREDOC_END.sub(lambda m: f'{m.group(0)}{m.group("indent")}uv pip install --no-config --python "$RUNNER_TEMP/knos/bin/python" --no-deps "{spec}"\n', text)


def locked() -> re.Match | None:
    """The last line of requirements/sign.txt when it names the knos wheel by hash (the release is locked), else None."""
    lines = (ROOT / SIGN).read_text(encoding="utf-8").rstrip("\n").split("\n")
    return KNOS_LINE.fullmatch(lines[-1])


def third_party() -> str:
    """requirements/sign.txt without the wheel's line: every package the signing jobs install besides knos, by hash.
    One line per line, newline last."""
    text = (ROOT / SIGN).read_text(encoding="utf-8")
    if locked():
        text = text.rstrip("\n").rpartition("\n")[0] + "\n"
    bare = [ln for ln in text.splitlines() if ln and not ln.startswith(("#", " "))]
    each = re.findall(r"^[\w.-]+==[\w.!+-]+ \\\n(?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+", text, re.M)
    if not bare or len(each) != len(bare) or not any(ln.startswith("solders==") for ln in bare):
        raise SystemExit(f"{SIGN} is not a hash-locked list (every package pinned with `==` and at least one sha256, solders among them): "
                         "compile it again with `uv pip compile requirements/sign.in --generate-hashes --python-version 3.12 --no-config -o requirements/sign.txt`")
    return text if text.endswith("\n") else text + "\n"


def lock(wheel: Path) -> str:
    """The list the pinned workflows install from: requirements/sign.txt, then this wheel by its hash. The wheel must be
    the release the workflows name, so a release cannot publish a list for another one."""
    named = WHEEL.fullmatch(wheel.name)
    if not named:
        raise SystemExit(f"{wheel.name} is not a knos wheel: it should be named knos-X.Y.Z-py3-none-any.whl")
    want = release(sources())
    if named.group("release") != want:
        raise SystemExit(f"{wheel.name} is knos {named.group('release')}, but the workflows install knos {want}: name the release "
                         f"in every \"knos=={want}\" line of {', '.join(WORKFLOWS)} before the tag")
    return third_party() + f"knos=={want} --hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}\n"


def lock_is_right(text: str) -> str:
    """The lock a release wrote, if it is requirements/sign.txt and one line for the release the workflows name."""
    head, _, last = text.rstrip("\n").rpartition("\n")
    if head + "\n" != third_party() or not re.fullmatch(re.escape(f"knos=={release(sources())} --hash=sha256:") + "[0-9a-f]{64}", last):
        raise SystemExit(f"the lock is not {SIGN} followed by one line, knos=={release(sources())} --hash=sha256:<the wheel's sha256>: "
                         "write it again with `python scripts/pinned_workflows.py lock <the wheel> --out sign.txt`")
    return text if text.endswith("\n") else text + "\n"


def written_in(text: str, locked: str) -> str:
    """The workflow with the lock where it says KNOS_LOCK, each line indented as that one is."""
    return HOLE.sub(lambda m: "\n".join(m.group("indent") + line for line in locked.rstrip("\n").split("\n")), text)


def published(lock_text: str | None = None, spec: str | None = None) -> dict[str, bytes]:
    """Every file of the published set, by its path in drexthealpha/knos-workflows: with the lock a release wrote, or
    (a rehearsal) with knos installed from `spec`."""
    texts = sources()
    version = release(texts)
    if (lock_text is None) == (spec is None):
        raise SystemExit("name the lock the release wrote (--lock FILE), or a rehearsal source (--source REQ), and not both")
    if spec is not None:
        if not REQ.fullmatch(spec) or ": " in spec or spec != spec.rstrip(" :"):
            raise SystemExit("--source takes one requirement, such as git+https://github.com/drexthealpha/Knos@<commit> "
                             "or a wheel's URL: letters, digits and @+:/._=<>~!,[]- only")
        texts = {name: rehearsal(text, spec) for name, text in texts.items()}
        locked = third_party()
    else:
        locked = lock_is_right(lock_text)
    texts = {name: written_in(text, locked) for name, text in texts.items()}
    files = {f".github/workflows/{name}": text.encode("utf-8") for name, text in texts.items()}
    files[SIGN] = locked.encode("utf-8")
    files["README.md"] = readme(version, spec).encode("utf-8")
    files["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    return files


def tree_id(files: dict[str, bytes]) -> str:
    """The id git gives the tree that holds exactly these files (all plain files, mode 100644): what `git rev-parse
    HEAD^{tree}` prints in a checkout that holds the published set and nothing else."""
    def obj(kind: bytes, body: bytes) -> bytes:
        return hashlib.sha1(kind + b" " + str(len(body)).encode() + b"\0" + body).digest()

    def tree(prefix: str) -> bytes:
        entries: dict[str, tuple[bytes, bytes]] = {}
        for rel, data in files.items():
            if not rel.startswith(prefix):
                continue
            name, _, rest = rel[len(prefix):].partition("/")
            entries[name] = (b"40000", tree(prefix + name + "/")) if rest else (b"100644", obj(b"blob", data))
        # git orders a tree's entries as if a folder's name ended in a slash
        ordered = sorted(entries.items(), key=lambda kv: (kv[0] + "/" if kv[1][0] == b"40000" else kv[0]).encode())
        return obj(b"tree", b"".join(mode + b" " + name.encode() + b"\0" + oid for name, (mode, oid) in ordered))
    return tree("").hex()


def differences(folder: Path, want: dict[str, bytes]) -> list[str]:
    """Why `folder` is not the published set, one line each: a file missing, changed, or not part of the set."""
    said = []
    for rel, data in want.items():
        path = folder / rel
        if not path.is_file():
            said.append(f"{rel} is missing")
        elif path.read_bytes() != data:
            said.append(f"{rel} is not the file this repository publishes")
    have: set[str] = set()
    for top, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if d != ".git"]      # not walked: git may be packing its loose objects there meanwhile
        have |= {(Path(top) / n).relative_to(folder).as_posix() for n in names if n != ".git" and os.path.isfile(os.path.join(top, n))}
    said += [f"{rel} is not part of the published set" for rel in sorted(have - set(want))]
    return said


# ---- the one commit everything names ---------------------------------------------------------------------------------

def _text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):       # a picture in docs/ names no commit
        return None


def naming() -> list[Path]:
    """Every file that names the published commit as plain text: the examples, Knos's own copies of them, and the
    documents. (The site's templates are written from the examples by scripts/front_workflow.py.)"""
    docs = [p for p in sorted((ROOT / "docs").rglob("*")) if p.is_file()] + [ROOT / "sdk" / "settle" / "README.md"]
    return [*sorted((ROOT / "examples").glob("*.yml")), *((ROOT / ".github" / "workflows" / own) for own in OWN.values()), *docs]


def in_the_wheel() -> list[str]:
    """Why the wheel would change with `stamp`, one line each: README.md is its description (pyproject.toml: readme),
    src/knos its content and terms/ carried in it as knos/_terms, so none may name a commit of the published workflows.
    Empty when the wheel is free of it, which is what lets it be built before that commit exists."""
    said = []
    held = [ROOT / "README.md", *(p for folder in (ROOT / "src" / "knos", ROOT / "terms") for p in sorted(folder.rglob("*"))
                                  if p.is_file() and "__pycache__" not in p.parts)]
    for path in held:
        text = _text(path) or ""
        if PLACEHOLDER in text or re.search(re.escape(REPO) + r"/(?:\.github/workflows/[\w.-]+@|)[0-9a-f]{40}", text):
            said.append(f"{path.relative_to(ROOT).as_posix()} names a commit of {REPO}, and it is part of the wheel: the wheel must be built before that commit "
                        "exists, so say it without the commit (link to examples/ instead)")
    return said


def pin() -> str:
    """The commit (or the placeholder) the examples name."""
    return _front().pin([(ROOT / "examples" / example).read_text(encoding="utf-8") for example in OWN])


def stamp(sha: str) -> list[str]:
    """Put the published commit wherever the placeholder, or the commit named before, stands. Returns what changed."""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit("stamp takes the full sha of a commit of drexthealpha/knos-workflows: 40 hex digits")
    front, old, changed = _front(), pin(), []
    for path in naming():
        text = _text(path)
        if text is not None and text.replace(old, sha) != text:
            path.write_text(text.replace(old, sha), encoding="utf-8", newline="\n")
            changed.append(path.relative_to(ROOT).as_posix())
    js = front.FRONT.read_text(encoding="utf-8")
    new = front.rewritten(js)                   # the site's templates, from the examples as they now are
    if new != js:
        front.FRONT.write_text(new, encoding="utf-8", newline="\n")
        changed.append(front.FRONT.relative_to(ROOT).as_posix())
    return changed


def modules_run() -> list[str]:
    """Why a module a published job runs with `python -m` would not run from the release it installs; [] when each is
    a file of src/knos (so of the wheel) and takes the command the job gives it. The verdict that crosses from the job
    that runs a pull request's code to the job that signs is read by such a module (knos.verdict_gate): a published
    workflow that named a module or a command the wheel does not have would sign nothing, for everyone, at once."""
    said = []
    sys.path.insert(0, str(PACKAGE))
    try:
        gate = importlib.import_module("knos.verdict_gate")
    finally:
        sys.path.pop(0)
    commands = {"knos.verdict_gate": {"emit", "check", "shape"}}
    for name, text in sorted(sources().items()):
        for module, command in sorted(set(RUNS.findall(text))):
            if not (PACKAGE / Path(*module.split("."))).with_suffix(".py").is_file():
                said.append(f".github/workflows/{name} runs `python -m {module}`, which is not a module of src/knos")
            elif command not in commands.get(module, {command}):
                said.append(f".github/workflows/{name} runs `python -m {module} {command}`, a command that module does not have")
    if not callable(getattr(gate, "main", None)) or not isinstance(getattr(gate, "SCHEMA", None), dict):
        said.append("knos.verdict_gate has no `main` to run or no SCHEMA to hold a verdict to")
    return said


def inconsistencies() -> list[str]:
    """Every place that disagrees, one line each: a copy that is not its example, a file that names another commit or
    a workflow that is not published, a placeholder left behind, site templates that are not the examples."""
    said, front = [], _front()
    for example, own in OWN.items():
        if (ROOT / "examples" / example).read_bytes() != (ROOT / ".github" / "workflows" / own).read_bytes():
            said.append(f".github/workflows/{own} is not examples/{example}: copy the example over it")
    if (ROOT / CLAIM_COPY).read_bytes() != (ROOT / "examples" / "knos-claim.yml").read_bytes():
        said.append(f"{CLAIM_COPY} is not examples/knos-claim.yml: copy the example over it")
    try:
        want = release(sources())
        named = pin()
        third_party()
    except SystemExit as why:
        return [*said, str(why)]
    said += in_the_wheel()
    said += modules_run()
    if locked() and locked().group("release") != want:
        said.append(f"{SIGN} locks the wheel of knos {locked().group('release')}, and the workflows install knos {want}: build the wheel and lock it again "
                    "(python scripts/release.py wheel, then lock)")
    if named != PLACEHOLDER and not re.fullmatch(r"[0-9a-f]{40}", named):
        said.append(f"the examples name {REPO} at {named}: a full commit sha, or {PLACEHOLDER} until the release")
    for path in [*naming(), front.FRONT]:
        text, rel = _text(path), path.relative_to(ROOT).as_posix()
        for name, ref in sorted(set(NAMED.findall(text or ""))):
            if name not in WORKFLOWS:
                said.append(f"{rel} names {name}, which {REPO} does not publish")
            elif ref != named:
                said.append(f"{rel} names {REPO} at {ref}; the examples name {named}")
        for ref in sorted(set(RAW.findall(text or ""))):        # the published lock, read at the pinned commit
            if ref != named:
                said.append(f"{rel} reads {SIGN} of {REPO} at {ref}; the examples name {named}")
        if text and named != PLACEHOLDER and path != front.FRONT and PLACEHOLDER in text:
            said.append(f"{rel} still says {PLACEHOLDER}: run python scripts/pinned_workflows.py stamp {named}")
    js = front.FRONT.read_text(encoding="utf-8")
    try:
        if front.rewritten(js) != js:
            said.append("web/front.js does not hand out examples/: run python scripts/front_workflow.py")
    except SystemExit as why:
        said.append(str(why))
    return said


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"Write, stamp and check the workflows {REPO} publishes.")
    sub = ap.add_subparsers(dest="command", required=True)
    make = sub.add_parser("lock", help=f"write {SIGN} followed by one line for this wheel and its hash: what release.yml publishes as sign.txt")
    make.add_argument("wheel", help="the knos wheel the release built, as PyPI gets it")
    make.add_argument("--out", metavar="FILE", help="write it here (default: print it)")
    make.add_argument("--write", action="store_true", help=f"write it to {SIGN} of this repository: the release is locked to this wheel")
    build = sub.add_parser("build", help="write the published set into a directory")
    build.add_argument("dir", help=f"a checkout of {REPO}, or any directory")
    build.add_argument("--lock", metavar="FILE", help=f"the list the signing jobs install from (default: {SIGN}, once `lock --write` wrote the wheel's line)")
    build.add_argument("--source", metavar="REQ", help="rehearsal variant: install knos from REQ instead of the PyPI release")
    sub.add_parser("tree", help="print the git tree id of the published set: a commit of it has this tree"
                   ).add_argument("--lock", metavar="FILE", help=f"the lock (default: {SIGN})")
    sub.add_parser("stamp", help="name the published commit in the examples, Knos's own files, the site and the documents"
                   ).add_argument("sha", help=f"the commit of {REPO} that holds the published set")
    check = sub.add_parser("check", help="exit 1 unless every file names one commit and the copies are their sources")
    check.add_argument("dir", nargs="?", help=f"also compare this checkout of {REPO} with the published set")
    check.add_argument("--lock", metavar="FILE", help=f"the checkout holds the published set made with this lock (default: {SIGN})")
    check.add_argument("--source", metavar="REQ", help="the checkout holds the rehearsal variant made with this REQ")
    a = ap.parse_args(argv)
    if a.command == "lock":
        text = lock(Path(a.wheel))
        for out in ([a.out] if a.out else []) + ([str(ROOT / SIGN)] if a.write else []):
            Path(out).write_text(text, encoding="utf-8", newline="\n")
            print(f"Wrote {out}: the third-party list and {text.splitlines()[-1]}")
        if not a.out and not a.write:
            sys.stdout.write(text)
        return 0
    if a.command == "tree":
        print(tree_id(published(_read(a.lock or _own_lock()), None)))
        return 0
    if a.command == "stamp":
        changed = stamp(a.sha)
        print(f"Named {REPO}@{a.sha} in {len(changed)} file(s)" + (": " + ", ".join(changed) if changed else "") + ".")
        return 0
    if a.command == "check":
        if (a.source or a.lock) and not a.dir:
            ap.error("--lock and --source go with the checkout to compare")
        if a.dir and a.source and a.lock:
            ap.error("name how the checkout was made: --lock FILE (the published set) or --source REQ (the rehearsal variant), not both")
        if a.dir and not a.source and not a.lock:
            a.lock = _own_lock()
        said = inconsistencies()
        what = "the rehearsal variant" if a.source else "the published set"
        if a.dir:
            wrong = differences(Path(a.dir), published(_read(a.lock), a.source))
            said += [f"{a.dir}: {line}" for line in wrong]
            if wrong:
                how = f'--source "{a.source}"' if a.source else f"--lock {a.lock}"
                said.append(f"{a.dir} is not {what}. Write it again: python scripts/pinned_workflows.py build {a.dir} {how}")
        for line in said:
            print(line)
        if not said:
            print(f"Consistent: every file names {REPO} at {pin()}" + (f", and {a.dir} is {what}, byte for byte." if a.dir else "."))
        return 1 if said else 0
    if not a.source and not a.lock:
        a.lock = _own_lock()
    want = published(_read(a.lock), a.source)
    for rel, data in want.items():
        path = Path(a.dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Wrote {'the rehearsal variant' if a.source else 'the published set'} ({len(want)} files) into {a.dir}.")
    if a.source:
        print("REHEARSAL VARIANT: for a staging repository only, never the commit a real bounty should record.")
    return 0


def _own_lock() -> str:
    """requirements/sign.txt of this repository, once it is a lock (it holds the wheel's line)."""
    if not locked():
        raise SystemExit(f"{SIGN} holds no line for the knos wheel yet, so there is nothing to publish from: build the wheel and lock it "
                         "(python scripts/release.py wheel, then python scripts/pinned_workflows.py lock dist/knos-X.Y.Z-py3-none-any.whl --write), "
                         "or name a lock with --lock FILE, or a rehearsal source with --source REQ")
    return str(ROOT / SIGN)


def _read(name: str | None) -> str | None:
    if name is None:
        return None
    try:
        return Path(name).read_text(encoding="utf-8")
    except OSError as why:
        raise SystemExit(f"cannot read the lock {name}: {why.strerror or why}") from None


if __name__ == "__main__":
    sys.exit(main())
