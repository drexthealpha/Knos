"""scripts/schedule_upgrade.sh with stand-ins for the three timers, node and knos: it arranges ONE run at the time the
schedule file names, with the first timer that works on the machine (under WSL the Windows task first), says how to
cancel it, and the run itself, started through a login shell with the key paths arranging wrote, executes each proposal
(only the build the schedule recorded for it), then `knos status`, with every line in the log; a key file it cannot read
stops it before anything is sent. Nothing here
reaches a cluster or a real timer, and the "keys" are files that only stand for keys."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "schedule_upgrade.sh"
pytestmark = pytest.mark.skipif(os.name == "nt" or not shutil.which("bash") or not shutil.which("node"), reason="runs the script with bash and node")

STANDINS = {
    "systemd-run": 'echo "systemd-run $*" >> "$CALLS"\n[ "$SYSTEMD" = 1 ]\n',
    "systemctl": 'echo "systemctl $*" >> "$CALLS"\ncase "$*" in "--user show-environment") [ "$SYSTEMD" = 1 ];; "is-active --quiet atd") [ "$ATD" = 1 ];; *) exit 0;; esac\n',
    "pgrep": 'exit 1\n',
    "at": 'echo "at $* <<< $(cat)" >> "$CALLS"\necho "warning: commands will be executed using /bin/sh" >&2\necho "job 17 at Tue Oct  6 01:33:00 2026" >&2\n',
    "atrm": 'echo "atrm $*" >> "$CALLS"\n',
    "schtasks.exe": 'echo "schtasks.exe $*" >> "$CALLS"\n',
    "wslpath": 'echo "C:\\\\keys\\\\$(basename "$2")"\n',
    "knos": 'echo "knos $* rpc=$KNOS_RPC" >> "$CALLS"\necho "12 of 12 checks pass"\n',
    # the BSD wc of macOS pads its count with spaces: on every OS the script meets that wc here
    "wc": 'printf "%8s\\n" "$(/usr/bin/wc "$@" | tr -d " ")"\n',
}
# governance.mjs's stand-in refuses as the real one does (scripts/governance.test.mjs holds `expected` to that): a proposal
# whose buffer holds another build than --expect-hash names (ON_CHAIN_<index>: the build "on chain"; default: the one asked for)
NODE = ('#!/bin/sh\ncase "$1" in */governance.mjs) echo "node governance $2 $3 $4 $5 $6 $7 $8 keys=$KNOS_KEYS payer=$KNOS_FEE_PAYER members=${KNOS_MEMBERS:-default}" >> "$CALLS"\n'
        '  if [ "$4" = "$FAIL_INDEX" ]; then echo "refused: its time lock ends later" >&2; exit 1; fi\n'
        '  [ "$7" = --expect-hash ] || { echo "refused: no build was named" >&2; exit 1; }\n'
        '  have="$(eval echo "\\${ON_CHAIN_$4:-$8}")"\n'
        '  if [ "$have" != "$8" ]; then echo "refused: proposal $4 of the upgrade multisig would deploy the build $have, and this run was arranged for the build $8. Nothing was sent." >&2; exit 1; fi\n'
        '  echo "on chain now: proposal $4 of the upgrade multisig is executed"; exit 0;; esac\nexec {node} "$@"\n')
# what each stand-in key file holds: if it ever shows up in the env file, the log or the output, a key was copied there
MARK = "a-file-that-stands-for-a-key"
# what 0.3.14 proposes: the four programs the upgrade vault holds, each with the executable hash of its build
PROPOSED = {3: "knos_oidc", 4: "knos_pay", 5: "knos_meter", 6: "knos_passkey"}
HASH = {index: f"{index}{index}" * 32 for index in PROPOSED}
RPC = "https://api.devnet.solana.com"


def _executes(index: int, tail: str) -> str:
    return f"node governance upgrade execute {index} --rpc {RPC} --expect-hash {HASH[index]} {tail}"


@pytest.fixture()
def box(tmp_path):
    """A key folder with a schedule and the key files the run signs with, a kernel that is not WSL's, and a PATH that holds
    the stand-ins before everything else."""
    keys, bin_dir = tmp_path / "keys", tmp_path / "bin"
    keys.mkdir(), bin_dir.mkdir()
    for name, body in STANDINS.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + body, encoding="utf-8")
    (bin_dir / "node").write_text(NODE.replace("{node}", shutil.which("node")), encoding="utf-8")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    for name in ("payer.json", "member-1.json", "member-2.json", "member-3.json"):
        (keys / name).write_text(json.dumps(MARK), encoding="utf-8")
    at = int(time.time()) + 172_800
    plan = {"rpc": "https://api.devnet.solana.com", "executable_from": at, "run_at": at + 600,
            "proposals": [{"program": name, "index": index, "hash": HASH[index]} for index, name in PROPOSED.items()]}
    (keys / "upgrade-schedule.json").write_text(json.dumps(plan), encoding="utf-8")
    calls = tmp_path / "calls"
    calls.write_text("", encoding="utf-8")
    kernel = tmp_path / "osrelease"              # the tests decide whether this is WSL, whatever machine runs them
    kernel.write_text("6.8.0-45-generic\n", encoding="utf-8")
    # and no schtasks.exe off PATH: on a real WSL the one in Windows' System32 would make a real task
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "KNOS_KEYS": str(keys), "CALLS": str(calls), "SYSTEMD": "0", "ATD": "0", "HOME": str(tmp_path), "TZ": "UTC",
           "KNOS_OSRELEASE": str(kernel), "KNOS_UPGRADE_DEPS": "0", "KNOS_SCHTASKS": str(tmp_path / "no-windows" / "schtasks.exe")}

    def run(*args: str, **more: str):
        return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **more}, capture_output=True, text=True)
    return keys, calls, plan, run, bin_dir


def _calls(calls: Path) -> list[str]:
    return calls.read_text(encoding="utf-8").splitlines()


def test_systemd_is_taken_first_and_the_timer_is_for_the_schedules_time_in_utc(box):
    keys, calls, plan, run, _ = box
    done = run(SYSTEMD="1", ATD="1")
    assert done.returncode == 0, done.stderr
    [made] = [c for c in _calls(calls) if c.startswith("systemd-run")]
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(plan["run_at"]))
    # through a login shell: the user's profile mounts and exports what the run needs, after a restart too
    assert "--user --unit knos-upgrade" in made and f"--on-calendar {stamp}" in made and made.endswith(f"/bin/bash -l {SCRIPT} --run")
    assert f"arranged with systemd: the user timer knos-upgrade.timer runs the upgrade at {stamp}" in done.stdout
    assert "cancel it: bash scripts/schedule_upgrade.sh --cancel     (or: systemctl --user stop knos-upgrade.timer)" in done.stdout
    assert "node scripts/governance.mjs upgrade execute <index>, then knos status" in done.stdout and str(keys / "upgrade-run.log") in done.stdout
    assert "NOTE: this is WSL" not in done.stdout and "the fee payer's and 3 member key file(s), each readable now" in done.stdout
    assert (keys / "upgrade-run.timer").read_text(encoding="utf-8").split() == ["systemd", "knos-upgrade"]
    envfile = (keys / "upgrade-run.env").read_text(encoding="utf-8")
    assert oct((keys / "upgrade-run.env").stat().st_mode & 0o777) == "0o600" and "export PATH=" in envfile
    # the paths of the keys, never a key
    assert f"export KNOS_KEYS={keys}\n" in envfile and f"export KNOS_FEE_PAYER={keys / 'payer.json'}\n" in envfile and MARK not in envfile
    # nothing was sent: arranging is not running
    assert not [c for c in _calls(calls) if c.startswith(("node governance", "knos"))]
    # again: the earlier timer is taken back first, so there is never more than one
    again = run(SYSTEMD="1")
    assert again.returncode == 0 and "replacing the earlier arrangement: cancelled: the systemd timer knos-upgrade is gone" in again.stdout
    assert "systemctl --user stop knos-upgrade.timer" in _calls(calls) and len([c for c in _calls(calls) if c.startswith("systemd-run")]) == 2
    gone = run("--cancel")
    assert gone.returncode == 0 and "cancelled: the systemd timer knos-upgrade is gone" in gone.stdout and not (keys / "upgrade-run.timer").exists()
    assert run("--cancel").stdout.startswith("nothing is arranged")


def test_without_systemd_at_is_used_when_its_daemon_runs_and_the_job_number_is_kept_for_the_cancel(box):
    keys, calls, plan, run, _ = box
    done = run(ATD="1")
    assert done.returncode == 0, done.stderr
    [made] = [c for c in _calls(calls) if c.startswith("at ")]
    assert made.startswith("at -t " + time.strftime("%Y%m%d%H%M.%S", time.gmtime(plan["run_at"]))) and made.endswith(f"/bin/bash -l {SCRIPT} --run")
    assert f"KNOS_KEYS={keys}" in made
    assert "arranged with at: job 17 runs the upgrade at" in done.stdout and "(or: atrm 17)" in done.stdout
    assert run("--cancel").returncode == 0 and "atrm 17" in _calls(calls)


def test_under_wsl_a_windows_task_comes_first_and_starts_wsl_at_a_utc_instant_through_a_login_shell(box, tmp_path):
    keys, calls, plan, run, bin_dir = box
    # systemd and atd answer too: under WSL they fire only while the distribution runs, so the Windows task is taken first
    done = run(WSL_DISTRO_NAME="Ubuntu-24.04", SYSTEMD="1", ATD="1")
    assert done.returncode == 0, done.stderr
    [made] = [c for c in _calls(calls) if c.startswith("schtasks.exe")]
    assert made == "schtasks.exe /Create /TN KnosUpgrade /XML C:\\keys\\upgrade-run.task.xml /F"
    assert not [c for c in _calls(calls) if c.startswith(("systemd-run", "at "))]
    xml = (keys / "upgrade-run.task.xml").read_bytes()
    assert xml[:2] == b"\xff\xfe"
    task = xml[2:].decode("utf-16-le")
    assert f"<StartBoundary>{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(plan['run_at']))}</StartBoundary>" in task
    # in a headless console: in a console of its own, the task's wsl.exe is ended after about 20 seconds
    assert ("<Command>C:\\Windows\\System32\\conhost.exe</Command><Arguments>--headless C:\\Windows\\System32\\wsl.exe -d Ubuntu-24.04 -- "
            f"env KNOS_KEYS={keys} /bin/bash -l {SCRIPT} --run</Arguments>") in task
    assert "<Command>wsl.exe</Command>" not in task
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in task and MARK not in task
    assert "arranged with the Windows Task Scheduler: the task KnosUpgrade starts wsl.exe -d Ubuntu-24.04" in done.stdout
    assert "(or: schtasks.exe /Delete /TN KnosUpgrade /F)" in done.stdout and "NOTE: this is WSL" not in done.stdout
    assert run("--cancel").returncode == 0 and "schtasks.exe /Delete /TN KnosUpgrade /F" in _calls(calls)
    # a bare environment (sudo, a timer: no WSL_DISTRO_NAME) is told it is WSL by the kernel's name
    wsl_kernel = tmp_path / "wsl-osrelease"
    wsl_kernel.write_text("5.15.167.4-microsoft-standard-WSL2\n", encoding="utf-8")
    bare = run(SYSTEMD="1", KNOS_OSRELEASE=str(wsl_kernel))
    assert bare.returncode == 0 and "arranged with the Windows Task Scheduler: the task KnosUpgrade starts wsl.exe -d Ubuntu-24.04" in bare.stdout
    # asked for, a systemd timer under WSL is made, and what it needs is said, with the way out
    warned = run("--with", "systemd", SYSTEMD="1", WSL_DISTRO_NAME="Ubuntu-24.04")
    assert warned.returncode == 0 and "arranged with systemd" in warned.stdout
    assert "NOTE: this is WSL. A systemd timer fires only if this distribution is running at that time" in warned.stdout and "--with schtasks" in warned.stdout
    forced = run("--with", "schtasks", SYSTEMD="1", WSL_DISTRO_NAME="Ubuntu-24.04")
    assert forced.returncode == 0 and "arranged with the Windows Task Scheduler" in forced.stdout
    # a WSL that keeps Windows' PATH off its own (appendWindowsPath=false): schtasks.exe is taken from Windows' System32
    system32 = tmp_path / "Windows" / "System32"
    system32.mkdir(parents=True)
    (bin_dir / "schtasks.exe").rename(system32 / "schtasks.exe")
    off_path = run(SYSTEMD="1", WSL_DISTRO_NAME="Ubuntu-24.04", KNOS_SCHTASKS=str(system32 / "schtasks.exe"))
    assert off_path.returncode == 0 and "arranged with the Windows Task Scheduler" in off_path.stdout, off_path.stderr
    assert _calls(calls)[-1] == "schtasks.exe /Create /TN KnosUpgrade /XML C:\\keys\\upgrade-run.task.xml /F"
    gone = run("--cancel", KNOS_SCHTASKS=str(system32 / "schtasks.exe"))
    assert gone.returncode == 0 and _calls(calls)[-1] == "schtasks.exe /Delete /TN KnosUpgrade /F"
    # no schtasks.exe reachable from this WSL: systemd, said aloud; and with no timer at all, what to do
    fallback = run(SYSTEMD="1", WSL_DISTRO_NAME="Ubuntu-24.04")
    assert fallback.returncode == 0 and "arranged with systemd" in fallback.stdout and "NOTE: this is WSL. A systemd timer fires only if" in fallback.stdout
    none = run()
    assert none.returncode == 1 and "no timer works here" in none.stderr and "bash scripts/schedule_upgrade.sh --run" in none.stderr
    assert "schtasks.exe is neither on PATH nor at" in none.stderr


def test_a_time_that_has_passed_or_a_missing_schedule_arranges_nothing(box):
    keys, calls, plan, run, _ = box
    (keys / "upgrade-schedule.json").write_text(json.dumps({**plan, "run_at": int(time.time()) - 5}), encoding="utf-8")
    late = run(SYSTEMD="1")
    assert late.returncode == 1 and "has passed already. Run it now: bash scripts/schedule_upgrade.sh --run" in late.stderr
    (keys / "upgrade-schedule.json").unlink()
    none = run(SYSTEMD="1")
    assert none.returncode == 1 and "Propose the upgrades first: bash scripts/deploy_v2.sh --propose" in none.stderr
    assert not [c for c in _calls(calls) if c.startswith("systemd-run")] and not (keys / "upgrade-run.timer").exists()


def test_the_run_executes_each_proposal_in_order_then_knos_status_and_logs_every_line(box):
    keys, calls, plan, run, _ = box
    done = run("--run")
    assert done.returncode == 0, done.stderr
    # all four, in the order of their indexes, each named with the build it was proposed with
    assert [c for c in _calls(calls) if c.startswith(("node", "knos"))] == [
        *(_executes(index, f"keys={keys} payer= members=default") for index in (3, 4, 5, 6)), "knos status rpc=https://api.devnet.solana.com"]
    log = (keys / "upgrade-run.log").read_text(encoding="utf-8")
    assert "the scheduled upgrade run starts (cluster https://api.devnet.solana.com; proposals 3 4 5 6)" in log
    assert log.index("proposal 3 of the upgrade multisig is executed") < log.index("proposal 4 of the upgrade multisig is executed") < log.index(
        "proposal 6 of the upgrade multisig is executed") < log.index("12 of 12 checks pass")
    assert log.rstrip().endswith("done: every proposal is executed") and "done: every proposal is executed" in done.stdout
    # one that is refused is said, the other still runs, knos status still runs, and the exit code says it
    bad = run("--run", "--force", FAIL_INDEX="3")          # --force: a second start after success does nothing otherwise
    log = (keys / "upgrade-run.log").read_text(encoding="utf-8")
    assert bad.returncode == 1 and "refused: its time lock ends later" in log and "proposal 3: NOT executed" in log
    assert log.rstrip().endswith("done: 1 proposal(s) NOT executed. Run it again by hand: bash scripts/schedule_upgrade.sh --run")
    assert log.count("knos status") >= 2 and log.count("the scheduled upgrade run starts") == 2          # appended, never overwritten
    shown = run("--show")
    assert "schedule: proposals 3 4 5 6 on https://api.devnet.solana.com" in shown.stdout and "timer: none arranged" in shown.stdout and "NOT executed" in shown.stdout


def test_the_run_signs_with_the_key_paths_arranging_wrote_and_a_key_it_cannot_read_stops_it_loudly_before_anything_is_sent(box, tmp_path):
    keys, calls, plan, run, _ = box
    # the keys live on a drive of their own (a mount the profile makes), named by the arranging shell alone
    drive = tmp_path / "mounted drive"
    drive.mkdir()
    payer, members = drive / "fee payer.json", [tmp_path / f"member-{n}-elsewhere.json" for n in (1, 2, 3)]
    for f in (payer, *members):
        f.write_text(json.dumps(MARK), encoding="utf-8")
    named = {"KNOS_FEE_PAYER": str(payer), "KNOS_MEMBERS": " ".join(map(str, members))}
    arranged = run(SYSTEMD="1", **named)
    assert arranged.returncode == 0, arranged.stderr
    envfile = (keys / "upgrade-run.env").read_text(encoding="utf-8")
    assert "paths only, never a key" in envfile and MARK not in envfile and str(members[2]) in envfile
    assert "keys: the 4 key files the run signs with can be read now" in run("--show").stdout
    # 48 hours later the timer starts it with none of that in its environment: the file arranging wrote is what it signs with
    done = run("--run")
    assert done.returncode == 0, done.stderr
    executed = [c for c in _calls(calls) if c.startswith("node governance")]
    assert len(executed) == 4 and all(c.endswith(f"payer={payer} members={named['KNOS_MEMBERS']}") for c in executed)
    # the drive that holds a member's key is not there: said once, in the log and aloud, with the path, and nothing is sent
    members[1].unlink()
    before = len(_calls(calls))
    stopped = run("--run", "--force")
    assert stopped.returncode == 1 and _calls(calls)[before:] == [], "no proposal executed, no knos status: nothing was sent"
    log = (keys / "upgrade-run.log").read_text(encoding="utf-8")
    tail = log[log.rindex("===="):]
    assert "the scheduled upgrade run CANNOT START (cluster https://api.devnet.solana.com; proposals 3 4 5 6)" in tail and str(members[1]) in tail
    assert str(members[0]) not in tail and str(payer) not in tail and "Nothing was sent" in tail and "bash scripts/schedule_upgrade.sh --run" in tail
    assert "CANNOT START" in stopped.stderr and str(members[1]) in stopped.stderr and MARK not in log + stopped.stdout + stopped.stderr
    assert f"keys: the run could NOT start now: it cannot read {members[1]}" in run("--show").stdout
    # arranging refuses at once what the run could not read, and arranges nothing
    made = len([c for c in _calls(calls) if c.startswith("systemd-run")])
    refused = run(SYSTEMD="1", **named)
    assert refused.returncode == 1 and "the run signs with key files that cannot be read now" in refused.stderr and str(members[1]) in refused.stderr
    assert "Nothing was arranged" in refused.stderr and len([c for c in _calls(calls) if c.startswith("systemd-run")]) == made
    # the fee payer's file missing from the key folder, with nothing named: the same
    (keys / "payer.json").unlink()
    alone = run(SYSTEMD="1")
    assert alone.returncode == 1 and str(keys / "payer.json") in alone.stderr


def test_the_run_executes_only_the_build_the_schedule_recorded_so_a_stale_run_never_executes_another(box):
    keys, calls, plan, run, _ = box
    arranged = run(SYSTEMD="1")
    assert arranged.returncode == 0, arranged.stderr
    # arranging says which build each proposal is executed for
    for index, name in PROPOSED.items():
        assert f"  proposal {index}: {name}, build {HASH[index]}" in arranged.stdout
    assert "Each is executed only while its buffer holds the build proposed" in arranged.stdout
    # the buffer of proposal 4 holds another build when the run starts: refused, in the log, and the others still run
    other = "69ec05b83e29b92fb255fd7f0cd52e128e04a4c9dbc5e16eecdc39caaafed9c9"
    done = run("--run", ON_CHAIN_4=other)
    log = (keys / "upgrade-run.log").read_text(encoding="utf-8")
    assert done.returncode == 1 and f"would deploy the build {other}, and this run was arranged for the build {HASH[4]}. Nothing was sent." in log
    assert "proposal 4: NOT executed" in log and "proposal 3: executed" in log and "proposal 6: executed" in log
    assert log.rstrip().endswith("done: 1 proposal(s) NOT executed. Run it again by hand: bash scripts/schedule_upgrade.sh --run")
    # a schedule that records no build for a proposal (an older --propose wrote it, or a hand): that proposal is never
    # executed on its index alone, governance.mjs is not even called for it, and such a schedule cannot be arranged
    old = {**plan, "proposals": [{"program": "knos_oidc", "index": 1}, {"program": "knos_pay", "index": 2, "hash": "not a hash"}, plan["proposals"][2]]}
    (keys / "upgrade-schedule.json").write_text(json.dumps(old), encoding="utf-8")
    before = len(_calls(calls))
    stale = run("--run")
    sent = [c for c in _calls(calls)[before:] if c.startswith("node governance")]
    assert stale.returncode == 1 and sent == [_executes(5, f"keys={keys} payer={keys / 'payer.json'} members=default")]
    log = (keys / "upgrade-run.log").read_text(encoding="utf-8")
    tail = log[log.rindex("==== ", 0, log.rindex("====")):]
    assert "proposal 1 (knos_oidc): NOT executed" in tail and "proposal 2 (knos_pay): NOT executed" in tail and "records no build for it" in tail
    assert "done: 2 proposal(s) NOT executed" in tail and "---- knos status" in tail
    refused = run(SYSTEMD="1")
    assert refused.returncode == 1 and "records no build (hash) for proposal 1 2" in refused.stderr and "Nothing was arranged" in refused.stderr
    assert "  proposal 1: knos_oidc, build -" in run("--show").stdout
    # every execution the script can send names a build: there is no path that executes by index alone
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.count('governance.mjs" upgrade execute') == 1 and 'upgrade execute "$index" --rpc "$rpc" --expect-hash "$hash"' in text


def test_the_windows_task_also_starts_after_a_missed_start_and_at_the_next_logon_and_stores_no_password(box):
    """Nobody has to be logged on at the minute: the task starts at the time, as soon as possible after a start that was
    missed, and at this Windows user's next logon from the time on. No password is stored (no principal that asks for
    one), and the output says how to check it."""
    keys, calls, plan, run, bin_dir = box
    (bin_dir / "whoami.exe").write_text("#!/bin/sh\nprintf '%s\\r\\n' 'desk\\ada'\n", encoding="utf-8")
    (bin_dir / "whoami.exe").chmod(0o755)
    done = run(WSL_DISTRO_NAME="Ubuntu-24.04")
    assert done.returncode == 0, done.stderr
    task = (keys / "upgrade-run.task.xml").read_bytes()[2:].decode("utf-16-le")
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(plan["run_at"]))
    until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(plan["run_at"] + 14 * 86_400))
    assert f"<TimeTrigger><StartBoundary>{at}</StartBoundary><Enabled>true</Enabled></TimeTrigger>" in task
    assert f"<LogonTrigger><StartBoundary>{at}</StartBoundary><EndBoundary>{until}</EndBoundary><Enabled>true</Enabled><UserId>desk\\ada</UserId></LogonTrigger>" in task
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in task and "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in task
    assert "Password" not in task and "S4U" not in task and "<Principal" not in task
    assert "at the next logon of desk\\ada after that time, for 14 days. No password is stored." in done.stdout
    assert "check it:  schtasks.exe /Query /TN KnosUpgrade /V /FO LIST" in done.stdout and "Last Result: 267011 before" in done.stdout
    assert len([c for c in _calls(calls) if c.startswith("schtasks.exe /Create")]) == 1
    # Windows does not take the logon trigger: the task is made without it, and that is said
    (bin_dir / "schtasks.exe").write_text('#!/bin/sh\necho "schtasks.exe $*" >> "$CALLS"\n[ "$(grep -c "schtasks.exe /Create" "$CALLS")" != 2 ]\n', encoding="utf-8")
    again = run(WSL_DISTRO_NAME="Ubuntu-24.04")
    assert again.returncode == 0, again.stderr
    assert "LogonTrigger" not in (keys / "upgrade-run.task.xml").read_bytes()[2:].decode("utf-16-le")
    assert "NOTE: no logon trigger" in again.stdout and "be logged on to Windows at that time" in again.stdout
    none = run(WSL_DISTRO_NAME="Ubuntu-24.04", KNOS_WIN_USER="-")
    assert none.returncode == 0 and "NOTE: no logon trigger" in none.stdout


def test_a_second_start_after_success_does_nothing_and_two_at_once_send_once(box):
    keys, calls, plan, run, _ = box
    assert "done: no run has executed every proposal of this schedule yet" in run("--show").stdout
    assert run("--run").returncode == 0
    sent = len([c for c in _calls(calls) if c.startswith("node governance")])
    assert sent == 4 and not (keys / "upgrade-run.lock").exists()
    second = run("--run")           # the logon trigger after the time trigger, or a person after both
    assert second.returncode == 0 and "a start for a schedule that is done already (proposals 3 4 5 6): nothing was sent" in second.stdout
    assert len([c for c in _calls(calls) if c.startswith("node governance")]) == sent
    assert "done: a run executed every proposal of this schedule" in run("--show").stdout
    assert run("--run", "--force").returncode == 0 and len([c for c in _calls(calls) if c.startswith("node governance")]) == 2 * sent
    # another schedule (a second --propose) is another run
    (keys / "upgrade-schedule.json").write_text(json.dumps({**plan, "run_at": plan["run_at"] + 60}), encoding="utf-8")
    assert run("--run").returncode == 0 and len([c for c in _calls(calls) if c.startswith("node governance")]) == 3 * sent
    # a run that did not execute everything is not done: the next start tries again
    (keys / "upgrade-run.done").unlink()
    assert run("--run", FAIL_INDEX="4").returncode == 1 and not (keys / "upgrade-run.done").exists() and not (keys / "upgrade-run.lock").exists()
    # a start while a run is going sends nothing; a lock a dead run left two hours ago is taken over
    (keys / "upgrade-run.lock").mkdir()
    before = len(_calls(calls))
    busy = run("--run")
    assert busy.returncode == 0 and "another upgrade run is going" in busy.stdout and len(_calls(calls)) == before
    old = time.time() - 3 * 3600
    os.utime(keys / "upgrade-run.lock", (old, old))
    assert run("--run").returncode == 0 and (keys / "upgrade-run.done").exists() and not (keys / "upgrade-run.lock").exists()
