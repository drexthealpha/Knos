"""scripts/schedule_upgrade.sh and the Node packages scripts/governance.mjs imports: the run holds node_modules to
package.json BEFORE it sends anything, installs what is missing, and stops with nothing sent and one plain line when it
cannot. On 6 October 2026 a scheduled run found node_modules gone and executed nothing; this is that run, with
stand-ins for node's packages, npm, the timers and knos (tests/test_schedule_upgrade.py holds the rest of the script)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "schedule_upgrade.sh"
pytestmark = pytest.mark.skipif(os.name == "nt" or not shutil.which("bash") or not shutil.which("node"), reason="runs the script with bash and node")

PINNED = {"@solana/web3.js": "1.99.0", "@sqds/multisig": "2.1.4"}
STAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC"
# node: governance.mjs is a stand-in that loads the packages as the real one does (so a run with none fails as the real
# run failed) and writes down what it was asked; everything else is the real node
NODE = ('#!/bin/sh\ncase "$1" in */governance.mjs)\n'
        '  ( cd "$KNOS_NODE_DIR" && {node} --input-type=module -e \'await import("@solana/web3.js"); await import("@sqds/multisig");\' ) || exit 1\n'
        '  echo "node governance $2 $3 $4" >> "$CALLS"; echo "on chain now: proposal $4 of the upgrade multisig is executed"; exit 0;; esac\nexec {node} "$@"\n')
# npm ci: writes each pinned package where node finds it, unless NPM_FAILS says the registry did not answer
NPM = ('#!/bin/sh\necho "npm $*" >> "$CALLS"\n[ -z "$NPM_FAILS" ] || { echo "npm error code ENOTFOUND registry.npmjs.org" >&2; exit 1; }\n'
       'at="$3"\nfor p in "@solana/web3.js:1.99.0" "@sqds/multisig:2.1.4"; do n="${p%:*}"; v="${p##*:}"; mkdir -p "$at/node_modules/$n"\n'
       '  printf \'{"name":"%s","version":"%s","main":"index.js"}\' "$n" "$v" > "$at/node_modules/$n/package.json"; echo "module.exports = {};" > "$at/node_modules/$n/index.js"; done\n'
       'echo "added 2 packages"\n')


@pytest.fixture()
def box(tmp_path):
    """A key folder with a schedule for proposals 7 and 8, a package folder with package.json and NO node_modules, and a
    PATH that holds the stand-ins first."""
    keys, bin_dir, deps = tmp_path / "keys", tmp_path / "bin", tmp_path / "pkg"
    keys.mkdir(), bin_dir.mkdir(), deps.mkdir()
    (deps / "package.json").write_text(json.dumps({"type": "module", "dependencies": PINNED, "optionalDependencies": {"@solana/surfpool": "1.6.0"}}), encoding="utf-8")
    real = shutil.which("node")
    for name, body in {"node": NODE.replace("{node}", real), "npm": NPM, "knos": '#!/bin/sh\necho "knos $*" >> "$CALLS"\necho "12 of 12 checks pass"\n',
                       "systemd-run": '#!/bin/sh\necho "systemd-run $*" >> "$CALLS"\n', "systemctl": '#!/bin/sh\nexit 0\n'}.items():
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    for name in ("payer.json", "member-1.json", "member-2.json"):
        (keys / name).write_text('"a-file-that-stands-for-a-key"', encoding="utf-8")
    at = int(time.time()) + 172_800
    (keys / "upgrade-schedule.json").write_text(json.dumps({"rpc": "https://api.devnet.solana.com", "executable_from": at, "run_at": at + 600, "proposals": [
        {"program": "knos_oidc", "index": 7, "hash": "7c" * 32}, {"program": "knos_pay", "index": 8, "hash": "27" * 32}]}), encoding="utf-8")
    calls = tmp_path / "calls"
    calls.write_text("", encoding="utf-8")
    kernel = tmp_path / "osrelease"
    kernel.write_text("6.8.0-45-generic\n", encoding="utf-8")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "KNOS_KEYS": str(keys), "KNOS_NODE_DIR": str(deps), "CALLS": str(calls), "HOME": str(tmp_path), "TZ": "UTC",
           "KNOS_OSRELEASE": str(kernel), "KNOS_SCHTASKS": str(tmp_path / "no-windows" / "schtasks.exe")}

    def run(*args: str, **more: str):
        return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **more}, capture_output=True, text=True, encoding="utf-8")
    return keys, calls, deps, run, bin_dir


def _calls(calls: Path) -> list[str]:
    return calls.read_text(encoding="utf-8").splitlines()


def test_with_node_modules_missing_the_run_installs_the_pinned_packages_first_and_then_executes(box):
    keys, calls, deps, run, _ = box
    assert not (deps / "node_modules").exists()
    done = run("--run")
    assert done.returncode == 0, done.stderr
    # npm ci before any execution, without the optional packages; then both proposals in order, then knos status
    assert _calls(calls) == [f"npm ci --prefix {deps} --omit=optional --no-audit --no-fund", "node governance upgrade execute 7", "node governance upgrade execute 8", "knos status"]
    log = (keys / "upgrade-run.log").read_text(encoding="utf-8")
    assert log.index("packages: missing from") < log.index("packages: installed") < log.index("the scheduled upgrade run starts") < log.index("proposal 7 of the upgrade multisig is executed")
    assert "@solana/web3.js@1.99.0 @sqds/multisig@2.1.4" in log and "surfpool" not in log
    # every line the script itself writes carries the time
    own = [line for line in log.splitlines() if line.startswith(("====", "----")) or "packages:" in line]
    assert len(own) >= 9 and all(re.search(STAMP, line) for line in own), own
    assert "gh workflow run network.yml" in done.stdout
    # a second run finds them and installs nothing
    assert run("--run", "--force").returncode == 0 and sum(c.startswith("npm") for c in _calls(calls)) == 1
    assert "packages: every package" in (keys / "upgrade-run.log").read_text(encoding="utf-8").split("done: every proposal is executed")[1]


def test_packages_that_cannot_be_installed_stop_the_run_with_nothing_sent_and_one_plain_line(box):
    keys, calls, deps, run, bin_dir = box
    failed = run("--run", NPM_FAILS="1")
    assert failed.returncode == 1 and not [c for c in _calls(calls) if c.startswith(("node governance", "knos"))]
    last = failed.stderr.strip().splitlines()
    assert len(last) == 1 and last[0].startswith("stopped: the upgrade run did not start and nothing was sent: npm ci did not install @solana/web3.js@1.99.0 @sqds/multisig@2.1.4")
    log = (keys / "upgrade-run.log").read_text(encoding="utf-8")
    assert "ENOTFOUND registry.npmjs.org" in log and "the scheduled upgrade run CANNOT START" in log and "the scheduled upgrade run starts" not in log
    # no npm at all: the same, and the line says so
    (bin_dir / "npm").unlink()
    none = run("--run")
    assert none.returncode == 1 and none.stderr.strip().splitlines()[-1].startswith("stopped: the upgrade run did not start and nothing was sent: npm is not on PATH")
    assert not [c for c in _calls(calls) if c.startswith("node governance")]
    # a package at another version than the pinned one is missing too
    at = deps / "node_modules" / "@solana" / "web3.js"
    at.mkdir(parents=True)
    (at / "package.json").write_text('{"name":"@solana/web3.js","version":"1.98.0"}', encoding="utf-8")
    assert "@solana/web3.js@1.99.0 (found 1.98.0)" in run("--show").stdout
    # a proposal that is not executed ends the same way: exit 1 and one plain line
    (bin_dir / "node").write_text('#!/bin/sh\ncase "$1" in */governance.mjs) echo "refused: its time lock ends later" >&2; exit 1;; esac\nexec ' + shutil.which("node") + ' "$@"\n', encoding="utf-8")
    refused = run("--run", KNOS_UPGRADE_DEPS="0")
    assert refused.returncode == 1 and refused.stderr.strip().splitlines()[-1].startswith("stopped: 2 proposal(s) NOT executed; the log says why for each:")


def test_show_says_whether_the_packages_are_there_and_arranging_checks_at_once(box):
    keys, calls, deps, run, _ = box
    shown = run("--show")
    assert shown.returncode == 0 and "packages: MISSING from" in shown.stdout and "@solana/web3.js@1.99.0 @sqds/multisig@2.1.4" in shown.stdout
    assert not _calls(calls)                                        # --show installs nothing
    made = run("--with", "systemd")
    assert made.returncode == 0, made.stderr
    assert "packages: installed" in made.stdout and "A dry trigger, now: bash scripts/schedule_upgrade.sh --verify" in made.stdout
    assert f"KNOS_NODE_DIR={deps}" in (keys / "upgrade-run.env").read_text(encoding="utf-8")
    assert "packages: every package" in run("--show").stdout
    assert not [c for c in _calls(calls) if c.startswith("node governance")]


def test_verify_is_a_dry_trigger_in_a_bare_login_shell_that_ends_0_and_sends_nothing(box):
    keys, calls, deps, run, _ = box
    # nothing arranged: there is no environment for the run to start with
    early = run("--verify")
    assert early.returncode == 1 and "nothing is arranged" in early.stderr
    assert run("--with", "systemd").returncode == 0
    shutil.rmtree(deps / "node_modules")                            # gone again, as on 6 October
    before = len(_calls(calls))
    ok = run("--verify", PATH="/usr/bin:/bin")                      # the caller's PATH is not the run's: the env file's is
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "packages: installed" in ok.stdout and re.search(rf"verified at {STAMP}: the run would start. Schedule: proposals 7 8 ", ok.stdout)
    assert ok.stdout.rstrip().endswith("the packages load. Nothing was sent.") and "3 key files readable" in ok.stdout
    # the bare shell installed them again (it knows no $CALLS: what it did is on disk), and nothing was executed
    assert (deps / "node_modules" / "@sqds" / "multisig" / "package.json").is_file() and len(_calls(calls)) == before
    assert not (keys / "upgrade-run.log").exists()                  # a dry trigger writes no run into the log
    # a key file that is gone, or packages that cannot be had: exit 1, one plain last line
    (keys / "payer.json").rename(keys / "payer.gone")
    bad = run("--verify")
    assert bad.returncode == 1 and "cannot be read from a login shell" in bad.stderr and bad.stderr.strip().splitlines()[-1].startswith("stopped: the dry trigger failed")
