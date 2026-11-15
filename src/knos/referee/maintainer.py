"""The free maintainer mode of the Knos check: no money, no wallet, no chain. For maintainers drowning in AI pull
requests: label (or close, when the maintainer opts in) a pull request that edits tests, touches files outside the
issue's scope, or fails the checks.

It reads the pull request's diff and the base commit and runs NONE of the pull request's code. It decides; the
action (action.yml, input `maintainer-mode`, in the same step as the gate) applies the labels and, only in `close` mode, closes the pull request
with the job's own token. Knos's Python code never closes anything (knos.judge.github refuses such a write).
"""

from __future__ import annotations

from .. import cheats

MODES = ("off", "comment", "label", "close")
LABELS = {"test_edited": "knos: edits tests", "assertion_removed": "knos: edits tests", "out_of_scope": "knos: out of scope",
          "checks": "knos: checks failed"}
CHEAT_LABEL = "knos: cheat"
ALL_LABELS = tuple(sorted({*LABELS.values(), CHEAT_LABEL}))


def maintainer(base_dir, diff_text: str, *, scope=(), core=(), mode: str = "label", checks_passed: bool | None = None,
               record: bool = False, record_root=None, repo: str = "") -> dict:
    """{"mode", "labels", "close", "comment", "findings", "refused"}. `scope`: the issue's allowed paths (globs);
    `checks_passed`: the Knos check's result on this pull request (claims and repository rules), when the caller ran
    it (None: not run, not judged)."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} is not one of {', '.join(MODES)}")
    found = cheats.scan_diff(diff_text, base_dir=base_dir, scope=scope, core=core, claim=False)
    refusing = [f for f in found if f.severity == "refuse"]
    labels = sorted({LABELS.get(f.category, CHEAT_LABEL) for f in refusing} |
                    ({LABELS["checks"]} if checks_passed is False else set()))
    bad = bool(labels)
    closing = mode == "close" and bad
    lines = []
    if bad:
        lines.append("**Knos check (free maintainer mode):** this pull request " + ("was closed: it " if closing else "")
                     + "does not pass.")
        for f in refusing[:10]:
            lines.append(f"- `{f.rule}`{' in `' + f.path + '`' if f.path else ''}: {f.detail}")
        if checks_passed is False:
            lines.append("- the Knos check failed: the description's claims or the repository's rules (CONTRIBUTING.md) "
                         "do not hold; the job's summary says which")
        lines.append(("Fix it and open a new pull request; this one stays closed." if closing else
                      "Fix it and push again; the check runs on every push.") + " No money is involved in this mode.")
    applies = mode in ("label", "close")
    out = {"mode": mode, "labels": labels if applies else [], "close": closing,
           # Knos's own labels that no longer apply (a later push fixed the cause): the action removes them
           "remove_labels": sorted(set(ALL_LABELS) - set(labels)) if applies else [],
           "comment": "\n".join(lines) if mode != "off" else "", "refused": bad,
           "findings": [f.to_dict() for f in found]}
    if record:
        from .check import write
        try:
            write("verification", {"test": "maintainer", "passed": not bad,
                                   "cheats": sorted({f.category for f in refusing}), "mode": mode}, domain="code", root=record_root)
            for f in refusing:
                write("cheat", {"cheat": f.category, "rule": f.rule, "severity": f.severity, "mode": "maintainer"},
                      domain="code", root=record_root)
        except ValueError:
            pass
    return out
