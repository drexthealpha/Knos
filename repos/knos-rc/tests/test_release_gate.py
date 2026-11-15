"""Nothing is published unless the whole test workflow passed on that exact commit: release.yml runs tests.yml on the
tagged commit and every publishing job needs that job. One mechanism, and no other workflow publishes a release."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# Every way a workflow can publish something outside the repository, and the one place each is allowed.
PUBLISHES = {
    r"\buv publish\b|\btwine upload\b|pypa/gh-action-pypi-publish": set(),      # no workflow uploads to PyPI: scripts/release.py does, before the push
    r"\bnpm publish\b|\bcargo publish\b": {"release.yml"},
    r"\bmcp-publisher publish\b": {"release.yml"},
    r"\bgh release (create|upload)\b": {"release.yml", "index.yml"},     # index.yml: the index-<date> data release
    r"actions/deploy-pages@": {"network.yml"},                           # the site, not a release
}


def _yaml(name: str) -> dict:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))   # YAML 1.1 reads the key `on` as True
    return doc


def _needs(job: dict) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def test_a_release_runs_the_whole_test_workflow_on_the_tagged_commit_before_anything_is_published():
    rel, tests = _yaml("release.yml"), _yaml("tests.yml")
    # a tag starts it (or the same run again, by hand, for a tag); publishing a release by hand starts nothing
    assert set(rel["on"]) == {"push", "workflow_dispatch"} and rel["on"]["push"] == {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}
    assert rel["permissions"] == {}
    gate = rel["jobs"]["tests"]
    assert gate["uses"] == "./.github/workflows/tests.yml"         # this commit's own tests.yml, on this commit
    assert gate["if"] == "github.ref_type == 'tag'" and "needs" not in gate
    assert "workflow_call" in tests["on"]
    # the whole workflow: no job of tests.yml is skipped when it is called from a release
    assert not [name for name, job in tests["jobs"].items() if "if" in job and name != "all-green"]
    assert set(tests["jobs"]) >= {"pytest", "sdk", "claims", "deadcode"}
    oses = {m["os"] for m in tests["jobs"]["pytest"]["strategy"]["matrix"]["include"]}
    assert oses == {"ubuntu-latest", "macos-latest", "windows-latest"}
    # the caller and the called workflow must not share a concurrency group (GitHub cancels the run if they do)
    assert rel["concurrency"]["group"].startswith("release-") and tests["concurrency"]["group"].startswith("tests-")
    assert "github.workflow" not in tests["concurrency"]["group"]


def test_the_lint_job_runs_ruff_and_mypy_at_pinned_versions_and_pyproject_lists_what_it_leaves_out():
    """tests.yml's lint job is part of the gate (no condition, nothing to wait for), inside the 5-minute budget, and runs
    the two tools at one version each. What they skip is written in pyproject.toml and is still true: every module it
    leaves to mypy's silence is a file that exists."""
    try:
        import tomllib
    except ModuleNotFoundError:   # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    job = _yaml("tests.yml")["jobs"]["lint"]
    assert "if" not in job and "needs" not in job and job["timeout-minutes"] <= 5
    runs = [str(step["run"]) for step in job["steps"] if "run" in step]
    install = next(r for r in runs if r.startswith("uv pip install"))
    assert re.findall(r"\b(ruff|mypy)==\d+\.\d+\.\d+\b", install) == ["ruff", "mypy"]
    assert " -e . " in install + " "              # the package is installed: mypy reads the types of what it imports
    assert [r for r in runs if r != install] == ["ruff check .", "mypy"]
    assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"].split(" ")[0]) for step in job["steps"] if "uses" in step)
    tool = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]
    assert tool["ruff"]["lint"]["select"] == ["E4", "E7", "E9", "F"] and tool["ruff"]["lint"]["ignore"] == ["E702"]
    assert tool["mypy"]["files"] == ["src/knos"] and tool["mypy"]["ignore_missing_imports"] is True
    for skipped in tool["mypy"].get("overrides", []):        # none since 0.3.21: the relay package is under mypy too
        assert skipped["ignore_errors"] is True and len(skipped["module"]) == len(set(skipped["module"]))
        for module in skipped["module"]:
            base = ROOT / "src" / Path(*module.split("."))
            assert base.with_suffix(".py").is_file() or (base / "__init__.py").is_file(), f"{module} is gone: take it off the list"


