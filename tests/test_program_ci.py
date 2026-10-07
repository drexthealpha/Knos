"""The program workflow keeps a branch push short and honest. Every job runs beside the others (a second deployment is
a second job, not more steps), every Rust build starts from a pinned cache action, the long random walk is four short
ones from seeds of their own, the container build waits for main, and the tests can only load a binary this commit's
source built. And the build scripts, driven with a stand-in for cargo: what each builds, under which names, and that
the build left to deploy is the real one."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "program.yml"
FIXTURES = ROOT / "tests" / "fixtures"


def _doc() -> dict:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))   # YAML 1.1 reads the key `on` as True
    return doc


def _runs(job: dict) -> str:
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def _legs(job: dict) -> dict[str, dict]:
    """What the job's matrix says about each deployment."""
    return {entry["deployment"]: entry for entry in job["strategy"]["matrix"]["include"]}


def _bash() -> str:
    bash = shutil.which("bash")
    if os.name == "nt" or not bash:
        pytest.skip("the build steps are bash; the programs are built on Linux")
    return bash


def test_a_second_deployment_is_a_job_beside_the_first_not_more_steps_in_it():
    doc = _doc()
    jobs = doc["jobs"]
    # nothing waits (the wait is the longest one job), but the gate: it signs the hashes of the verified builds
    assert {name: job["needs"] for name, job in jobs.items() if "needs" in job} == {"gate": "verified-build"}
    build = jobs["build-test"]
    legs = _legs(build)
    assert set(legs) == {"first", "second"} and build["strategy"]["fail-fast"] is False
    assert (legs["first"]["workspace"], legs["second"]["workspace"]) == ("programs", "programs-v2")
    assert (legs["first"]["suffix"], legs["second"]["suffix"]) == ("", "-v2")   # the first deployment's artifact names stay
    for leg in legs.values():
        assert (ROOT / leg["build"]).is_file() and (ROOT / leg["cargo-test"] / "Cargo.toml").is_file(), leg
        assert (ROOT / leg["workspace"] / "Cargo.lock").is_file(), leg       # what the cache key and cargo audit read
    # cargo test, the build, the LiteSVM tests and the fixture check, in that order, for whichever deployment it is
    run = _runs(build)
    at = [run.index(s) for s in ('cd "$CARGO_TEST" && cargo test --release', 'bash "$BUILD"', "pytest -q -s $TESTS",
                                 "python scripts/interface_fixture.py --check")]
    assert at == sorted(at)
    assert build["env"] == {"DEPLOYMENT": "${{ matrix.deployment }}", "CARGO_TEST": "${{ matrix.cargo-test }}",
                            "BUILD": "${{ matrix.build }}", "TESTS": "${{ matrix.tests }}"}
    assert "matrix." not in run and "github." not in run                    # values reach the scripts through env only
    # the first deployment's tests are named; the second's are every test file of the verifier, the escrow and its
    # work orders, the tests of its other two programs (the meter and the passkey wallet), and the tests of the
    # example programs that are built against it
    assert all((ROOT / t).is_file() for t in legs["first"]["tests"].split())
    assert legs["second"]["tests"] == ("tests/test_oidc2_*.py tests/test_oidc_differential.py tests/test_pay2_*.py tests/test_order_*.py tests/test_meter_chain.py "
                                       "tests/test_passkey_chain.py tests/test_cpi_fund.py tests/test_workflow_vault.py tests/test_upgrade_gate.py tests/test_reader_template.py")
    # the verifier against a reference that shares no code with it, on this commit's build (it loads the same test binary)
    assert 'PROGRAM = "knos_oidc_v2_test.so"' in (ROOT / "tests" / "test_oidc_differential.py").read_text(encoding="utf-8")
    for pattern, harness in zip(legs["second"]["tests"].split(), ("_oidc2.py", "test_oidc_differential.py", "_pay2.py", "_order.py", "_meter.py", "test_passkey_chain.py",
                                                                  "test_cpi_fund.py", "test_workflow_vault.py", "test_upgrade_gate.py", "test_reader_template.py")):
        assert (ROOT / "tests" / harness).is_file(), harness                 # a program's tests arrive with its harness
        assert list(ROOT.glob(pattern)), f"{pattern} matches no file: pytest would fail the second deployment's job"
    assert sorted(p.name for p in ROOT.glob("tests/test_order_*.py")) == ["test_order_auto.py", "test_order_chain.py", "test_order_judges.py",
                                                                              "test_order_quorum.py", "test_order_terms.py"]
    # the examples: each one's test loads the binary the second deployment's script builds from examples/<name>, and
    # the cache holds their shared target directory beside the workspace's (rust-cache: `workspace -> target`)
    script = (ROOT / legs["second"]["build"]).read_text(encoding="utf-8")
    examples = re.findall(r"^  example (\w+) (\w+\.so)$", script, re.M)
    assert [name for name, _ in examples] == ["cpi_fund", "workflow_vault", "upgrade_gate", "reader_template"] and 'to="${CARGO_TARGET_DIR:-$PWD/examples/target}"' in script
    for name, binary in examples:
        assert (ROOT / "examples" / name / "Cargo.lock").is_file() and f"tests/test_{name}.py" in legs["second"]["tests"].split()
        assert binary in (ROOT / "tests" / f"test_{name}.py").read_text(encoding="utf-8"), name
    assert legs["second"]["also"].split("\n") == [f"examples/{name} -> ../target" for name, _ in examples]
    assert legs["first"]["also"] == "examples/oidc_gate" and "tests/test_oidc_gate.py" in legs["first"]["tests"].split()
    paths = set(doc["on"]["push"]["paths"])
    assert {"programs/**", "programs-v2/**", "examples/**", "crates/**", "scripts/build_programs*.sh", "tests/test_oidc*.py", "tests/test_pay*.py",
            "tests/test_order*.py", "tests/test_meter*.py", "tests/test_passkey*.py", "tests/test_cpi_fund.py", "tests/test_workflow_vault.py",
            "tests/test_upgrade_gate.py"} <= paths
    # every path the workflow watches exists (a pattern that matches nothing is a trigger that never fires)
    # the first match is enough: walking all of `crates/**` races a test beside this one whose cargo build writes and
    # removes files under crates/*/target while the walk lists them
    for path in paths:
        assert next(iter(ROOT.glob(path)), None) is not None or (ROOT / path).exists(), path
    # what the job keeps: every program its workspace built (the second deployment's four, the first's two)
    upload = next(s for s in build["steps"] if (s.get("with") or {}).get("name") == "programs${{ matrix.suffix }}")
    assert upload["with"]["path"] == "${{ matrix.workspace }}/target/deploy/knos_*.so" and upload["with"]["if-no-files-found"] == "error"
    members = re.search(r"members = \[(.+?)\]", (ROOT / "programs-v2" / "Cargo.toml").read_text(encoding="utf-8")).group(1)
    assert sorted(re.findall(r'"(\w+)"', members)) == ["knos_meter", "knos_oidc", "knos_passkey", "knos_pay"]   # cargo test and clippy reach all four
    audit = _runs(jobs["cargo-audit"])
    assert "(cd programs && cargo audit)" in audit and "(cd programs-v2 && cargo audit)" in audit
    assert "(cd crates/knos-oidc-interface && cargo audit)" in audit and (ROOT / "crates" / "knos-oidc-interface" / "Cargo.lock").is_file()
    # a newer push to a branch cancels the run of the push before it; on main every run finishes
    assert doc["concurrency"] == {"group": "program-${{ github.ref }}", "cancel-in-progress": "${{ github.ref != 'refs/heads/main' }}"}


