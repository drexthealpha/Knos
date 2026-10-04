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
    assert not [name for name, job in tests["jobs"].items() if "if" in job]
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
    [skipped] = tool["mypy"]["overrides"]
    assert skipped["ignore_errors"] is True and len(skipped["module"]) == len(set(skipped["module"]))
    for module in skipped["module"]:
        assert (ROOT / "src" / Path(*module.split("."))).with_suffix(".py").is_file(), f"{module} is gone: take it off the list"


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


def test_publish_uploads_only_the_locked_wheel_from_a_committed_tree_with_a_token_from_the_environment():
    text = (ROOT / "scripts" / "release.py").read_text(encoding="utf-8")
    body = text[text.index("def publish_cmd"):text.index("def main")]
    order = ["is not the locked wheel", "the working tree is not committed", "the commit does not hold this lock", "on_pypi(version)", "UV_PUBLISH_TOKEN", '"uv", "publish"', "pypi_check(wait=300)"]
    assert [body.index(x) for x in order] == sorted(body.index(x) for x in order)
    assert "--check-url" in body and "print(os.environ" not in text and "UV_PUBLISH_TOKEN\"]" not in text      # the token is read by uv, never by this script
    r = _release_script()
    assert r.EPOCH == 1767225600 and r.BUILD == "requirements/build.txt"
    build = (ROOT / "requirements" / "build.txt").read_text(encoding="utf-8")
    pinned = re.search(r'^requires = \["hatchling==([\d.]+)"\]', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    assert f"hatchling=={pinned} \\\n    --hash=sha256:" in build
    assert all("--hash=sha256:" in block for block in re.split(r"\n(?=[a-z])", build) if re.match(r"[a-z][\w.-]*==", block))