def test_every_publishing_job_needs_the_gate_and_none_can_run_when_it_did_not_pass():
    rel = _yaml("release.yml")
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    jobs = {name: job for name, job in rel["jobs"].items() if name != "tests"}
    assert set(jobs) >= {"build", "pypi", "github-release", "registry", "site"}
    for name, job in jobs.items():                                  # every job, whatever it publishes and whoever adds it
        assert "tests" in _needs(job), f"{name} does not need the tests"
        # a job with needs runs only when they all succeeded, unless its own `if` says otherwise
        assert "if" not in job and "continue-on-error" not in json.dumps(job), name
        # PyPI first: nothing else leaves unless PyPI took the release
        assert name in ("build", "pypi") or {"pypi", "github-release"} & set(_needs(job)), name
    # a tag starts the run, so there is no release event: a job that waited for one or read its payload would never run
    assert "github.event" not in "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    # the only secrets are the two registry tokens: no workflow holds a way into PyPI (the MCP registry takes this run's OIDC token)
    assert sorted(re.findall(r"secrets\.(\w+)", text)) == ["CARGO_REGISTRY_TOKEN", "NPM_TOKEN"]
    # PyPI: nothing is uploaded. The job reads the lock from the commit and holds what PyPI serves to it
    pypi = jobs["pypi"]
    assert pypi["permissions"] == {"contents": "read"} and "environment" not in pypi
    run = "\n".join(str(s.get("run", "")) for s in pypi["steps"])
    assert "python3 scripts/release.py pypi-check --dist dist" in run and "publish" not in run and "upload" not in run
    # what is attached was built from the tagged commit, with the tag as its version, and is the locked wheel or the job fails
    build = "\n".join(str(s.get("run", "")) for s in jobs["build"]["steps"])
    assert 'version="${GITHUB_REF_NAME#v}"' in build and build.count('= "$version"') == 4
    assert "python3 scripts/release.py wheel --check" in build and "uv build" not in build and "pinned_workflows.py lock" not in build
    assert _needs(jobs["github-release"]) == ["tests", "build", "pypi"] and _needs(jobs["registry"]) == ["tests", "pypi"]
    assert jobs["github-release"]["permissions"] == {"contents": "write"}
    assert jobs["registry"]["permissions"] == {"contents": "read", "id-token": "write"}


def test_no_other_workflow_publishes_a_release():
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        text = "\n".join(ln for ln in wf.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
        for pattern, allowed in PUBLISHES.items():
            if re.search(pattern, text):
                assert wf.name in allowed, f"{wf.name} publishes ({pattern}) outside the release gate"
    # the Pages build is no longer started by a release being published: release.yml starts it, after the gate
    net = _yaml("network.yml")
    assert "release" not in net["on"] and "workflow_dispatch" in net["on"]
    site = _yaml("release.yml")["jobs"]["site"]
    assert "gh workflow run network.yml" in site["steps"][0]["run"] and site["permissions"] == {"actions": "write"}


# ---- PyPI: the wheel is there before the tag, and it is the locked one ----------------------------------------------------

def _release_script():
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_script", ROOT / "scripts" / "release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path: Path, last: str) -> Path:
    (tmp_path / "requirements").mkdir(parents=True)
    (tmp_path / "requirements" / "sign.txt").write_text("solders==0.29.0 \\\n    --hash=sha256:" + "0" * 64 + "\n" + last, encoding="utf-8")
    return tmp_path


