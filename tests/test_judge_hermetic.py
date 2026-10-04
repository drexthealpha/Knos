"""The hermetic judge (knos.judge with an `image`): the command line that isolates a submission, argument by argument;
the refusals (a tag, another digest, no runtime); the three assurances a verdict names; and `knos judge rerun`.

No container runtime is needed for any of these but the last: the command line is a pure function, and the whole path
through the judge is run against a stand-in runtime that runs the command in the mounted tree. The last test runs a
real container, and is skipped where no runtime answers."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from knos import cli, judge, terms

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "bench_tamper" / "sample"
D = "a" * 64
IMAGE = f"registry.example/team/judge@sha256:{D}"
FIX = 'import re\nKNOWN = [("Hello World", "hello-world"), ("a  b", "a-b"), ("x", "x")]\n' \
      'def slugify(s):\n    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")\n'
posix = pytest.mark.skipif(os.name == "nt", reason="the hermetic judge reaches the container through a shell script")


# ---- the command line ------------------------------------------------------------------------------------------------

def test_the_command_line_is_exactly_this():
    assert judge.container_argv("docker", IMAGE, "/t/work", name="n1", label="abc", suite="/t/check/public") == [
        "docker", "run", "--rm", "--interactive", "--pull", "never",
        "--network", "none",
        "--read-only",
        "--tmpfs", "/work:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--user", "65534:65534",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1",
        "--pids-limit", "128",
        "--entrypoint", "",
        "--workdir", "/submission",
        "--env", "HOME=/work", "--env", "TMPDIR=/work", "--env", "LANG=C.UTF-8", "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--mount", "type=bind,source=/t/work,target=/submission,readonly",
        "--mount", "type=bind,source=/t/check/public,target=/suite,readonly",
        "--name", "n1",
        "--label", "knos.judge=abc",
        IMAGE]


def test_the_only_host_paths_in_the_command_line_are_the_tree_and_the_public_suite_both_read_only():
    argv = judge.container_argv("podman", IMAGE, "/t/work", judge.Limits(memory="1g", cpus="0.5", pids=32, scratch="8m"))
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a in ("--mount", "--volume", "-v")]
    assert mounts == ["type=bind,source=/t/work,target=/submission,readonly"]
    assert not any(a in ("--privileged", "--env-file", "--volume", "-v", "--cap-add", "--pid", "--device") for a in argv)
    assert not any(a.startswith("--network=") or a == "host" for a in argv)
    assert argv[argv.index("--memory") + 1] == argv[argv.index("--memory-swap") + 1] == "1g"      # no swap beyond the limit
    assert argv[argv.index("--cpus") + 1] == "0.5" and argv[argv.index("--pids-limit") + 1] == "32"
    assert "size=8m" in argv[argv.index("--tmpfs") + 1] and argv[-1] == IMAGE


@pytest.mark.parametrize("image", ["python:3.12", "python", "docker.io/library/python:3.12-alpine", "ghcr.io/a/b:latest",
                                   f"python@sha256:{D}", f"docker.io/library/python:3.12@sha256:{D}",
                                   f"docker.io/library/python@sha256:{D[:-1]}", f"docker.io/library/python@sha256:{D.upper()}",
                                   f"docker.io/Library/python@sha256:{D}", f"docker.io/library/python@sha256:{D} --privileged", "", 7])
def test_an_image_that_is_not_pinned_by_digest_is_refused(image):
    with pytest.raises(ValueError):
        judge.container_argv("docker", image, "/t/work")
    with pytest.raises(terms.Refused):
        terms.valid_image(image)


def test_a_tag_is_refused_in_words_that_say_what_to_write():
    with pytest.raises(terms.Refused) as why:
        terms.valid_image("docker.io/library/python:3.12")
    said = str(why.value)
    assert "a tag can be pointed at another image after funding" in said and "<registry>/<name>@sha256:<64 hex>" in said


@pytest.mark.parametrize("image", [IMAGE, f"docker.io/library/python@sha256:{D}", f"localhost:5000/judge@sha256:{D}",
                                   f"ghcr.io/owner/repo/judge-image_v2@sha256:{D}"])
def test_an_image_pinned_by_digest_is_taken(image):
    assert terms.valid_image(image) == image and judge.container_argv("docker", image, "/t")[-1] == image


@pytest.mark.parametrize("path", ["relative/tree", "/t/a,b", '/t/a"b', "/t/a\nb"])
def test_a_path_a_mount_cannot_name_is_refused(path):
    with pytest.raises(ValueError, match="cannot mount"):
        judge.container_argv("docker", IMAGE, path)


def test_the_script_runs_each_call_in_its_own_container_and_kills_it_after_the_time_limit():
    argv = judge.container_argv("/usr/bin/docker", IMAGE, "/t/work", label="abc")
    text = judge.run_script(argv, "/usr/bin/docker", 45, "abc")
    lines = text.splitlines()
    assert lines[0] == "#!/bin/sh" and lines[1] == "name=knos-abc-$$"
    assert lines[2].startswith("timeout -s KILL 45 /usr/bin/docker run --rm --interactive --pull never --network none --read-only ")
    assert lines[2].endswith(f'--label knos.judge=abc --name "$name" {IMAGE} "$@"')
    assert lines[3:] == ["code=$?", 'if [ "$code" -ge 124 ]; then', '  /usr/bin/docker rm -f "$name" >/dev/null 2>&1', "fi", 'exit "$code"']
    assert "--entrypoint ''" in lines[2]                                    # an empty argument survives the quoting
    assert judge.run_script(argv, "/usr/bin/docker", 45, "abc", has_timeout=False).splitlines()[2].startswith("/usr/bin/docker run ")


def test_limits_are_fixed_numbers_and_a_wrong_one_is_refused():
    assert vars(judge.Limits()) == {"memory": "512m", "cpus": "1", "pids": 128, "seconds": 45, "scratch": "64m"}
    assert judge.Limits.of({"memory": "1g", "seconds": 10}) == judge.Limits(memory="1g", seconds=10)
    assert judge.Limits.of(None) == judge.Limits()
    for bad in ({"memory": "lots"}, {"memory": "512m --privileged"}, {"pids": 0}, {"pids": "9"}, {"seconds": 0},
                {"seconds": 3601}, {"cpus": "0"}, {"cpus": 1}, {"scratch": "-1m"}):
        with pytest.raises(ValueError, match="limits"):
            judge.Limits.of(bad)


def test_the_runtime_is_docker_then_podman_and_knos_container_overrides():
    has = lambda *names: lambda n: f"/bin/{n}" if n in names else None  # noqa: E731
    assert judge.container_runtime({}, has("docker", "podman")) == "/bin/docker"
    assert judge.container_runtime({}, has("podman")) == "/bin/podman"
    assert judge.container_runtime({}, has()) is None
    assert judge.container_runtime({"KNOS_CONTAINER": "podman"}, has("docker", "podman")) == "/bin/podman"
    assert judge.container_runtime({"KNOS_CONTAINER": "nerdctl"}, has("docker")) is None        # the one asked for, or none
    assert judge.runtime_ready(None) is False and judge.runtime_ready("/no/such/runtime") is False


# ---- the digest that ran ---------------------------------------------------------------------------------------------

def test_the_image_the_machine_holds_must_have_the_digest_in_the_terms():
    assert judge.digest_ran({"RepoDigests": [f"registry.example/team/judge@sha256:{D}"]}, IMAGE) == f"sha256:{D}"
    assert judge.digest_ran([{"RepoDigests": ["x/y@sha256:" + "b" * 64, f"x/y@sha256:{D}"]}], IMAGE) == f"sha256:{D}"
    for held in ({"RepoDigests": ["registry.example/team/judge@sha256:" + "b" * 64]}, {"RepoDigests": []}, {}, None, []):
        with pytest.raises(ValueError, match="Refusing to judge on an image other than the one in the terms"):
            judge.digest_ran(held, IMAGE)


class Ran:
    """subprocess.run, replaced: records each command and answers as a runtime would."""
    def __init__(self, digest: str = D, pull_exit: int = 0, slow: bool = False):
        self.calls, self.digest, self.pull_exit, self.slow = [], digest, pull_exit, slow

    def __call__(self, argv, capture_output=True, timeout=None):
        self.calls.append((list(argv), timeout))
        if self.slow:
            raise subprocess.TimeoutExpired(argv, timeout)
        out = b""
        if argv[1] == "image":
            out = json.dumps({"Id": "sha256:" + "1" * 64, "RepoDigests": [f"registry.example/team/judge@sha256:{self.digest}"]}).encode()
        if argv[1] == "--version":
            out = b"Docker version 27.0.0, build x\n"
        code = self.pull_exit if argv[1] == "pull" else 0
        return subprocess.CompletedProcess(argv, code, out, b"manifest unknown\n" if code else b"")


def test_pull_asks_for_the_digest_and_records_what_ran():
    ran = Ran()
    assert judge.pull("/usr/bin/docker", IMAGE, run=ran) == {"ref": IMAGE, "digest": f"sha256:{D}", "id": "sha256:" + "1" * 64,
                                                             "runtime": "docker", "version": "Docker version 27.0.0, build x"}
    assert [c[0] for c in ran.calls] == [["/usr/bin/docker", "pull", IMAGE],
                                         ["/usr/bin/docker", "image", "inspect", "--format", "{{json .}}", IMAGE],
                                         ["/usr/bin/docker", "--version"]]
    assert ran.calls[0][1] == 900


def test_pull_refuses_another_digest_a_failed_pull_a_slow_one_and_a_tag():
    with pytest.raises(ValueError, match="other than the one in the terms"):
        judge.pull("docker", IMAGE, run=Ran(digest="b" * 64))
    with pytest.raises(ValueError, match="could not pull .* manifest unknown"):
        judge.pull("docker", IMAGE, run=Ran(pull_exit=1))
    with pytest.raises(ValueError, match="took more than 5 seconds"):
        judge.pull("docker", IMAGE, timeout=5, run=Ran(slow=True))
    ran = Ran()
    with pytest.raises(ValueError, match="tag"):
        judge.pull("docker", "registry.example/team/judge:latest", run=ran)
    assert ran.calls == []                                                  # nothing is pulled by a name that can move


# ---- the whole judge, against a stand-in runtime ---------------------------------------------------------------------

FAKE = '''#!%s
"""A stand-in container runtime for the tests: it records its arguments and runs the command in the mounted tree."""
import json, os, sys
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(a) + "\\n")
if a[0] == "--version":
    print("fake runtime 1.0")
elif a[:2] == ["image", "inspect"]:
    print(json.dumps({"Id": "sha256:" + "1" * 64, "RepoDigests": ["registry.example/team/judge@sha256:" + os.environ["FAKE_DIGEST"]]}))
elif a[0] == "run":
    at = next(i for i, x in enumerate(a) if "@sha256:" in x)
    tree = next(x for x in a if x.endswith(",target=/submission,readonly")).split("source=")[1].split(",")[0]
    os.chdir(tree)
    os.execvp(a[at + 1], a[at + 1:])
'''


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    exe = tmp_path / "fake-runtime"
    exe.write_text(FAKE % sys.executable, encoding="utf-8")
    exe.chmod(0o755)
    log = tmp_path / "runtime.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv("KNOS_CONTAINER", str(exe))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_DIGEST", D)
    return lambda: [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.fixture()
def repos(tmp_path):
    base, pr = tmp_path / "base", tmp_path / "pr"
    shutil.copytree(SAMPLE, base)
    shutil.copytree(SAMPLE, pr)
    (pr / "calc.py").write_text(FIX, encoding="utf-8")
    return base, pr


@posix
def test_with_an_image_the_submission_runs_only_through_the_container_and_the_verdict_records_the_digest(repos, fake):
    base, pr = repos
    v = judge.judge(base, pr, {"issue": "2", "image": IMAGE}, sandbox="require")     # the container stands in for the host sandbox
    assert v["passed"], v["reasons"]
    assert v["assurance"] == "hermetic" and v["assurance_means"] == terms.ASSURANCE["hermetic"]
    ev = v["evidence"]
    assert ev["image"] == {"ref": IMAGE, "digest": f"sha256:{D}", "id": "sha256:" + "1" * 64, "runtime": "fake-runtime",
                           "version": "fake runtime 1.0", "limits": vars(judge.Limits())}
    assert ev["sandbox"] == {"user": 65534, "network": "none", "container": f"sha256:{D}"}
    assert ev["artifact"] == {"base": judge.tree_hash(base), "pr": judge.tree_hash(pr)}
    calls = fake()
    runs = [c for c in calls if c[0] == "run"]
    assert [c[0] for c in calls[:4]] == ["info", "pull", "image", "--version"] and len(runs) == 2      # the base, then the pull request
    for c in runs:
        at = c.index(IMAGE)
        assert c[at + 1:at + 3] == ["python3", "-c"]
        name = c[c.index("--name") + 1]
        want = judge.container_argv("run", IMAGE, "/x", label=c[c.index("--label") + 1].split("=")[1])
        got = [a for a in c[:at + 1] if a not in ("--name", name)]
        assert [a if not a.startswith("type=bind") else "M" for a in got] == [a if not a.startswith("type=bind") else "M" for a in want[1:]]
        assert name.startswith("knos-")
    assert calls[-1][:3] == ["ps", "-aq", "--filter"]                                # what outlived its limit is removed
    noop = judge.judge(base, base, {"issue": "2", "image": IMAGE})
    assert not noop["passed"] and noop["assurance"] == "hermetic"


@posix
def test_the_terms_image_is_the_one_that_runs_whatever_proof_toml_says(repos, fake):
    base, pr = repos
    (base / ".knos" / "proof.toml").write_text('[judge]\nimage = "registry.example/other/thing@sha256:%s"\n' % ("c" * 64), "utf-8")
    shutil.copy(base / ".knos" / "proof.toml", pr / ".knos" / "proof.toml")
    cfg = judge.proof_config((base / ".knos" / "proof.toml").read_text("utf-8"))
    v = judge.judge(base, pr, {**cfg, "issue": "2", "image": IMAGE})
    assert v["evidence"]["image"]["ref"] == IMAGE and v["passed"], v["reasons"]
    assert all(IMAGE in c for c in fake() if c[0] in ("pull", "run"))


@posix
def test_a_local_image_with_another_digest_stops_the_judge_before_any_pull_request_code_runs(repos, fake, monkeypatch):
    base, pr = repos
    monkeypatch.setenv("FAKE_DIGEST", "b" * 64)
    v = judge.judge(base, pr, {"issue": "2", "image": IMAGE})
    assert not v["passed"] and "other than the one in the terms" in v["reasons"][0]
    assert not [c for c in fake() if c[0] == "run"] and "image" not in v["evidence"] and v["assurance"] != "hermetic"


def test_an_image_is_never_swapped_for_the_host(repos, monkeypatch):
    base, pr = repos
    monkeypatch.setattr(judge, "container_runtime", lambda *a, **k: None)
    monkeypatch.setattr(judge, "_side", lambda *a, **k: pytest.fail("pull request code was run"))
    none = judge.judge(base, pr, {"issue": "2", "image": IMAGE})
    monkeypatch.setattr(judge, "container_runtime", lambda *a, **k: "/no/such/docker")
    down = judge.judge(base, pr, {"issue": "2", "image": IMAGE})
    if os.name == "nt":     # it says it needs a POSIX shell before it looks for a runtime, and runs nothing
        assert not none["passed"] and not down["passed"] and all("needs a POSIX shell" in v["reasons"][0] for v in (none, down))
    else:
        assert not none["passed"] and "no container runtime on this machine" in none["reasons"][0] and "KNOS_CONTAINER" in none["reasons"][0]
        assert "does not answer" in down["reasons"][0]
    tag = judge.judge(base, pr, {"issue": "2", "judge": {"image": "python:3.12"}})
    assert not tag["passed"] and "Pin it by digest" in tag["reasons"][0]
    inproc = judge.judge(base, pr, {"issue": "1", "image": IMAGE})
    assert not inproc["passed"] and "an image goes with a black-box bundle" in inproc["reasons"][0]
    monkeypatch.setattr(judge, "container_runtime", lambda *a, **k: sys.executable)
    monkeypatch.setattr(judge, "runtime_ready", lambda rt: True)
    setup = judge.judge(base, pr, {"issue": "2", "image": IMAGE}, setup="pip install x")
    assert "a hermetic judge installs nothing" in setup["reasons"][0]


# ---- the three assurances --------------------------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "darwin", reason="as tests/test_tamper_bench.py: the sample's tests are not collected on macOS")
def test_every_verdict_names_its_assurance_and_what_it_means(repos):
    base, pr = repos
    tests = judge.judge(base, pr, {"issue": "1", "test_dirs": ["tests"]})
    assert tests["passed"] and tests["assurance"] == "in-process" and "7 of 63" in tests["assurance_means"]
    if os.name != "nt":
        box = judge.judge(base, pr, {"issue": "2"})
        assert box["passed"] and box["assurance"] == "black-box" and "0 of 63" in box["assurance_means"]
    assert set(terms.ASSURANCE) == {"in-process", "black-box", "hermetic"}
    for said in terms.ASSURANCE.values():                    # a count for one suite, never a promise
        assert "63" in said and not any(w in said.lower() for w in ("cannot be cheated", "impossible", "unforgeable", "guarantee"))
    for said in (terms.ASSURANCE["black-box"], terms.ASSURANCE["hermetic"]):
        assert "not a proof for every attack" in said
    assert (judge.assurance_of("python", False), judge.assurance_of("blackbox", False), judge.assurance_of("blackbox", True),
            judge.assurance_of("command", True)) == ("in-process", "black-box", "hermetic", "in-process")


def test_the_assurance_page_has_the_three_rows_and_a_bounded_claim():
    page = (ROOT / "docs" / "ASSURANCE.md").read_text(encoding="utf-8")
    part = page.split("## How much a verdict can carry", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in part.split("| Invariant |")[0].splitlines() if ln.startswith("| `") and not ln.startswith("| `assurance`")]
    assert [r.split("|")[1].strip() for r in rows] == ["`in-process`", "`black-box`", "`hermetic`"]
    assert "7 of 63" in rows[0] and "0 of 63" in rows[1] and "0 of 63" in rows[2]
    assert "cannot be cheated" not in part.replace('never "cannot be cheated"', "")


# ---- knos judge rerun ------------------------------------------------------------------------------------------------

@posix
def test_rerun_judges_the_same_artifact_in_the_same_image_and_says_agree_or_disagree(repos, fake, tmp_path, capsys):
    base, pr = repos
    first = judge.judge(base, pr, {"issue": "2", "image": IMAGE})
    got = judge.rerun(first, base, pr)
    assert got == {"agree": True, "differences": [], "again": got["again"]} and got["again"]["evidence"]["image"]["digest"] == f"sha256:{D}"
    file = tmp_path / "verdict.json"
    file.write_text(json.dumps(first), encoding="utf-8")
    assert cli.main(["judge", "rerun", str(file), "--base", str(base), "--pr", str(pr)]) == 0
    said = capsys.readouterr().out
    assert "agree: passed both times" in said and "judged again: hermetic" in " ".join(said.split())
    bundle = tmp_path / "bundle"                             # a bundle: the verdict under "verdict", the trees beside it
    bundle.mkdir()
    (bundle / "verdict.json").write_text(json.dumps({"verdict": first, "receipt": "..."}), encoding="utf-8")
    shutil.copytree(base, bundle / "base")
    shutil.copytree(pr, bundle / "pr")
    assert cli.main(["judge", "rerun", str(bundle)]) == 0
    capsys.readouterr()
    lie = {**first, "passed": False}
    file.write_text(json.dumps(lie), encoding="utf-8")
    assert cli.main(["judge", "rerun", str(file), "--base", str(base), "--pr", str(pr)]) == 1
    said = " ".join(capsys.readouterr().out.split())
    assert "disagree" in said and "DIFFERENT verdict: the verdict says refused, this run says passed" in said


@posix
def test_rerun_refuses_other_trees_another_image_and_a_file_that_is_no_verdict(repos, fake, tmp_path, monkeypatch, capsys):
    base, pr = repos
    first = judge.judge(base, pr, {"issue": "2", "image": IMAGE})
    (pr / "calc.py").write_text(FIX + "\n# changed since\n", encoding="utf-8")
    with pytest.raises(ValueError, match="is not the pr tree this verdict was given on"):
        judge.rerun(first, base, pr)
    (pr / "calc.py").write_text(FIX, encoding="utf-8")
    monkeypatch.setenv("FAKE_DIGEST", "b" * 64)              # the machine now holds other bytes under that name
    got = judge.rerun(first, base, pr)
    assert not got["agree"] and any(d.startswith("image digest:") for d in got["differences"])
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"passed": True, "checks_hash": "x", "reasons": [], "evidence": {"issue": "2"}}), encoding="utf-8")
    assert cli.main(["judge", "rerun", str(old), "--base", str(base), "--pr", str(pr)]) != 0
    assert "evidence.artifact" in " ".join((lambda c: c.out + c.err)(capsys.readouterr()).split())


@pytest.mark.skipif(os.name == "nt", reason="black-box needs a shell wrapper")
def test_rerun_of_a_verdict_given_without_an_image_does_not_use_one(repos, monkeypatch):
    base, pr = repos
    first = judge.judge(base, pr, {"issue": "2"})
    monkeypatch.setattr(judge, "_hold", lambda *a, **k: pytest.fail("a container was asked for"))
    got = judge.rerun(first, base, pr, {"judge": {"image": IMAGE}})
    assert got["agree"] and got["again"]["assurance"] == "black-box"


# ---- one real container ----------------------------------------------------------------------------------------------

def _bench():
    spec = importlib.util.spec_from_file_location("tamper_bench", ROOT / "scripts" / "tamper_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not (sys.platform.startswith("linux") and judge.runtime_ready(judge.container_runtime())),
                    reason="no container runtime answers on this machine")
def test_end_to_end_in_a_real_container(repos):
    bench = _bench()
    try:
        judge.pull(judge.container_runtime(), bench.ESCAPE_IMAGE)
    except ValueError as why:
        pytest.skip(f"the image could not be pulled here: {why}")
    base, pr = repos
    cfg = {"issue": "2", "image": bench.ESCAPE_IMAGE}
    good = judge.judge(base, pr, cfg)
    assert good["passed"] and good["assurance"] == "hermetic", good["reasons"]
    assert good["evidence"]["image"]["digest"] == bench.ESCAPE_IMAGE.split("@")[1]
    assert not judge.judge(base, base, cfg)["passed"]
    assert judge.rerun(good, base, pr)["agree"]
    got = bench.run_escapes(only=("hermetic",))
    assert not got["places"]["hermetic"], got["places"]
    assert {k: v["hermetic"] for k, v in got["rows"].items()} == {e.key: False for e in bench.ESCAPES}


def test_the_example_names_an_image_the_terms_take():
    ex = ROOT / "examples" / "acceptance" / "hermetic"
    image = judge.image_of(judge.proof_config((ex / "proof.toml").read_text(encoding="utf-8")))
    held = terms.parse((ex / "terms.json").read_bytes().rstrip(b"\n"))
    assert held["image"] == terms.valid_image(image) == _bench().ESCAPE_IMAGE and terms.assurance(held) == "hermetic"
    assert image in (ex / "README.md").read_text(encoding="utf-8") and not (ex / "base").exists()   # not a task: nothing to judge here


@posix
def test_the_judge_command_prints_the_assurance_of_its_verdict(repos, capsys):
    base, pr = repos
    assert cli.main(["proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", "2", "--sandbox", "off"]) == 0
    said = " ".join(capsys.readouterr().out.split())
    assert "assurance black-box: The pull request's code runs as a separate process" in said and "0 of 63" in said