def test_every_rust_build_starts_from_the_pinned_cache_action():
    doc = _doc()
    pin = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]["Swatinem/rust-cache@v2"]
    assert re.fullmatch(r"[0-9a-f]{40}", pin)
    for name in ("build-test", "fuzz", "interface"):
        steps = doc["jobs"][name]["steps"]
        cache = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("Swatinem/rust-cache@")]
        cargo = [i for i, s in enumerate(steps) if re.search(r"\bcargo (test|build)|\$BUILD", str(s.get("run", "")))]
        assert len(cache) == 1 and steps[cache[0]]["uses"] == f"Swatinem/rust-cache@{pin}", name
        assert cargo and cache[0] < min(cargo), name                       # restored before the first compile
    build, fuzz = (next(s for s in doc["jobs"][j]["steps"] if str(s.get("uses", "")).startswith("Swatinem/")) for j in ("build-test", "fuzz"))
    # one cache per deployment: runs on main save it from build-test, branches and the walks read it
    key = "programs-${{ matrix.deployment }}-agave-${{ env.SOLANA_VERSION }}"
    assert build["with"]["shared-key"] == fuzz["with"]["shared-key"] == key
    assert build["with"]["workspaces"] == fuzz["with"]["workspaces"] == "${{ matrix.workspace }}\n${{ matrix.also }}\n"
    assert build["with"]["save-if"] == "${{ github.ref == 'refs/heads/main' }}" and fuzz["with"]["save-if"] is False
    for deployment, leg in _legs(doc["jobs"]["build-test"]).items():       # the same workspaces, or the key would differ
        walk = _legs(doc["jobs"]["fuzz"])[deployment]
        assert [walk[k] for k in ("workspace", "also", "build")] == [leg[k] for k in ("workspace", "also", "build")]
    # the container build compiles with no cache, so it is not on a branch push's path
    # (a release tag builds them too: the upgrade gate records a build made at a commit of main or of a v tag)
    assert doc["jobs"]["verified-build"]["if"] == "github.event_name != 'push' || github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v')"
    assert not any(str(s.get("uses", "")).startswith("Swatinem/") for s in doc["jobs"]["verified-build"]["steps"])
    verified = doc["jobs"]["verified-build"]
    assert sorted(verified["strategy"]["matrix"]["workspace"]) == ["programs", "programs-v2"]
    assert verified["strategy"]["matrix"]["program"] == ["knos_oidc", "knos_pay"]
    # the second deployment's other two programs and upgrade_gate are built the same way; the meter's dependency on the
    # interface crate is outside its workspace, and cargo reads every member of a workspace to build any one, so every
    # build of programs-v2 mounts the repository and names the workspace; upgrade_gate reads the same crate
    assert verified["strategy"]["matrix"]["include"] == [{"workspace": "programs-v2", "mount": "repository"},
                                                         {"workspace": "programs-v2", "program": "knos_meter", "mount": "repository"},
                                                         {"workspace": "programs-v2", "program": "knos_passkey", "mount": "repository"},
                                                         {"workspace": "examples/upgrade_gate", "program": "upgrade_gate", "mount": "repository"}]
    assert verified["env"] == {"WORKSPACE": "${{ matrix.workspace }}", "PROGRAM": "${{ matrix.program }}", "MOUNT": "${{ matrix.mount }}"}
    run = _runs(verified)
    assert 'solana-verify build "$GITHUB_WORKSPACE" --workspace-path "$GITHUB_WORKSPACE/$WORKSPACE" --library-name "$PROGRAM"' in run
    assert 'solana-verify build "$GITHUB_WORKSPACE/$WORKSPACE" --library-name "$PROGRAM"' in run and "matrix." not in run
    outside = [name for name in ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")
               if re.search(r'path = "\.\./\.\./', (ROOT / "programs-v2" / name / "Cargo.toml").read_text(encoding="utf-8"))]
    assert outside == ["knos_meter"]                                       # one member reads outside: the workspace needs the wider mount
    assert re.search(r'path = "\.\./\.\./crates/knos-oidc-interface"', (ROOT / "examples" / "upgrade_gate" / "Cargo.toml").read_text(encoding="utf-8"))