def test_the_release_fails_loudly_unless_pypi_serves_the_wheel_with_exactly_the_locked_hash(tmp_path):
    r = _release_script()
    want, other = "a" * 64, "b" * 64
    root = _tree(tmp_path, "knos" + f"==9.8.7 --hash=sha256:{want}\n")           # in two parts: this file is read for version pins too
    wheel = "knos-9.8.7-py3-none-any.whl"
    asked = []

    def pypi(files):
        def fetch(url: str):
            asked.append(url)
            return None if files is None else json.dumps({"urls": [{"filename": n, "digests": {"sha256": h}} for n, h in files.items()]}).encode()
        return fetch
    ok, said = r.pypi_check(fetch=pypi({wheel: want, "knos-9.8.7.tar.gz": other}), root=root)
    assert ok and said == f"PyPI serves {wheel} with the locked sha256 {want}." and asked == ["https://pypi.org/pypi/knos/9.8.7/json"]
    # another file under the same name: the release stops, and says that the file cannot be replaced
    ok, said = r.pypi_check(fetch=pypi({wheel: other}), root=root)
    assert not ok and f"PyPI serves {wheel} with sha256 {other}, and this commit locks {want}" in said and "DIFFERENT" in said and "release a new version" in said
    # not there (the version is unknown, or it has only an sdist): it is never uploaded from the workflow
    for files in (None, {"knos-9.8.7.tar.gz": want}):
        ok, said = r.pypi_check(fetch=pypi(files), root=root)
        assert not ok and f"PyPI does not serve {wheel}" in said and "BEFORE the push" in said and "never uploads a wheel" in said
    # it waits for PyPI to show a release that was just uploaded, then reads it
    seen = iter([None, None, {wheel: want}])
    naps = []
    ok, _said = r.pypi_check(wait=120, fetch=lambda url: None if (f := next(seen)) is None else pypi(f)(url), sleep=naps.append, root=root)
    assert ok and naps == [20, 20]
    # the artifact of this run's build must be that file too
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / wheel).write_bytes(b"not it")
    ok, said = r.pypi_check(dist=dist, fetch=pypi({wheel: want}), root=root)
    assert not ok and "is not the locked wheel" in said
    # a commit that locks nothing has nothing to hold PyPI to
    bare = _tree(tmp_path / "bare", "")
    ok, said = r.pypi_check(fetch=pypi({wheel: want}), root=bare)
    assert not ok and "locks no release" in said and r.lock_hash(bare) is None and r.lock_hash(root) == ("9.8.7", want)


