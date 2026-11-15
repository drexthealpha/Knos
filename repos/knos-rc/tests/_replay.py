"""Replay a repo's releases through the proof engine, with and without its Sibyl history.

Each release is announced the same way an agent announces one ("Knos X is shipped: tagged, on PyPI, tests pass").
The claim never mentions CI, so a hook without memory checks only what it says. Knos's history holds an earlier
false "done" (a release whose CI then failed); learn() made CI a required check for release claims, so Knos runs it
for every later release. After each release its real CI outcome is observed and learned from, as in use.

    with_sibyl(store, evidence)   Knos: Sibyl history + all checks
    null_baseline(evidence)       a NullStore and local pytest only
"""

from __future__ import annotations

from pathlib import Path

from knos.proof import checks, engine, history

CLAIM = "Knos {version} is shipped: tagged, on PyPI, tests pass."


def _runners(rel: dict, tests_only: bool = False) -> dict:
    ok_tests = rel["local_pytest"] == "passed"
    run = {"tests": lambda repo, claim, cfg: checks.Result("tests", ok_tests, f"local pytest {rel['local_pytest']}"),
           "pypi": lambda repo, claim, cfg: checks.Result("pypi", True, f"knos {rel['version']} on PyPI"),
           "author": lambda repo, claim, cfg: checks.Result("author", True, "drexthealpha, no AI trailers"),
           "ci": lambda repo, claim, cfg: checks.Result("ci", rel["ci"] == "success",
                                                        f"CI at {rel['sha']}: {rel['ci']}", {"sha": rel["sha"]})}
    if tests_only:
        return {k: v for k, v in run.items() if k == "tests"} | {
            k: (lambda repo, claim, cfg, k=k: checks.Result(k, True, "not checked by a local-pytest hook"))
            for k in ("pypi", "author", "ci")}
    return run


def seed(store, past: list[dict]) -> None:
    """The repo's history before the replay: each past release, claimed done, then its real CI outcome."""
    for rel in past:
        history.record(store, rel["sha"], CLAIM.format(**rel), ["release", "pypi", "tests"],
                       [{"name": "tests", "ok": True, "detail": "local pytest"}], True)
        history.observe(store, rel["sha"], "ci", rel["ci"] == "success")
    history.learn(store)


def with_sibyl(store, releases: list[dict], repo: Path) -> list[tuple[str, bool, str]]:
    out = []
    for rel in releases:
        v = engine.evaluate(repo, CLAIM.format(**rel), store, _runners(rel), use_cache=False)
        out.append((rel["version"], v.ok, "; ".join(r.detail for r in v.results if not r.ok) or "proven"))
        history.observe(store, rel["sha"], "ci", rel["ci"] == "success")
        history.learn(store)
    return out


def null_baseline(releases: list[dict], repo: Path) -> list[tuple[str, bool, str]]:
    out = []
    for rel in releases:
        v = engine.evaluate(repo, CLAIM.format(**rel), history.NullStore(), _runners(rel, tests_only=True),
                            use_cache=False)
        out.append((rel["version"], v.ok, "; ".join(r.detail for r in v.results if r.name == "tests")))
    return out