def test_the_gate_job_has_github_sign_the_hash_of_each_verified_build_and_runs_nothing_a_commit_wrote(tmp_path):
    """examples/upgrade_gate takes a token only from this file (job_workflow_ref program.yml@), at the commit built, on
    main or a v tag, in drexthealpha/Knos, on a GitHub-hosted runner: the job is here, runs only there, and is the
    only one that may ask for a token. It checks out nothing and builds nothing: it hashes this run's artifacts."""
    from knos.settle.v2 import gate
    doc = _doc()
    job = doc["jobs"]["gate"]
    assert doc["permissions"] == {"contents": "read"}
    assert [name for name, j in doc["jobs"].items() if "id-token" in (j.get("permissions") or {})] == ["gate"]
    assert job["permissions"] == {"id-token": "write", "issues": "write"} and job["runs-on"] == "ubuntu-latest" and "uses" not in job
    assert job["if"] == ("github.repository == 'drexthealpha/Knos' && github.event_name != 'schedule' && "
                         "(github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v'))")
    assert gate.WORKFLOW == "drexthealpha/Knos/.github/workflows/program.yml" and WORKFLOW.name == "program.yml"
    lib = (ROOT / "examples" / "upgrade_gate" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert 'git_ref.is("refs/heads/main") || git_ref.starts_with("refs/tags/v")' in lib and 'is("github-hosted")' in lib
    # a push of a v tag starts the workflow (no branch filter; GitHub does not apply a path filter to a tag) and the builds run on it
    assert set(doc["on"]["push"]) == {"paths"} and "workflow_dispatch" in doc["on"]
    # one action, the artifacts of this run; no checkout, no cache, no toolchain, no secret
    [down, sign] = job["steps"]
    assert down["uses"].split("@")[0] == "actions/download-artifact" and down["with"] == {"pattern": "*-v2-verified.so", "path": "built"}
    pins = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]
    assert down["uses"].split("@")[1] == pins["actions/download-artifact@v8"]
    run = sign["run"]
    assert sign["env"] == {"GH_TOKEN": "${{ github.token }}"} and "${{" not in run and "secrets." not in json.dumps(job)
    assert not re.search(r"\bgit\b|cargo|solana|pip |uv |npm |checkout", run)
    # the programs are the second deployment's four, by their pinned ids, and each is an artifact verified-build uploads
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    named = dict(entry.split("=") for entry in job["env"]["PROGRAMS"].split())
    assert named == {name: ids[name] for name in ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")}
    verified = doc["jobs"]["verified-build"]
    built = {(w, p) for w in verified["strategy"]["matrix"]["workspace"] for p in verified["strategy"]["matrix"]["program"]}
    built |= {(e["workspace"], e["program"]) for e in verified["strategy"]["matrix"]["include"] if "program" in e}
    assert {p for w, p in built if w == "programs-v2"} == set(named)
    [upload] = [s for s in verified["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert upload["with"]["name"] == "${{ matrix.program }}${{ matrix.workspace == 'programs-v2' && '-v2' || '' }}-verified.so"
    assert upload["with"]["path"] == "${{ matrix.workspace }}/target/deploy/${{ matrix.program }}.so"
    assert 'file="built/${entry%%=*}-v2-verified.so/${entry%%=*}.so"' in run
    assert '"$ACTIONS_ID_TOKEN_REQUEST_URL&audience=gate:$id:$hash"' in run and "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" in run
    assert "printf 'knos-gate: %s\\n\\n<sub>knosrelay: " in run and 'gh issue comment "$issue"' in run and '.title == "knos tokens"' in run
    # the step itself, run with stand-ins for GitHub: the audience it asks for is the client's, for the hash solana-verify prints
    bash = _bash()
    elf = b"\x7fELF" + hashlib.sha256(b"a verified build").digest() * 8
    for name in named:
        (tmp_path / "built" / f"{name}-v2-verified.so").mkdir(parents=True)
        (tmp_path / "built" / f"{name}-v2-verified.so" / f"{name}.so").write_bytes(elf + name.encode() + bytes(300))
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$OUT/gh.log"\ncase "$*" in\n  "api repos/drexthealpha/Knos/issues?state=open"*) echo 12 ;;\n'
                             '  "issue comment"*) cat >> "$OUT/comments" ;;\nesac\n', encoding="utf-8")
    (fake / "curl").write_text('#!/bin/sh\nfor a in "$@"; do last="$a"; done\nprintf \'%s\\n\' "$last" >> "$OUT/asked"\n'
                               'printf \'{"value": "eyJh.%s.sig"}\' "$(printf %s "$last" | sha256sum | cut -c1-16)"\n', encoding="utf-8")
    for tool in ("gh", "curl"):
        (fake / tool).chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "OUT": str(tmp_path), "PROGRAMS": job["env"]["PROGRAMS"],
           "GITHUB_REPOSITORY": "drexthealpha/Knos", "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"), "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "t",
           "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.test/?api-version=2"}
    done = subprocess.run([bash, "-c", run], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    want = [gate.audience(ids[name], gate.executable_hash(elf + name.encode())) for name in named]
    assert (tmp_path / "asked").read_text(encoding="utf-8").split() == [f"https://token.test/?api-version=2&audience={aud}" for aud in want]
    from knos.proof import ghrelay
    posted = ghrelay.TOKEN.findall((tmp_path / "comments").read_text(encoding="utf-8"))
    assert [kind for kind, _jwt in posted] == ["gate"] * 4 and len({jwt for _kind, jwt in posted}) == 4
    log = (tmp_path / "gh.log").read_text(encoding="utf-8").splitlines()
    assert len(log) == 5 and all(line == "issue comment 12 --repo drexthealpha/Knos --body-file -" for line in log[1:])     # the issue was there: none is made
    assert all(f"{name} {ids[name]}: executable hash" in (tmp_path / "summary").read_text(encoding="utf-8") for name in named)
    # a build that is missing from the run fails the job before anything else is signed for it
    (tmp_path / "built" / "knos_pay-v2-verified.so" / "knos_pay.so").unlink()
    again = subprocess.run([bash, "-c", run], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert again.returncode == 1 and "no verified build of knos_pay" in again.stdout


def test_ten_thousand_random_steps_are_four_walks_side_by_side_each_from_its_own_seed():
    fuzz = _doc()["jobs"]["fuzz"]
    matrix = fuzz["strategy"]["matrix"]
    assert matrix["deployment"] == ["first", "second"] and len(set(matrix["walk"])) == 4
    step = next(s for s in fuzz["steps"] if "random_walk" in str(s.get("run", "")))
    assert len(matrix["walk"]) * int(step["env"]["KNOS_FUZZ_N"]) == 10_000
    assert step["env"]["KNOS_FUZZ_SEED"] == "${{ github.run_id }}${{ github.run_attempt }}${{ matrix.walk }}"
    assert "pytest -q -s $TESTS -k random_walk" in step["run"] and 'bash "$BUILD"' in _runs(fuzz)   # this commit's binaries
    legs = _legs(fuzz)
    assert (legs["first"]["tests"], legs["second"]["tests"]) == ("tests/test_pay_chain.py", "tests/test_pay2_*.py")
    # and each walk takes the seed (the first deployment's used to walk one fixed path whatever the workflow set)
    walks = [p for pattern in (leg["tests"] for leg in legs.values()) for p in sorted(ROOT.glob(pattern))
             if "random_walk" in p.read_text(encoding="utf-8")]
    assert ROOT / "tests" / "test_pay_chain.py" in walks
    for path in walks:
        text = path.read_text(encoding="utf-8")
        assert re.search(r'FUZZ_SEED = int\(os\.environ\.get\("KNOS_FUZZ_SEED", "\d+"\)\)', text), path.name
        assert re.search(r'FUZZ_N = int\(os\.environ\.get\("KNOS_FUZZ_N", "\d+"\)\)', text), path.name
        assert "random.Random(FUZZ_SEED)" in text and not re.search(r"random\.Random\(\d", text), path.name


def test_the_tests_can_only_load_a_binary_this_commit_built(tmp_path):
    """The build step as the workflow runs it, around a build script that builds one binary less than was committed:
    the deployment's committed binaries are gone before it builds, so the one it does not build is missing afterwards
    (a test that loads it fails) instead of being tested as it was committed. The other deployment's are not touched."""
    bash = _bash()
    doc = _doc()
    for job in ("build-test", "fuzz"):
        [step] = [s for s in doc["jobs"][job]["steps"] if 'bash "$BUILD"' in str(s.get("run", ""))]
        # the meter's binary carries no _v2_ and is the second deployment's all the same
        for deployment, builds, left in (("first", "knos_pay_test.so", "knos_pay_v2_test.so knos_old_v2_test.so knos_meter_test.so"),
                                         ("second", "knos_pay_v2_test.so", "knos_pay_test.so knos_old_test.so")):
            tree = tmp_path / job / deployment
            (tree / "tests" / "fixtures").mkdir(parents=True)
            for name in ("knos_pay_test.so", "knos_old_test.so", "knos_pay_v2_test.so", "knos_old_v2_test.so", "knos_meter_test.so", "SHA256SUMS",
                         "keys.json"):
                (tree / "tests" / "fixtures" / name).write_text("committed", encoding="utf-8")
            (tree / "build.sh").write_text(f"echo built > tests/fixtures/{builds}\n", encoding="utf-8")
            env = {**os.environ, "DEPLOYMENT": deployment, "BUILD": "build.sh"}
            r = subprocess.run([bash, "-e", "-c", step["run"]], cwd=str(tree), env=env, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            got = {p.name: p.read_text(encoding="utf-8").strip() for p in (tree / "tests" / "fixtures").iterdir()}
            want = {builds: "built", "SHA256SUMS": "committed", "keys.json": "committed", **dict.fromkeys(left.split(), "committed")}
            assert got == want, (job, deployment)


def test_every_committed_test_binary_is_one_its_deployments_build_script_builds():
    """The other half of the test above, where it can be seen before a push: a binary in tests/fixtures that neither
    build script builds would be missing in the program workflow."""
    legs = _legs(_doc()["jobs"]["build-test"])
    binaries = sorted(FIXTURES.glob("*.so"))
    assert binaries
    for binary in binaries:
        # the meter exists only in the second deployment's workspace, so its binary carries no _v2_
        script = ROOT / legs["second" if "_v2_" in binary.name or binary.name.startswith("knos_meter_") else "first"]["build"]
        code = "\n".join(ln for ln in script.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
        assert re.search(rf"(?<![\w.]){re.escape(binary.name)}(?![\w.])", code), (
            f"tests/fixtures/{binary.name}: scripts/{script.name} does not build it. The program workflow removes the "
            f"committed binaries before it builds, so a test that loads this one would fail there: add its build, or remove it")


def test_the_two_claim_readers_and_serde_json_are_asked_the_same_documents_on_every_push():
    """The fuzz target's check runs nightly on any bytes; the same function runs on stable, from fixed seeds, in the
    job that tests the interface crate. And the crate a program funds an order with is tested there too."""
    job = _doc()["jobs"]["interface"]
    assert "if" not in job and "needs" not in job
    run = _runs(job)
    assert "cd programs-v2/knos_oidc/fuzz && cargo test --release --locked --test random --test seeds" in run
    fuzz = ROOT / "programs-v2" / "knos_oidc" / "fuzz"
    assert (fuzz / "Cargo.lock").is_file() and (fuzz / "tests" / "random.rs").is_file()
    # the committed seeds, through both targets' checks, beside it: the files the nightly fuzzer starts from
    seeds = (fuzz / "tests" / "seeds.rs").read_text(encoding="utf-8")
    assert len(re.findall(r"^#\[test\]$", seeds, re.M)) >= 2 and all(f'each("{t}"' in seeds and any((fuzz / "seeds" / t).iterdir()) for t in ("rsa_verify", "claims"))
    tests = (fuzz / "tests" / "random.rs").read_text(encoding="utf-8")
    assert len(re.findall(r"^#\[test\]$", tests, re.M)) == 4 and "agree(" in tests
    # the number the workflow's header gives is the tests' own: 300,000 + 200,000 + 16 x (40,000 + 20,000), less the spellings
    counts = [int(n.replace("_", "")) for n in re.findall(r"for _ in 0\.\.([\d_]+) \{", tests)]
    assert counts == [300_000, 200_000, 40_000, 20_000] and "for seed in 1..=16u64" in tests
    assert 300_000 + 200_000 + 16 * (40_000 + 20_000) == 1_460_000 and "1.46 million inputs" in WORKFLOW.read_text(encoding="utf-8")
    cache = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("Swatinem/rust-cache@"))
    assert cache["with"]["workspaces"].split() == ["crates/knos-oidc-interface", "crates/knos-pay-interface", "programs-v2/knos_oidc/fuzz"]
    assert "tests/test_pay_interface.py" in run and (ROOT / "tests" / "test_pay_interface.py").is_file()
    assert (ROOT / "crates" / "knos-pay-interface" / "Cargo.lock").is_file()


def _pin(action: str) -> str:
    pins = json.loads((ROOT / "scripts" / "action_pins.json").read_text(encoding="utf-8"))["pins"]
    return f"{action.split('@')[0]}@{pins[action]}"


def test_clippy_denies_every_warning_on_the_second_deployment_and_the_interface_crate_on_a_named_rust_release():
    job = _doc()["jobs"]["clippy"]
    assert "needs" not in job and "if" not in job
    release = job["env"]["RUSTUP_TOOLCHAIN"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", release), "a release, not `stable`: a new lint must not fail an old push"
    steps = job["steps"]
    install = next(i for i, s in enumerate(steps) if "rustup toolchain install" in str(s.get("run", "")))
    assert '"$RUSTUP_TOOLCHAIN"' in steps[install]["run"] and "--component clippy" in steps[install]["run"]
    cache = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("Swatinem/rust-cache@"))
    lint = next(i for i, s in enumerate(steps) if "cargo clippy" in str(s.get("run", "")))
    assert install < cache < lint                    # the cache key reads the release, so the release comes first
    assert steps[cache]["uses"] == _pin("Swatinem/rust-cache@v2") and steps[cache]["with"]["save-if"] == "${{ github.ref == 'refs/heads/main' }}"
    assert steps[cache]["with"]["workspaces"] == "programs-v2\ncrates/knos-oidc-interface\n"
    assert "${{ env.RUSTUP_TOOLCHAIN }}" in steps[cache]["with"]["shared-key"]
    commands = [ln.strip() for ln in steps[lint]["run"].splitlines() if ln.strip()]
    assert commands == [
        "(cd crates/knos-oidc-interface && cargo clippy --locked --all-targets --all-features -- -D warnings)",
        "(cd programs-v2 && cargo clippy --locked --all-targets -- -D warnings)"]
    for crate in ("crates/knos-oidc-interface", "programs-v2"):
        assert (ROOT / crate / "Cargo.lock").is_file()            # --locked needs one
    assert not [a for a in ("allow(", "-A ") if a in steps[lint]["run"]]     # nothing is let through on the command line


def test_the_verifiers_two_targets_are_fuzzed_nightly_for_five_minutes_each_and_the_job_skips_cleanly_without_them():
    from _ghexpr import runs
    doc = _doc()
    job = doc["jobs"]["fuzz-claims"]
    assert "cron" in doc["on"]["schedule"][0] and "workflow_dispatch" in doc["on"] and "needs" not in job
    # nightly and by hand only: a push (or a pull request) never waits for five minutes of fuzzing
    for event, runs_it in (("schedule", True), ("workflow_dispatch", True), ("push", False), ("pull_request", False)):
        assert runs(job["if"], {"github": {"event_name": event, "ref": "refs/heads/main"}}) is runs_it, event
    assert re.fullmatch(r"nightly-\d{4}-\d{2}-\d{2}", job["env"]["FUZZ_TOOLCHAIN"])      # dated: a night can be reproduced
    assert re.fullmatch(r"\d+\.\d+\.\d+", job["env"]["CARGO_FUZZ"]) and job["timeout-minutes"] >= 25      # two targets of 300 seconds, and the build
    steps = job["steps"]
    guard = "hashFiles('programs-v2/knos_oidc/fuzz/Cargo.toml') != ''"
    script = next(s for s in steps if "fuzz_nightly.sh" in str(s.get("run", "")))
    assert script["run"] == "bash scripts/fuzz_nightly.sh 300" and "if" not in script   # 300 seconds each; the script itself says "no target"
    fuzz_dir = ROOT / "programs-v2" / "knos_oidc" / "fuzz"
    targets = sorted(p.stem for p in (fuzz_dir / "fuzz_targets").glob("*.rs"))
    assert targets == ["claims", "rsa_verify"] and all(f'name = "{t}"\npath = "fuzz_targets/{t}.rs"' in (fuzz_dir / "Cargo.toml").read_text(encoding="utf-8") for t in targets)
    # each target has committed seeds, which the script hands the fuzzer beside the corpus (they are read, never written)
    assert all(any((fuzz_dir / "seeds" / t).iterdir()) for t in targets) and "seeds" not in (fuzz_dir / ".gitignore").read_text(encoding="utf-8").split()
    # until the target exists every step that takes time is skipped, and the ones after still run
    for step in steps:
        if step is script or str(step.get("uses", "")).startswith(("actions/checkout@", "actions/upload-artifact@")):
            continue
        assert step.get("if") == guard, step
    uploads = {s["with"]["name"]: s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")}
    assert uploads["fuzz-claims"]["with"]["path"].split() == ["fuzz.json", "fuzz_targets.jsonl"] and uploads["fuzz-claims"]["if"] == "always()"
    # the corpus is published with the counts, crash or none; nothing in the job commits or pushes
    assert uploads["fuzz-claims-corpus"]["with"]["path"] == "programs-v2/knos_oidc/fuzz/corpus" and uploads["fuzz-claims-corpus"]["if"] == "always()"
    assert set(uploads) == {"fuzz-claims", "fuzz-claims-corpus", "fuzz-claims-crash"} and "git " not in _runs(job) and "permissions" not in job
    assert uploads["fuzz-claims-crash"]["with"]["path"] == "programs-v2/knos_oidc/fuzz/artifacts" and uploads["fuzz-claims-crash"]["if"] == "failure()"
    assert all(u["with"]["if-no-files-found"] == "ignore" and u["uses"] == _pin("actions/upload-artifact@v7") for u in uploads.values())
    # the corpus is kept from one night to the next, and no other job here is on a nightly compiler
    corpus = next(s for s in steps if s.get("uses") == _pin("actions/cache@v6"))
    assert corpus["with"]["path"] == "programs-v2/knos_oidc/fuzz/corpus" and corpus["with"]["restore-keys"] == "fuzz-claims-corpus-"
    assert "${{ github.run_id }}" in corpus["with"]["key"]
    # no other job here names a nightly compiler (the Kani job's verifier carries the one it was built with)
    assert not [name for name, other in doc["jobs"].items() if name != "fuzz-claims" and "nightly" in str(other)]


def test_every_kani_harness_of_knos_pay_runs_in_a_job_and_none_is_let_off_by_its_time():
    """Every `#[kani::proof]` of programs-v2/knos_pay/src/proofs.rs is named by exactly one Kani step of program.yml
    (`--exact --harness`), so a harness added, renamed or left out is found here. The fee-bounds harness, which did not
    finish in 30 minutes (run 37569582253), has a job of its own with the hosted runner's 360 minutes; its step stops
    first and fails, and nothing there lets a failure or the limit pass."""
    from _ghexpr import runs
    doc = _doc()
    proofs = (ROOT / "programs-v2" / "knos_pay" / "src" / "proofs.rs").read_text(encoding="utf-8")
    harnesses = re.findall(r"#\[kani::proof\]\s*(?:#\[[^\]]*\]\s*)*fn (\w+)\(", proofs)
    assert len(harnesses) == proofs.count("#[kani::proof]") >= 5
    named: list[str] = []
    for name, job in doc["jobs"].items():
        for step in job.get("steps", []):
            if "kani-github-action" in str(step.get("uses", "")) and step["with"]["working-directory"] == "programs-v2/knos_pay":
                args = step["with"]["args"].split()
                assert "--exact" in args and "--harness" in args, name          # by name, or a harness could hide in "every"
                # `--exact` takes the full path of a harness (Kani: "Please specify the fully-qualified name")
                full = [args[i + 1] for i, a in enumerate(args) if a == "--harness"]
                assert all(f.startswith("proofs::harness::") for f in full), name
                named += [f.removeprefix("proofs::harness::") for f in full]
                assert "continue-on-error" not in step and "continue-on-error" not in job, name
    assert sorted(named) == sorted(harnesses) and len(named) == len(set(named))
    fee = "an_orders_fee_is_between_its_floor_and_the_one_rate_for_every_amount"
    long = doc["jobs"]["kani-fee-bounds"]
    [step] = [s for s in long["steps"] if "kani-github-action" in str(s.get("uses", ""))]
    assert step["with"]["args"].split()[-2:] == ["--harness", f"proofs::harness::{fee}"] and step["with"]["args"].count("--harness") == 1
    assert long["timeout-minutes"] == 360 and step["timeout-minutes"] < long["timeout-minutes"] and "needs" not in long
    assert step["with"]["kani-version"] == doc["jobs"]["kani"]["steps"][1]["with"]["kani-version"]
    for event, runs_it in (("schedule", True), ("workflow_dispatch", True), ("push", False), ("pull_request", False)):
        assert runs(long["if"], {"github": {"event_name": event, "ref": "refs/heads/main"}}) is runs_it, event

def test_the_arithmetic_of_an_orders_money_is_proved_nightly_and_tested_at_random_on_every_push():
    from _ghexpr import runs
    doc = _doc()
    job = doc["jobs"]["kani"]
    assert "needs" not in job and job["timeout-minutes"] <= 30
    for event, runs_it in (("schedule", True), ("workflow_dispatch", True), ("push", False), ("pull_request", False)):
        assert runs(job["if"], {"github": {"event_name": event, "ref": "refs/heads/main"}}) is runs_it, event
    checkout, kani, cvc5, fees = job["steps"]
    # the fee's bounds, on the program's own lines copied out as text: the Kani the step before installed, every
    # harness of that crate alone within its limit, and a harness that fails or times out fails the step by name
    assert fees["run"] == "python3 scripts/kani_fee_record.py --ci" and fees["timeout-minutes"] <= 15 and "continue-on-error" not in fees
    spec = importlib.util.spec_from_file_location("kani_fee_record", ROOT / "scripts" / "kani_fee_record.py")
    rec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rec)
    assert len(rec.harnesses()) * rec.LIMIT <= fees["timeout-minutes"] * 60 and str(rec.LIMIT) in fees["name"]
    # the solver of the exact bound: one named version, held to a hash before it runs
    assert re.search(r"releases/download/cvc5-(\d+\.\d+\.\d+)/cvc5-Linux-x86_64-static\.zip", cvc5["run"]).group(1) in cvc5["name"]
    assert re.search(r'echo "[0-9a-f]{64}  \$RUNNER_TEMP/cvc5\.zip" \| sha256sum -c -', cvc5["run"]) and '>> "$GITHUB_PATH"' in cvc5["run"]
    assert "#[kani::proof]" in (ROOT / "programs-v2" / "fee_proofs" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert checkout["uses"] == _pin("actions/checkout@v7") and kani["uses"] == _pin("model-checking/kani-github-action@v1.1")
    # a named version of the verifier, in the crate whose arithmetic it proves; a harness that fails fails the step
    assert re.fullmatch(r"\d+\.\d+\.\d+", kani["with"]["kani-version"]) and kani["with"]["working-directory"] == "programs-v2/knos_pay"
    assert set(kani["with"]) == {"kani-version", "working-directory", "args"}
    crate = ROOT / "programs-v2" / "knos_pay"
    proofs, lib = (crate / "src" / "proofs.rs").read_text(encoding="utf-8"), (crate / "src" / "lib.rs").read_text(encoding="utf-8")
    # the proofs are in no build of the program: one line of lib.rs, the last, behind cfg(kani) or cfg(test)
    assert lib.rstrip().splitlines()[-1].startswith("#[cfg(any(kani, test))] mod proofs;") and lib.count("mod proofs") == 1
    harnesses = re.findall(r"#\[kani::proof\]\n(?:    #\[kani::unwind\(\d+\)\]\n)?    fn (\w+)\(\)", proofs)
    assert harnesses == ["the_remainder_of_a_share_is_never_more_than_the_remainder", "an_orders_fee_is_between_its_floor_and_the_one_rate_for_every_amount",
                         "a_payment_takes_its_share_of_the_amount_and_of_the_fee_and_the_last_one_empties_the_order",
                         "what_a_funder_puts_in_is_what_the_payees_the_relayer_and_the_fee_owner_take_out",
                         "an_order_that_has_paid_nothing_has_given_out_none_of_its_fee"]
    assert proofs.count("#[kani::proof]") == len(harnesses) and "#[cfg(kani)]\nmod harness {" in proofs
    # what a harness assumes instead of proving is said where the file says what is proved, and tested at random
    assert proofs.count("kani::assume(fee_before <= fee_after && fee_after <= fee && (!last || fee_after == fee));") == 1
    assert "WHAT IS ASSUMED" in proofs and "WHAT IS PROVED" in proofs and "WHAT IS NOT" in proofs
    # the same properties on inputs made from fixed seeds, in the programs' own `cargo test`, which every push runs
    tests = re.findall(r"    #\[test\]\n    fn (\w+)\(\)", proofs)
    assert tests == ["the_model_is_the_arithmetic_of_the_source", "an_orders_fee_is_its_one_rate_above_its_floor_and_a_share_is_never_more_than_the_whole",
                     "the_payees_shares_add_up_to_the_payment", "the_fee_an_order_has_given_out_grows_with_what_it_paid_and_ends_at_the_whole_fee",
                     "nothing_is_created_or_lost_over_the_life_of_an_order",
                     "a_standing_order_gives_out_its_fee_with_its_amount_and_keeps_the_rest_for_the_refund"]
    assert _legs(doc["jobs"]["build-test"])["second"]["cargo-test"] == "programs-v2"
    assert 'cd "$CARGO_TEST" && cargo test --release' in _runs(doc["jobs"]["build-test"])
    # the lint that would refuse `cfg(kani)` is off for this crate, so clippy's -D warnings still passes
    assert 'unexpected_cfgs = { level = "allow" }' in (crate / "Cargo.toml").read_text(encoding="utf-8")


# ---- the nightly fuzz script, with a stand-in for cargo-fuzz ----------------------------------------------------------

CARGO_FUZZ = """#!/bin/sh
# cargo +<toolchain> fuzz list | fuzz run <target> <corpus> [<seeds>] -- <libFuzzer arguments>, as far as the script
# can tell. Like libFuzzer it keeps what it finds in the first folder: here three files, or FAKE_FOUND of them.
echo "$@" >> "$FAKE_LOG"
[ "$2" = fuzz ] || exit 9
case "$3" in
  list) printf '%s\n' $FAKE_TARGETS ;;
  run)
    target=$4
    echo "INFO: Running with entropic power schedule"
    [ "$FAKE_MODE" = nobuild ] && { echo "error: could not compile $target" >&2; exit 101; }
    [ -d "$5" ] || { echo "no corpus folder $5 in $PWD" >&2; exit 102; }
    for i in $(seq 1 "${FAKE_FOUND:-3}"); do echo x > "$5/found-$i"; done
    [ "$FAKE_MODE" = crashes-in-keys ] && [ "$target" = keys ] && FAKE_MODE=crash
    echo "#9\tDONE cov: 14 ft: 15 corp: 1/1b exec/s: 3 rss: 40Mb"
    [ "$FAKE_MODE" = crash ] && echo "Test unit written to ./artifacts/$target/crash-0123abcd"
    echo "stat::number_of_executed_units: ${FAKE_RUNS:-1000}"
    echo "stat::average_exec_per_sec:     333"
    [ "$FAKE_MODE" = crash ] && exit 77
    exit 0 ;;
esac
"""


@pytest.fixture()
def fuzz(tmp_path):
    """scripts/fuzz_nightly.sh in a tree shaped like the repository, with a `cargo` that fuzzes nothing and says what a
    real run says. `go(mode=..., targets=..., runs=..., seconds=...)` returns (result, parsed fuzz.json or None, summary)."""
    bash = _bash()
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "fuzz_nightly.sh", root / "scripts" / "fuzz_nightly.sh")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "cargo").write_text(CARGO_FUZZ, encoding="utf-8")
    (fake / "cargo").chmod(0o755)

    def go(mode: str = "", targets: tuple[str, ...] = ("claims",), runs: int = 1000, seconds: str = "300", present: bool = True):
        crate = root / "programs-v2" / "knos_oidc"
        if present:
            (crate / "fuzz" / "fuzz_targets").mkdir(parents=True, exist_ok=True)
            (crate / "fuzz" / "Cargo.toml").write_text("[package]\nname = 'knos-oidc-fuzz'\n", encoding="utf-8")
            for name in targets:
                (crate / "fuzz" / "fuzz_targets" / f"{name}.rs").write_text("// target\n", encoding="utf-8")
        for stale in ("fuzz.json", "summary.md", "calls"):
            (root / stale).unlink(missing_ok=True)
        shutil.rmtree(crate / "fuzz" / "corpus", ignore_errors=True)
        env = {**os.environ, "PATH": str(fake) + os.pathsep + os.environ["PATH"], "FAKE_MODE": mode, "FAKE_RUNS": str(runs),
               "FAKE_TARGETS": " ".join(targets), "FAKE_LOG": str(root / "calls"), "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
               "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "77", "GITHUB_REPOSITORY": "o/r", "GITHUB_SERVER_URL": "https://github.com",
               "FUZZ_TOOLCHAIN": "nightly-2026-10-01"}
        r = subprocess.run([bash, "scripts/fuzz_nightly.sh", *([seconds] if seconds else [])], cwd=str(root), env=env, capture_output=True, text=True)
        out = json.loads((root / "fuzz.json").read_text(encoding="utf-8")) if (root / "fuzz.json").exists() else None
        summary = (root / "summary.md").read_text(encoding="utf-8") if (root / "summary.md").exists() else ""
        calls = (root / "calls").read_text(encoding="utf-8").splitlines() if (root / "calls").exists() else []
        return r, out, summary, calls
    go.root = root
    return go


def test_the_fuzz_script_counts_the_inputs_the_fuzzer_reports_and_says_so_three_times(fuzz):
    r, out, summary, calls = fuzz(runs=61_230)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out["executions"] == 61_230 and out["seconds"] == 300 and out["crashed"] is False and out["target"] == "claims"
    assert out["commit"] == "a" * 40 and out["run"] == "https://github.com/o/r/actions/runs/77"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", out["date"])
    assert "libFuzzer" in out["source"] and "300 seconds" in out["source"] and "aaaaaaa" in out["source"] and out["run"] in out["source"]
    # the line of the target: what it tried, the files in its corpus, its crashes; the same line in fuzz_targets.jsonl
    [line] = out["targets"]
    assert line == {"target": "claims", "executions": 61_230, "corpus": 3, "crashes": 0, "seconds": 300, "commit": "a" * 40, "run": out["run"], "date": line["date"]}
    assert [json.loads(ln) for ln in (fuzz.root / "fuzz_targets.jsonl").read_text(encoding="utf-8").splitlines()] == [line]
    assert "| claims | 300 | 61230 | 3 | none |" in summary
    # the nightly toolchain, the corpus folder (no seeds here: the folder is not there), and libFuzzer's own time limit
    assert calls == ["+nightly-2026-10-01 fuzz list",
                     "+nightly-2026-10-01 fuzz run claims fuzz/corpus/claims -- -max_total_time=300 -print_final_stats=1 -rss_limit_mb=2048"]


def test_with_two_targets_each_gets_the_whole_time_its_own_line_and_its_seeds(fuzz):
    seeds = fuzz.root / "programs-v2" / "knos_oidc" / "fuzz" / "seeds" / "keys"
    seeds.mkdir(parents=True)
    (seeds / "one").write_bytes(b"seed")
    lines = fuzz.root / "fuzz_targets.jsonl"
    lines.unlink(missing_ok=True)
    r, out, summary, calls = fuzz(targets=("claims", "keys"), runs=500, seconds="300")
    assert r.returncode == 0, r.stdout + r.stderr
    # at the top, the claim parser's own count (what bench_docs takes as claim_parser_executions); the sum beside it
    assert out["target"] == "claims" and out["executions"] == 500 and out["total_executions"] == 1000 and out["all_targets"] == "claims,keys"
    assert [(t["target"], t["executions"], t["corpus"], t["crashes"], t["seconds"]) for t in out["targets"]] == [("claims", 500, 3, 0, 300), ("keys", 500, 3, 0, 300)]
    assert "target claims," in out["source"]
    runs = [c for c in calls if " fuzz run " in c]
    assert [c.split(" -- ")[1].split()[0] for c in runs] == ["-max_total_time=300"] * 2
    assert runs[0].split(" -- ")[0].endswith("fuzz run claims fuzz/corpus/claims") and runs[1].split(" -- ")[0].endswith("fuzz run keys fuzz/corpus/keys fuzz/seeds/keys")
    assert (seeds / "one").read_bytes() == b"seed" and sorted(p.name for p in seeds.iterdir()) == ["one"]      # read, never written
    assert "| claims | 300 | 500 | 3 | none |" in summary and "| keys | 300 | 500 | 3 | none |" in summary
    # a second run appends its lines: the file is a history, fuzz.json is the last run
    fuzz(targets=("claims", "keys"), runs=7)
    kept = [json.loads(ln) for ln in lines.read_text(encoding="utf-8").splitlines()]
    assert [(k["target"], k["executions"]) for k in kept] == [("claims", 500), ("keys", 500), ("claims", 7), ("keys", 7)]


def test_the_fuzz_script_defaults_to_five_minutes_and_refuses_what_is_not_a_number_of_seconds(fuzz):
    r, out, _summary, calls = fuzz(seconds="")
    assert r.returncode == 0 and out["seconds"] == 300 and "-max_total_time=300" in calls[-1]
    for bad in ("five", "0", "-5", "1.5"):
        r, out, _summary, calls = fuzz(seconds=bad)
        assert r.returncode == 2 and out is None and not calls and "whole number of seconds" in r.stdout, bad


def test_the_fuzz_script_skips_cleanly_while_the_target_is_not_there(fuzz):
    fuzz_dir = fuzz.root / "programs-v2" / "knos_oidc" / "fuzz"
    for kind in ("no fuzz directory", "a fuzz directory with no target in it"):
        if kind != "no fuzz directory":
            (fuzz_dir / "fuzz_targets").mkdir(parents=True)
            (fuzz_dir / "Cargo.toml").write_text("[package]\nname = 'knos-oidc-fuzz'\n", encoding="utf-8")
        r, out, summary, calls = fuzz(present=False)
        assert r.returncode == 0 and out is None and not calls, (kind, r.stdout, r.stderr)   # green, no file, cargo never called
        assert "no fuzz target" in summary and "nothing was fuzzed" in summary, kind


def test_an_input_that_fails_a_target_fails_the_job_is_still_counted_and_the_next_target_still_runs(fuzz):
    r, out, summary, _calls = fuzz(mode="crash", runs=42)
    assert r.returncode == 1
    assert out["crashed"] is True and out["executions"] == 42 and out["targets"][0]["crashes"] == 1
    assert "yes: the input is in the artifact" in summary and "found an input that fails: claims." in summary
    # the second of two targets finds one: the first is counted as clean, and the script says which one failed
    r, out, summary, calls = fuzz(mode="crashes-in-keys", targets=("claims", "keys"), runs=9)
    assert r.returncode == 1 and out["crashed"] is True and [t["crashes"] for t in out["targets"]] == [0, 1]
    assert "| claims | 300 | 9 | 3 | none |" in summary and "| keys | 300 | 9 | 3 | yes: the input is in the artifact |" in summary
    assert "found an input that fails: keys." in summary and len([c for c in calls if " fuzz run " in c]) == 2


def test_a_run_that_did_not_finish_writes_no_count(fuzz):
    r, out, summary, _calls = fuzz(mode="nobuild")
    assert r.returncode == 1 and out is None
    assert "did not finish" in summary and "No count was written" in summary


def test_the_numbers_in_fuzz_json_are_what_bench_docs_takes_for_a_number_only_a_run_can_measure(fuzz, tmp_path):
    """`bench_docs.py --set NAME=NUMBER --source TEXT` with the file's `executions` and `source`: kept in docs/bench.json
    under release.<name>, with where it was measured."""
    spec = importlib.util.spec_from_file_location("bench_docs", ROOT / "scripts" / "bench_docs.py")
    bd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bd)
    assert bd.SLOTS["claim_parser_executions"][1] is None        # no stats.json path: only a run can give it
    _r, out, _summary, _calls = fuzz(runs=987_654)
    for rel in ("docs/bench.json", "docs/facts.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes((ROOT / rel).read_bytes())
    bd.fill(given={"claim_parser_executions": (out["executions"], out["source"])}, root=tmp_path)
    kept = json.loads((tmp_path / "docs" / "bench.json").read_text(encoding="utf-8"))["release"]["claim_parser_executions"]
    assert kept == {"value": 987_654, "source": out["source"]}


# ---- the build scripts, with a stand-in for cargo -------------------------------------------------------------------

CARGO = """#!/bin/sh
# cargo build-sbf [arguments], as far as a build script can tell: it writes <target>/deploy/<crate>.so (here a file
# that holds the arguments of the build), and like the real one it leaves a file that is already there and newer.
[ "$1" = build-sbf ] || exit 9
shift
crate=$(basename "$PWD")
if [ -n "${CARGO_TARGET_DIR:-}" ]; then target=$CARGO_TARGET_DIR; elif grep -q workspace ../Cargo.toml 2>/dev/null; then target=../target; else target=target; fi
mkdir -p "$target/deploy"
[ -e "$target/deploy/$crate.so" ] || echo "$crate $*" > "$target/deploy/$crate.so"
"""


@pytest.fixture()
def tree(tmp_path):
    """The build scripts in a tree shaped like the repository, and a `cargo` that records what it is asked to build."""
    bash = _bash()
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for script in ("build_programs.sh", "build_programs_v2.sh"):
        shutil.copy(ROOT / "scripts" / script, root / "scripts" / script)
    (root / "tests" / "fixtures").mkdir(parents=True)
    (root / "tests" / "fixtures" / "SHA256SUMS").write_text(f"{'0' * 64}  docs/other.json\n", encoding="utf-8")
    for ws in ("programs", "programs-v2"):
        (root / ws).mkdir()
        crates = ("knos_oidc", "knos_pay") + (("knos_passkey",) if ws == "programs-v2" else ())
        (root / ws / "Cargo.toml").write_text(f'[workspace]\nmembers = {json.dumps(list(crates))}\n', encoding="utf-8")
        for crate in crates:
            (root / ws / crate).mkdir()
            (root / ws / crate / "Cargo.toml").write_text(f'[package]\nname = "{crate}"\n', encoding="utf-8")
    (root / "programs-v2" / "knos_meter").mkdir()
    (root / "programs-v2" / "knos_meter" / "Cargo.toml").write_text('[package]\nname = "knos_meter"\n', encoding="utf-8")
    for example in ("oidc_gate", "cpi_fund", "workflow_vault", "upgrade_gate", "reader_template"):
        (root / "examples" / example).mkdir(parents=True)
        (root / "examples" / example / "Cargo.toml").write_text(f'[package]\nname = "{example}"\n', encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "cargo").write_text(CARGO, encoding="utf-8")
    (fake / "cargo").chmod(0o755)

    def build(script: str, *args: str, target: Path | None = None) -> subprocess.CompletedProcess:
        env = {**os.environ, "PATH": str(fake) + os.pathsep + os.environ["PATH"]}
        env.pop("CARGO_TARGET_DIR", None)
        if target:
            env["CARGO_TARGET_DIR"] = str(target)
        return subprocess.run([bash, str(root / "scripts" / script), *args], env=env, capture_output=True, text=True)
    return root, build


def _built(folder: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8").strip() for p in sorted(folder.glob("*.so"))}


def test_the_first_deployments_script_builds_its_test_binaries_and_leaves_the_real_builds_to_deploy(tree, tmp_path):
    root, build = tree
    want = {"knos_oidc_test.so": "knos_oidc --features testkeys", "knos_pay_nodevnet.so": "knos_pay --no-default-features",
            "knos_pay_test.so": "knos_pay", "oidc_gate_test.so": "oidc_gate"}
    deploy = root / "programs" / "target" / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "knos_oidc.so").write_text("left by a build before this one", encoding="utf-8")   # cargo would keep it
    r = build("build_programs.sh")
    assert r.returncode == 0, r.stderr
    assert _built(root / "tests" / "fixtures") == want
    # what is left in target/deploy is the real build of each program, and the second deployment was not touched
    assert _built(deploy) == {"knos_oidc.so": "knos_oidc", "knos_pay.so": "knos_pay"}
    assert not (root / "programs-v2" / "target").exists()
    # again, where the last run left its files: every binary is still the build it is named for
    assert build("build_programs.sh").returncode == 0 and _built(root / "tests" / "fixtures") == want
    # with CARGO_TARGET_DIR, cargo writes there and the script reads there
    for made in ("programs/target", "examples/oidc_gate/target", "tests/fixtures/oidc_gate_test.so"):
        path = root / made
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    shared = tmp_path / "shared target"
    r = build("build_programs.sh", target=shared)
    assert r.returncode == 0, r.stderr
    assert _built(shared / "deploy") == {"knos_oidc.so": "knos_oidc", "knos_pay.so": "knos_pay", "oidc_gate.so": "oidc_gate"}
    assert _built(root / "tests" / "fixtures") == want and not (root / "programs" / "target").exists()


def test_the_second_deployments_script_builds_test_binaries_with_test_keys_and_leaves_builds_without_them(tree):
    root, build = tree
    for run in (1, 2):                                                       # the second run starts where the first ended
        r = build("build_programs_v2.sh")
        assert r.returncode == 0, r.stderr
        got = _built(root / "tests" / "fixtures")
        # its binaries carry _v2_ (the meter's, which the first deployment never had, does not); the first's are not its business
        assert got and all("_v2_" in name or name == "knos_meter_test.so" for name in got), got
        for name, how in got.items():
            assert how.split()[0] == name.split("_v2_")[0].removesuffix("_test.so"), (name, how)
            # a binary named real is the program as it is deployed; every other one is a test build
            assert ("--features testkeys" in how) == ("_real" not in name), (name, how)
        assert {"knos_oidc_v2_test.so", "knos_pay_v2_test.so", "knos_pay_v2_nodevnet.so", "knos_meter_test.so", "knos_passkey_v2_real.so"} <= set(got)
        assert "--no-default-features" in got["knos_pay_v2_nodevnet.so"] and "--no-default-features" not in got["knos_pay_v2_test.so"]
        # the example programs built on this deployment are built here too, each as it would be deployed, into a target of their own
        assert {"cpi_fund_v2_real.so", "workflow_vault_v2_real.so", "upgrade_gate_v2_real.so", "reader_template_v2_real.so"} <= set(got)
        assert set(_built(root / "examples" / "target" / "deploy")) == {"cpi_fund.so", "workflow_vault.so", "upgrade_gate.so", "reader_template.so"}
        # what is left to try on a cluster trusts no test key, and the devnet escrow has its faucet
        assert _built(root / "programs-v2" / "target" / "deploy") == {"knos_oidc.so": "knos_oidc", "knos_pay.so": "knos_pay", "knos_meter.so": "knos_meter", "knos_passkey.so": "knos_passkey"}
        # each binary it built is pinned by its hash, once, and the other pins are as they were
        sums = dict(reversed(line.split("  ", 1)) for line in (root / "tests" / "fixtures" / "SHA256SUMS").read_text(encoding="utf-8").splitlines())
        assert sums.pop("docs/other.json") == "0" * 64
        assert sums == {f"tests/fixtures/{name}": hashlib.sha256((root / "tests" / "fixtures" / name).read_bytes()).hexdigest() for name in got}
    assert not (root / "programs" / "target").exists()


def test_the_rebuild_a_person_is_told_to_run_is_the_command_program_yml_and_deploy_v2_run():
    """The verified hashes are program.yml's builds. ASSURANCE.md, deploy_v2.sh (the build it runs, the step it describes
    and the command its UNGATED line hands the members) and build_programs_v2.sh's note must say the same command, or a
    verifier rebuilds something else. Every mount is an absolute path: solana-verify finds the manifest with `find
    <mount>` and strips the mount's text from each path it finds, so a mount of "." strips every dot
    (./programs-v2/knos_pay/Cargo.toml becomes /programs-v2/knos_pay/Cargotoml) and cargo refuses it."""
    import shlex
    doc = _doc()
    image = doc["env"]["VERIFY_IMAGE"]
    run = _runs(doc["jobs"]["verified-build"])
    ci = next(line.strip() for line in run.splitlines() if line.strip().startswith('solana-verify build "$GITHUB_WORKSPACE" '))

    def words(command: str, root: str, name: str) -> list[str]:
        return shlex.split(command.replace(root, "<repo>").replace("$WORKSPACE", "programs-v2").replace("$VERIFY_IMAGE", image)
                           .replace("$PROGRAM", "<name>").replace("$name", "<name>").replace("<name>", name))
    want = {name: words(ci, "$GITHUB_WORKSPACE", name) for name in ("knos_oidc", "knos_pay")}
    assert want["knos_pay"] == ["solana-verify", "build", "<repo>", "--workspace-path", "<repo>/programs-v2", "--library-name",
                                "knos_pay", "--base-image", image]
    script = (ROOT / "scripts" / "deploy_v2.sh").read_text(encoding="utf-8")
    assert f'VERIFY_IMAGE="${{KNOS_VERIFY_IMAGE:-{image}}}"' in script
    built = [line.strip().split(" || ")[0] for line in script.splitlines() if line.strip().startswith("solana-verify build ")]
    assert len(built) == 1 and words(built[0], "$ROOT", "knos_pay") == want["knos_pay"]
    # what the UNGATED line prints, as bash prints it
    echo = next(line.strip() for line in script.splitlines() if "UNGATED: the members have only their own rebuild" in line)
    bash = shutil.which("bash")
    if bash and os.name != "nt":
        said = subprocess.run([bash, "-c", f"name=knos_oidc; want=abc; VERIFY_IMAGE={shlex.quote(image)}; {echo}"],
                              capture_output=True, text=True, timeout=30).stdout
        told = said[said.index("solana-verify build"):].rstrip().rstrip(".").rstrip(")")
        assert words(told, "$PWD", "knos_oidc") == want["knos_oidc"], said
    # the documented commands, one per program, run from the repository's root
    text = (ROOT / "docs" / "ASSURANCE.md").read_text(encoding="utf-8")
    documented = [line for line in text.splitlines() if line.startswith("solana-verify build")]
    assert [words(line, "$PWD", "")[6] for line in documented] == ["knos_pay", "knos_oidc"]
    assert all(words(line, "$PWD", "") == want[words(line, "$PWD", "")[6]] for line in documented), documented
    # the notes in the scripts, which name the program <name>
    step = script[script.index("#   2 build"):script.index("#   3 deploy")]
    notes = {"deploy_v2.sh": " ".join(line.lstrip("# ").strip() for line in step.splitlines()),
             "build_programs_v2.sh": (ROOT / "scripts" / "build_programs_v2.sh").read_text(encoding="utf-8")}
    for where, note in notes.items():
        assert note.count("solana-verify build") == 1, where
        assert 'solana-verify build "$PWD" --workspace-path "$PWD/programs-v2" --library-name <name>' in note, where
    for text in (script, notes["build_programs_v2.sh"], (ROOT / "docs" / "ASSURANCE.md").read_text(encoding="utf-8"), run):
        assert "solana-verify build ." not in text and "solana-verify build programs" not in text