def test_publish_uploads_only_the_locked_wheel_this_tree_builds_with_a_token_from_the_environment():
    """`publish` runs before the one commit (the cutoff is written from PyPI's time), so it holds the tree to the lock by
    building the wheel again: the same bytes as the locked hash, or nothing is uploaded."""
    text = (ROOT / "scripts" / "release.py").read_text(encoding="utf-8")
    body = text[text.index("def publish_cmd"):text.index("def main")]
    order = ["is not the locked wheel", "build(Path(tmp))", "if got != want", "changed after the lock", "on_pypi(version)", "UV_PUBLISH_TOKEN", '"uv", "publish"', "pypi_check(wait=300)"]
    assert [body.index(x) for x in order] == sorted(body.index(x) for x in order)
    assert "--check-url" in body and "print(os.environ" not in text and "UV_PUBLISH_TOKEN\"]" not in text      # the token is read by uv, never by this script
    r = _release_script()
    assert r.EPOCH == 1767225600 and r.BUILD == "requirements/build.txt"
    build = (ROOT / "requirements" / "build.txt").read_text(encoding="utf-8")
    pinned = re.search(r'^requires = \["hatchling==([\d.]+)"\]', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    assert f"hatchling=={pinned} \\\n    --hash=sha256:" in build
    assert all("--hash=sha256:" in block for block in re.split(r"\n(?=[a-z])", build) if re.match(r"[a-z][\w.-]*==", block))


# ---- crates.io and npm: a package is published at its own version -----------------------------------------------------------

def _crate(root: Path, name: str, version: str) -> None:
    (root / "crates" / name).mkdir(parents=True, exist_ok=True)
    (root / "crates" / name / "Cargo.toml").write_text(f'[package]\nname = "{name}"\nversion = "{version}"\nedition = "2021"\n', encoding="utf-8")


def _index(versions: list[str] | None, asked: list[str] | None = None):
    """crates.io's index for one crate: a JSON line per version; None: no such crate (404)."""
    def fetch(url: str):
        if asked is not None:
            asked.append(url)
        return None if versions is None else "".join(json.dumps({"name": "x", "vers": v, "yanked": False}) + "\n" for v in versions).encode()
    return fetch


def test_a_crate_held_at_an_older_version_is_a_green_skip_and_a_version_that_is_neither_is_red(tmp_path):
    """0.3.15: crates-trusted compared the interface crates' version with the tag. They are held at 0.3.14 on purpose
    (a version is in a build's bytes), so the job could never pass. The rule: a crate is published at its own version,
    which is the tag's or the one it is held at; only a version the registry lacks is published."""
    r = _release_script()
    name, asked = "knos-oidc-interface", []
    _crate(tmp_path, name, "0.3.14")
    # held at 0.3.14, release 0.3.15, the crate not on crates.io yet: green, one notice, nothing to publish
    code, said, publish = r.registry_plan("crates", name, "v0.3.15", "0.3.14", fetch=_index(None, asked), root=tmp_path)
    assert (code, publish) == (0, False) and said.startswith("::notice title=crates.io::Skipped: knos-oidc-interface is not on crates.io yet")
    assert "is published by hand (docs/reference/RELEASE.md)" in said and "held at 0.3.14" in said and "published at its own version" in said
    assert asked == ["https://index.crates.io/kn/os/knos-oidc-interface"]
    # held, and crates.io has that version already: green, a notice, nothing to publish
    code, said, publish = r.registry_plan("crates", name, "v0.3.15", "0.3.14", fetch=_index(["0.3.13", "0.3.14"]), root=tmp_path)
    assert (code, publish) == (0, False) and said.startswith("::notice ") and "already has knos-oidc-interface 0.3.14" in said
    # held, on crates.io, without this version: it is published at ITS version, not the tag's
    code, said, publish = r.registry_plan("crates", name, "v0.3.15", "0.3.14", fetch=_index(["0.3.13"]), root=tmp_path)
    assert (code, publish) == (0, True) and "publishing knos-oidc-interface 0.3.14" in said
    # neither the tag's version nor the held one: red, and the registry is not even asked
    asked.clear()
    _crate(tmp_path, name, "0.3.13")
    code, said, publish = r.registry_plan("crates", name, "v0.3.15", "0.3.14", fetch=_index(["0.3.13"], asked), root=tmp_path)
    assert (code, publish) == (1, False) and said.startswith("::error title=crates.io::") and asked == []
    assert "neither the tag's version (v0.3.15) nor the 0.3.14 that scripts/bump_version.py holds it at" in said and "Nothing is published" in said
    # a crate nothing holds must carry the tag's version: an older one is red, the tag's is published once
    code, said, publish = r.registry_plan("crates", name, "v0.3.15", None, fetch=_index([]), root=tmp_path)
    assert (code, publish) == (1, False) and "It is not held at an earlier version" in said
    _crate(tmp_path, name, "0.3.15")
    assert r.registry_plan("crates", name, "v0.3.15", None, fetch=_index(["0.3.14"]), root=tmp_path)[::2] == (0, True)
    assert r.registry_plan("crates", name, "v0.3.15", None, fetch=_index(["0.3.14", "0.3.15"]), root=tmp_path)[::2] == (0, False)
    assert r.registry_plan("crates", name, "v0.3.15", "0.3.14", fetch=_index(["0.3.14"]), root=tmp_path)[::2] == (0, True)   # held elsewhere, moved on here: the tag's
    # a registry that does not answer is red and says to run the job again: nothing is published on a guess

    def down(url: str):
        raise OSError("timed out")
    code, said, publish = r.registry_plan("crates", name, "v0.3.15", None, fetch=down, root=tmp_path)
    assert (code, publish) == (1, False) and "did not answer" in said and "run this job again" in said
    # the folder of crates.io's index is made of the name's first letters
    for crate, where in (("a", "1/a"), ("ab", "2/ab"), ("abc", "3/a/abc"), ("knos-pay-interface", "kn/os/knos-pay-interface")):
        asked.clear()
        r.on_registry("crates", crate, _index(None, asked))
        assert asked == [f"https://index.crates.io/{where}"]


def test_the_npm_package_follows_the_same_rule_and_its_version_is_always_the_tags(tmp_path):
    r = _release_script()
    (tmp_path / "sdk" / "settle").mkdir(parents=True)
    (tmp_path / "sdk" / "settle" / "package.json").write_text(json.dumps({"name": "knos-settle", "version": "0.3.15"}), encoding="utf-8")

    def npm(versions):
        return lambda url: None if versions is None else json.dumps({"name": "knos-settle", "versions": {v: {} for v in versions}}).encode()
    code, said, publish = r.registry_plan("npm", "knos-settle", "v0.3.15", None, fetch=npm(None), root=tmp_path)
    assert (code, publish) == (0, False) and said.startswith("::notice title=npm::Skipped: knos-settle is not on npm yet") and "by hand (docs/reference/RELEASE.md)" in said
    assert r.registry_plan("npm", "knos-settle", "v0.3.15", None, fetch=npm(["0.3.14"]), root=tmp_path)[::2] == (0, True)
    assert r.registry_plan("npm", "knos-settle", "v0.3.15", None, fetch=npm(["0.3.15"]), root=tmp_path)[::2] == (0, False)
    code, said, publish = r.registry_plan("npm", "knos-settle", "v0.3.16", None, fetch=npm(["0.3.15"]), root=tmp_path)
    assert (code, publish) == (1, False) and said.startswith("::error title=npm::knos-settle is at 0.3.15, and the tag is v0.3.16")


def test_what_is_held_comes_from_bump_version_alone_and_this_trees_packages_pass_the_rule():
    """One source: scripts/bump_version.py (PROGRAMS_FROZEN, FROZEN_AT). Whatever it holds, each package of this tree is
    at a version its release may publish, so no publishing job of the release this commit becomes is red by its rule."""
    r = _release_script()
    bump = r._load("bump_version")
    tag = f"v{bump.project()}"
    for crate in ("knos-oidc-interface", "knos-pay-interface"):
        assert r.held(crate) == (bump.FROZEN_AT if crate in bump.PROGRAMS_FROZEN else None)
        assert r.version_rule(crate, r.own_version("crates", crate), tag, r.held(crate)) is None, crate
    assert r.held("knos-settle") is None and r.version_rule("knos-settle", r.own_version("npm", "knos-settle"), tag, None) is None
    assert "PROGRAMS_FROZEN" not in (WORKFLOWS / "release.yml").read_text(encoding="utf-8").replace("#", "\n#").split("\n  tests:")[1]     # no second list


def test_the_publishing_jobs_ask_the_one_rule_and_none_compares_a_held_crate_with_the_tag(tmp_path, monkeypatch, capsys):
    jobs = _yaml("release.yml")["jobs"]

    def plan(job: str) -> str:
        [step] = [s for s in jobs[job]["steps"] if s.get("id") == "plan"]
        return step["run"]
    crates, npm = plan("crates-trusted"), plan("npm-trusted")
    assert 'python3 scripts/release.py registry-plan crates "$CRATE" --tag "$TAG"' in crates
    assert 'python3 scripts/release.py registry-plan npm knos-settle --tag "$TAG"' in npm
    for run in (crates, npm):
        assert '= "$TAG"' not in run and "cargo metadata" not in run       # the comparison that a held crate can never pass is gone
    for job in ("crates-trusted", "npm-trusted"):                          # and a publish still happens only on the plan's word
        later = [s for s in jobs[job]["steps"] if "publish" in str(s.get("run", "")) and s.get("id") != "plan"]
        assert later and all(s["if"] == "steps.plan.outputs.publish == 'true'" for s in later), job
    # the token job (the fallback, dormant while the secret is unset) holds each crate to the same two versions
    token = "\n".join(str(s.get("run", "")) for s in jobs["crates"]["steps"])
    for crate in ("knos-oidc-interface", "knos-pay-interface"):
        assert f'[ "$version" = "$(python3 ../../scripts/release.py held {crate})" ] || test "v$version" = "$TAG"' in token
    # the command writes the plan where the next steps read it: publish=true only when there is something to publish
    r = _release_script()
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(r, "registry_plan", lambda *a, **k: (0, "said", True))
    assert r.main(["registry-plan", "crates", "knos-oidc-interface", "--tag", "v9.9.9"]) == 0
    assert out.read_text(encoding="utf-8").splitlines() == [f"version={r.own_version('crates', 'knos-oidc-interface')}", "publish=true"]
    out.write_text("", encoding="utf-8")
    monkeypatch.setattr(r, "registry_plan", lambda *a, **k: (1, "::error::no", False))
    assert r.main(["registry-plan", "crates", "knos-oidc-interface", "--tag", "v9.9.9"]) == 1 and out.read_text(encoding="utf-8") == ""
    assert capsys.readouterr().out.splitlines() == ["said", "::error::no"]


# ---- PyPI's index lags an upload: the push waits for it, and the worker's install waits for that one error ---------------------

def test_publish_says_push_only_once_the_index_an_installer_reads_lists_the_locked_wheel(tmp_path):
    r = _release_script()
    want = "a" * 64
    root = _tree(tmp_path, "knos" + f"==9.8.7 --hash=sha256:{want}\n")
    wheel = "knos-9.8.7-py3-none-any.whl"

    def index(files: dict):
        return json.dumps({"name": "knos", "files": [{"filename": n, "hashes": {"sha256": h}} for n, h in files.items()]}).encode()
    old = {"knos-9.8.6-py3-none-any.whl": "c" * 64}
    asked, naps = [], []
    pages = iter([index(old), index(old), index({**old, wheel: want})])
    ok, said = r.index_check(wait=600, fetch=lambda url: asked.append(url) or next(pages), sleep=naps.append, root=root)
    assert ok and naps == [20, 20] and set(asked) == {"https://pypi.org/simple/knos/"} and "PyPI's index lists" in said
    # bounded: it asks for the time it was given and no longer, then says not to push
    naps.clear()
    ok, said = r.index_check(wait=600, fetch=lambda url: index(old), sleep=naps.append, root=root)
    assert not ok and sum(naps) == 600 and len(naps) == 30 and "Do NOT push yet" in said and "after 600 seconds" in said
    naps.clear()
    assert not r.index_check(fetch=lambda url: index(old), sleep=naps.append, root=root)[0] and naps == []           # no wait asked: asked once
    # another file under that name is never waited for
    ok, said = r.index_check(wait=600, fetch=lambda url: index({wheel: "b" * 64}), sleep=naps.append, root=root)
    assert not ok and naps == [] and "DIFFERENT" in said
    # `publish` ends with it, after PyPI took the upload; and the release's own check asks the index too
    text = (ROOT / "scripts" / "release.py").read_text(encoding="utf-8")
    body = text[text.index("def publish_cmd"):text.index("def main")]
    assert body.index("pypi_check(wait=300)") < body.index("index_check(wait=600)") < body.index("Next: python scripts/pinned_workflows.py cutoff")
    assert body.count("Next:") == 1 and "git push" not in body and "return _pushable() if ok else 1" in body
    assert "not committed" not in body and "does not hold this lock" not in body
    assert "ok, said = index_check(wait=a.wait)" in text[text.index("def main"):]


def _worker_install() -> str:
    [step] = [s for s in _yaml("worker.yml")["jobs"]["relay"]["steps"] if "requirements/sign.txt" in str(s.get("run", ""))]
    return step["run"]


def test_the_workers_install_waits_only_for_the_index_to_list_the_release_and_for_ten_minutes_at_most(tmp_path):
    """The first worker run after 0.3.15 was pushed failed on "no version of" the knos release it asked for (PyPI's index was minutes
    behind the upload), and a run that fails starts no next run. The step now waits for that error alone, 195 s in all (since 0.3.21,
    inside a 6-minute step timeout: a run that stays stuck is replaced by the watchdog, tests/test_worker_chain.py)."""
    import os
    import subprocess

    import _posix
    run = _worker_install()
    assert "for nap in 15 30 60 90 end; do" in run and sum((15, 30, 60, 90)) == 195
    assert run.count("uv pip install ") == 1 and run.count("sleep ") == 1 and "while" not in run and "until" not in run     # no loop without an end
    assert _yaml("worker.yml")["jobs"]["relay"]["timeout-minutes"] >= 15                                # the wait and the 5 minutes of relaying fit
    if os.name == "nt":
        pytest.skip("runs the step with stand-ins for uv and sleep on a POSIX shell")
    bash = _posix.bash()
    fake = tmp_path / "bin"
    fake.mkdir()
    # uv: `venv` does nothing; `pip install` fails with the next line of $ANSWERS on stderr until that file is empty
    (fake / "uv").write_text('#!/bin/sh\n[ "$1" = venv ] && exit 0\necho x >> "$LOG/tries"\nsaid=$(head -n 1 "$ANSWERS")\n[ -n "$said" ] || exit 0\n'
                             'tail -n +2 "$ANSWERS" > "$ANSWERS.next"; mv "$ANSWERS.next" "$ANSWERS"\necho "$said" >&2\nexit 1\n', encoding="utf-8")
    (fake / "sleep").write_text('#!/bin/sh\necho "$1" >> "$LOG/naps"\n', encoding="utf-8")
    for tool in ("uv", "sleep"):
        (fake / tool).chmod(0o755)
    pin = "knos" + "==9.8.7"                                           # in two parts: this file is read for version pins too
    lag = f"  x No solution found when resolving dependencies: Because there is no version of {pin} and you require {pin}, we can conclude"

    def go(answers: list[str], last: str = "knos" + "==9.8.7 --hash=sha256:" + "a" * 64 + "\n"):
        work = tmp_path / f"run-{len(list(tmp_path.iterdir()))}"
        (work / "requirements").mkdir(parents=True)
        (work / "requirements" / "sign.txt").write_text("solders==0.29.0 \\\n    --hash=sha256:" + "0" * 64 + "\n" + last, encoding="utf-8")
        (work / "answers").write_text("".join(a + "\n" for a in answers), encoding="utf-8")
        env = _posix.environ({**os.environ, "RUNNER_TEMP": _posix.path(work), "GITHUB_PATH": _posix.path(work / "path"), "LOG": _posix.path(work),
                              "ANSWERS": _posix.path(work / "answers")}, first=[fake])
        done = subprocess.run([bash, "--noprofile", "--norc", "-e", "-c", run], env=env, cwd=str(work), capture_output=True, text=True, encoding="utf-8", timeout=60)
        naps = [int(n) for n in (work / "naps").read_text(encoding="utf-8").split()] if (work / "naps").exists() else []
        return done, len((work / "tries").read_text(encoding="utf-8").split()), naps, (work / "path").exists()
    done, tries, naps, installed = go([])                               # the usual run: one try, no wait
    assert (done.returncode, tries, naps, installed) == (0, 1, [], True), done.stderr
    done, tries, naps, installed = go([lag, lag])                       # the index shows the release on the third try
    assert (done.returncode, tries, naps, installed) == (0, 3, [15, 30], True), done.stderr
    assert done.stdout.count("PyPI's index does not list knos 9.8.7 yet") == 2
    done, tries, naps, installed = go([lag] * 20)                       # it never does: five tries, 195 s, then red
    assert (done.returncode, tries, sum(naps), installed) == (1, 5, 195, False) and naps == [15, 30, 60, 90]
    # any other failure is red at once: a hash that does not match, another package, another release of knos, the network
    for other in (f"  x Failed to download `{pin}`: Hash mismatch for `{pin}`",
                  "Because there is no version of solders==0.29.0 and you require solders==0.29.0, we can conclude",
                  f"Because there is no version of {pin}0 and you require {pin}0, we can conclude",
                  "error: Failed to fetch: `https://pypi.org/simple/knos/`"):
        done, tries, naps, installed = go([other, lag])
        assert (done.returncode, tries, naps, installed) == (1, 1, [], False), other
        assert other.strip() in done.stderr                             # and uv's own words are shown
    # a list whose last line names no release (a tree before its lock) has no release to wait for
    done, tries, naps, installed = go([lag], last="")
    assert (done.returncode, tries, naps) == (1, 1, [])


def test_the_release_page_says_how_the_worker_chain_is_restarted_and_that_a_rerun_does_not():
    page = " ".join((ROOT / "docs" / "reference" / "RELEASE.md").read_text(encoding="utf-8").split())
    assert "gh workflow run worker.yml --repo drexthealpha/Knos --ref main" in page
    assert "Re-running the failed run restarts nothing" in page
    worker = (WORKFLOWS / "worker.yml").read_text(encoding="utf-8")
    assert 'if [ "${GITHUB_RUN_ATTEMPT:-1}" != "1" ]; then' in worker and "A re-run" in worker        # what the page says is what the file does


def test_every_module_is_reached_from_an_entry_point_as_the_deadcode_job_checks():
    """The deadcode job of tests.yml (scripts/deadcode.py) fails a module no entry point imports. It ran only there, so a
    module whose one caller is `python -m` (knos.private, run by examples/private) failed staging and no local run:
    the same check runs in the suite."""
    import subprocess
    import sys

    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "deadcode.py")], capture_output=True, encoding="utf-8")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "unreached: 0" in out.stdout
