"""The verdict: Works and Wanted and Makeable, all three, or no. And the referee as a reward for agents in training:
the same checks, one number."""

from __future__ import annotations

from .check import Check, write


def verdict(works: Check, wanted: Check, makeable: Check, *, spec_hash: str, domain: str = "", record_root=None,
            record: bool = True, claim: str | None = None) -> dict:
    """{"passed", "spec_hash", "checks": {works, wanted, makeable}, "failed": [names], "recorded"}. With `record`, one
    "verdict" entry and one "cheat" entry per cheat caught go to Knos Record (when this install has it)."""
    checks = {"works": works, "wanted": wanted, "makeable": makeable}
    for name, c in checks.items():
        if c.name != name:
            raise ValueError(f"the {name} slot holds a {c.name} check")
    failed = [n for n, c in checks.items() if not c.passed]
    out = {"passed": not failed, "spec_hash": spec_hash, "failed": failed, "checks": {n: c.to_dict() for n, c in checks.items()},
           "recorded": False}
    if record:
        try:
            got = write("verdict", {"spec_hash": spec_hash, "passed": out["passed"], "failed": failed,
                                    "works": works.passed, "wanted": wanted.passed, "makeable": makeable.passed,
                                    "cheats": sorted({f.category for f in works.cheats})},
                        domain=domain, root=record_root, claim=claim)
            for f in works.cheats:
                write("cheat", {"spec_hash": spec_hash, "cheat": f.category, "rule": f.rule, "severity": f.severity},
                      domain=domain, root=record_root, claim=claim)
            out["recorded"] = got is not None
        except ValueError as why:
            out["recorded"] = f"refused by Knos Record: {why}"
    return out


def redact_hidden(reasons) -> list[str]:
    """Reasons as a worker may read them: what a sealed suite printed (its inputs, its answers) is cut, the rule and
    the pass/fail stay."""
    import re
    out = []
    for r in reasons:
        r = re.sub(r"\s*\(the suite's last words:.*$", " (sealed: details withheld)", str(r), flags=re.S)
        out.append(r)
    return out


def reward(check: Check) -> float:
    """1.0 for work that passed, 0.0 for work that failed honestly, -1.0 for work a cheat rule refused: an evolving
    agent must never find cheating better than failing."""
    if any(f.severity == "refuse" for f in check.cheats):
        return -1.0
    return 1.0 if check.passed else 0.0


def judge_candidate(base_dir, pr_dir, seal: dict, **kw) -> dict:
    """One candidate (a skill's or agent's output tree) through Works: {"reward", "passed", "reasons", "cheats"}.
    The candidate sees this dict: pass/fail and rule names, never the sealed tests' contents."""
    from .works import works
    c = works(base_dir, pr_dir, seal, **kw)
    return {"reward": reward(c), "passed": c.passed, "reasons": redact_hidden(c.reasons),
            "cheats": [{"rule": f.rule, "category": f.category} for f in c.cheats]}
