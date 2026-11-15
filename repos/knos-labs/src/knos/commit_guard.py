"""The commit and push guard: edit-time for hook tools, commit-time for raw shell writes.

Agents whose host has an edit hook are stopped before the edit. Anything else (a script, an editor, a host with no
hook) is stopped when it tries to commit or push a file that another machine in the team has claimed. The hooks are
git's own `pre-commit` and `pre-push`, in the repo's hooks directory (core.hooksPath is respected, never changed).

Claims made from this machine never block its own commits: a person committing their agent's work is not a
collision. If the chain cannot be reached, the commit goes ahead with a one-line warning. `git commit --no-verify`
skips it, as it skips every git hook; docs/SECURITY.md says so.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MARK = "knos-guard"
_LINE = '{cmd} hook commit --stage {stage} "$@" || exit $?  # ' + MARK


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, input=stdin, timeout=30)
    return done.stdout if done.returncode == 0 else ""


def hooks_dir(repo: Path) -> Path:
    got = _git(repo, "rev-parse", "--git-path", "hooks").strip()
    p = Path(got) if got else Path(".git") / "hooks"
    return p if p.is_absolute() else Path(repo) / p


def staged(repo: Path) -> list[str]:
    return [line for line in _git(repo, "diff", "--cached", "--name-only", "-z").split("\0") if line]


def pushed(repo: Path, stdin_text: str) -> list[str]:
    """Files changed by the commits a push sends (pre-push gets '<local ref> <local sha> <remote ref> <remote sha>')."""
    out: list[str] = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {"0"}:
            continue
        local, remote = parts[1], parts[3]
        rng = [local, "--not", "--remotes"] if set(remote) == {"0"} else [f"{remote}..{local}"]
        names = _git(repo, "log", "--name-only", "--format=", *rng)
        out.extend(n for n in names.splitlines() if n.strip())
    return list(dict.fromkeys(out))


def refusals(repo: Path, rels: list[str]) -> tuple[list[str], str]:
    """(one line per file another machine has claimed, a warning if the team could not be checked)."""
    if not rels or not (Path(repo) / ".knos" / "team.json").exists():
        return [], ""
    try:
        from .team import live, units
    except ImportError:
        return [], "team check skipped: knos's Solana extras are missing (Knos)"
    try:
        rt = live.runtime(repo)
        if rt is None:
            return [], "this machine has not joined the team: commits are not checked (Knos)"
        try:
            live.sync(rt, timeout=5.0)
        except Exception:  # noqa: BLE001
            return [], "team registry unreachable: commit not checked against other machines' claims (Knos)"
        conn = rt.db()
        try:
            now = live._chain_now(conn)
            rows = conn.execute("SELECT address, unit_hash, ancestors, holder, signer, lease_until, kind, since "
                                "FROM claims").fetchall()
            mine = {r[0] for r in conn.execute("SELECT address FROM mine")}
        finally:
            conn.close()
        theirs = [r for r in rows if r[0] not in mine and r[5] > now]
        out = []
        for rel in rels:
            unit = units.unit(rel)
            uh = units.unit_hash(rt.salt, rt.tf.repo_id, unit)
            anc = units.ancestors(rt.salt, rt.tf.repo_id, unit)
            hit = next((r for r in theirs if units.overlaps(r[1], r[2], uh, anc)), None)
            if hit is not None:
                out.append(live.refusal(rt, rel, hit[4], hit[3], hit[7]))
        return out, ""
    except Exception as exc:  # noqa: BLE001 - never stand between a person and their own commit on a bug
        return [], f"team check failed ({type(exc).__name__}); commit not checked (Knos)"


def run(stage: str, repo: Path, stdin_text: str = "") -> int:
    rels = staged(repo) if stage == "commit" else pushed(repo, stdin_text)
    lines, warning = refusals(repo, rels)
    if warning:
        print(f"knos: {warning}", file=sys.stderr)
    if not lines:
        return 0
    for line in lines:
        print(f"knos: {line}", file=sys.stderr)
    print("knos: the commit was stopped. Ask the holder, or unstage those files. "
          "(git's --no-verify skips this check and is recorded nowhere.)", file=sys.stderr)
    return 1


# ---- installing -----------------------------------------------------------------------------------------------------

def _cmd() -> str:
    from .guard import knos_cmd
    return " ".join(knos_cmd())


def install(repo: Path) -> list[Path]:
    """Add the knos line to pre-commit and pre-push; an existing hook keeps its own lines and runs them after."""
    d = hooks_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    done = []
    for name, stage in (("pre-commit", "commit"), ("pre-push", "push")):
        p = d / name
        line = _LINE.format(cmd=_cmd(), stage=stage)
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if MARK in text:
                continue
            first, _, rest = text.partition("\n")
            text = (first + "\n" + line + "\n" + rest) if first.startswith("#!") else (line + "\n" + text)
        else:
            text = "#!/bin/sh\n" + line + "\n"
        p.write_text(text, encoding="utf-8", newline="\n")
        try:
            p.chmod(0o755)
        except OSError:
            pass
        done.append(p)
    return done


def uninstall(repo: Path) -> list[Path]:
    d = hooks_dir(repo)
    done = []
    for name in ("pre-commit", "pre-push"):
        p = d / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        if MARK not in text:
            continue
        kept = [ln for ln in text.split("\n") if MARK not in ln]
        if kept in (["#!/bin/sh", ""], ["#!/bin/sh"]):
            p.unlink()
        else:
            p.write_text("\n".join(kept), encoding="utf-8", newline="\n")
        done.append(p)
    return done


def installed(repo: Path) -> bool:
    p = hooks_dir(repo) / "pre-commit"
    try:
        return MARK in p.read_text(encoding="utf-8")
    except OSError:
        return False
