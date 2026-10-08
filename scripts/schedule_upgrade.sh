#!/usr/bin/env bash
# Execute the proposed upgrades when their 48 hours have passed, unattended.
#
# `bash scripts/deploy_v2.sh --propose` wrote <key folder>/upgrade-schedule.json: each proposal's index, the executable
# hash of the build it was proposed with, and the time from which all of them can be executed, plus ten minutes
# (run_at). This script arranges for one run at that time:
#
#     node scripts/governance.mjs upgrade execute <index> --expect-hash <hash>     for each proposal, in the order of their indexes
#     knos status                                                                  what is on chain afterwards
#
# with every line of both appended to <key folder>/upgrade-run.log. The run executes a proposal only while its buffer
# holds exactly the build the schedule recorded for it (--expect-hash: governance.mjs reads the buffer from the
# proposal's own transaction and refuses any other build, or a buffer that is gone), and a proposal the schedule
# records no build for is not executed at all. So a run arranged for a build that was withdrawn since
# (bash scripts/deploy_v2.sh --propose --replace) executes nothing of it, whatever the schedule file names by then.
#
#   bash scripts/schedule_upgrade.sh              arrange the run, and print how to cancel it
#   bash scripts/schedule_upgrade.sh --show       what is arranged, whether the keys and the Node packages are there now, and
#                                                 what the log says so far
#   bash scripts/schedule_upgrade.sh --verify     a dry trigger: starts what the timer starts (a login shell with a bare
#                                                 environment, then the env file), checks the schedule, the keys and the
#                                                 Node packages (installing them when they are missing), loads them in
#                                                 node, and sends NOTHING. Exit 0: the run would start. Do it after arranging
#   bash scripts/schedule_upgrade.sh --cancel     take the arrangement back (the proposals stay as they are on chain).
#                                                 The first step when a proposal must not execute: docs/RELEASE.md
#   bash scripts/schedule_upgrade.sh --run        the run itself, now: what the timer calls. Safe by hand too: a
#                                                 proposal whose time has not come is refused by governance.mjs and by
#                                                 the Squads program, and one already executed is left alone
#   bash scripts/schedule_upgrade.sh --run --force   the run again, although a run for this schedule ended well before
#   --with systemd|at|schtasks                    choose the timer instead of taking the first that works here
#
# NOBODY HAS TO BE THERE AT THE MINUTE (0.3.20). The Windows task used to have one trigger, the time, and a Windows task
# made without a stored password runs only in a session that is logged on: with nobody logged on at that minute it did
# not start. It now has three ways to start, and none stores a password:
#   at the time                  the time trigger, as before
#   as soon as possible after    StartWhenAvailable: a start that was missed (the machine was off or asleep) is made
#                                when the Task Scheduler runs again
#   at the next logon            a logon trigger for this Windows user, in force from the time on, for 14 days: with
#                                nobody logged on at the time, the run starts when that user next logs on
# The other way Windows offers, "run whether the user is logged on or not" without a stored password (logon type S4U),
# is NOT used: such a task has "no access to either the network or encrypted files"
# (https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-logontype-simpletype), and the run
# needs the cluster. When Windows does not take the logon trigger (KNOS_WIN_USER names nobody it knows), the task is
# made with the first two, and the script says so. A systemd timer is made with Persistent=true, which is the same
# promise there; `at` runs a job whose time passed when its daemon next starts.
# A SECOND RUN AFTER SUCCESS DOES NOTHING. A run that executed every proposal writes <key folder>/upgrade-run.done (the
# schedule it was for). Any later start for the same schedule, by a trigger or by hand, logs one line and ends with 0;
# --force runs it again. Two starts at once: the second finds <key folder>/upgrade-run.lock and ends (a lock older
# than two hours is a run that died, and is taken over).
#
# The timer is the first of these that works on this machine:
#   systemd   systemd-run --user --on-calendar: a transient timer of the user's systemd (unit knos-upgrade)
#   at        the at command, when its daemon (atd) is running
#   schtasks  a Windows scheduled task (KnosUpgrade), made with schtasks.exe from inside WSL, that starts
#             `wsl.exe -d <this distribution>` at the time, in a headless console (conhost --headless): it runs
#             even if no WSL window is open then. schtasks.exe
#             is taken from PATH, or from Windows' System32 when this WSL does not put Windows' PATH on its own
#             ([interop] appendWindowsPath=false in /etc/wsl.conf)
# Under WSL schtasks is tried FIRST: a systemd or at timer of WSL fires only while the distribution is running at that
# time (a WSL with no open window stops after a few seconds; after a restart nothing runs until a window opens), and the
# Windows task starts it. When schtasks.exe cannot be reached from WSL, the other two are taken and the script says
# what they need: keep a window open.
#
# The run starts 48 hours later with a bare environment, perhaps after a restart, so it does not lean on this shell:
#   - every timer starts it through a login shell (bash -l), so the user's profile does what it does for a terminal:
#     mounts the drive that holds the keys, puts node and knos on PATH;
#   - then it reads <key folder>/upgrade-run.env, which arranging wrote (mode 600): PATH and the PATHS of the keys
#     (KNOS_KEYS, KNOS_FEE_PAYER, KNOS_MEMBERS), never a key;
#   - before it sends anything it checks that every key file the execution signs with (the fee payer's and each
#     member's) can be read. If one cannot (a drive that is not mounted, a file that moved), the log says which, and
#     nothing is sent. Arranging checks the same at once, and `--show` says whether they can be read now.
#
# THE NODE PACKAGES COME FIRST. scripts/governance.mjs imports the packages scripts/package.json pins (@solana/web3.js,
# @sqds/multisig). A run that found scripts/node_modules gone executed nothing (6 October 2026: `Cannot find package
# '@solana/web3.js'`, four proposals left waiting). So --run, before it sends anything, holds scripts/node_modules to
# scripts/package.json: every pinned package there at its pinned version, or `npm ci --prefix scripts --omit=optional`
# and the same check again. When they cannot be had, nothing is sent, the log says why, and the last line on stderr is
# one plain line starting `stopped:` with exit 1. Arranging checks the same at once, and so do --show and --verify.
#
# Every line this script writes into the log starts with the time (UTC).
#
# Running it again replaces the arrangement with one for the time the schedule file names now, so it is safe after a
# second --propose. Nothing here sends a transaction before --run.
#
# What it reads
#   KNOS_KEYS, KNOS_FEE_PAYER, KNOS_MEMBERS, KNOS_RPC    as scripts/governance.mjs reads them. The key folder, the
#                      fee payer's file and the members' files, and PATH, are written to <key folder>/upgrade-run.env
#                      (mode 600) so that the run has what this shell has
#   KNOS_SCHEDULE      the schedule file (default: upgrade-schedule.json in the key folder)
#   KNOS_WSL_DISTRO    schtasks: the distribution wsl.exe starts (default: $WSL_DISTRO_NAME, else Ubuntu-24.04)
#   KNOS_OSRELEASE     the file that names the kernel (default /proc/sys/kernel/osrelease): Microsoft's means WSL even
#                      where WSL_DISTRO_NAME is not set (sudo, a timer)
#   KNOS_SCHTASKS      schtasks.exe when it is not on PATH (default /mnt/c/Windows/System32/schtasks.exe)
#   KNOS_WIN_USER      schtasks: the Windows user whose logon also starts the run (default: what whoami.exe, beside
#                      schtasks.exe, prints). `-`: no logon trigger
#   KNOS_NODE_DIR      the folder whose package.json and node_modules governance.mjs runs on (default: scripts/)
#   KNOS_UPGRADE_DEPS  0: the Node packages are neither checked nor installed (a machine that provides them another
#                      way, and the tests that stand in for node). Anything else: checked first
#
# Needs: node 20 or later and npm (the run does `npm ci --prefix scripts` itself when it must), `knos` on PATH (pip install -e . or pipx install knos),
# and one of the three timers.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD

ACTION=schedule WITH="" BARE=0 FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --show) ACTION=show ;;
    --cancel) ACTION=cancel ;;
    --run) ACTION=run ;;
    --verify) ACTION=verify ;;
    --force) FORCE=1 ;;
    --bare) BARE=1 ;;                        # --verify's second half, inside the login shell it started
    --with) shift; WITH="${1:-}"; case "$WITH" in systemd|at|schtasks) ;; *) echo "--with takes systemd, at or schtasks" >&2; exit 2 ;; esac ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "usage: bash scripts/schedule_upgrade.sh [--show | --cancel | --run | --verify] [--with systemd|at|schtasks]" >&2; exit 2 ;;
  esac
  shift
done

KEYS="${KNOS_KEYS:-$ROOT/.knos-keys}"
SCHEDULE="${KNOS_SCHEDULE:-$KEYS/upgrade-schedule.json}"
LOG="$KEYS/upgrade-run.log"
ENVFILE="$KEYS/upgrade-run.env"
STATE="$KEYS/upgrade-run.timer"            # how the run was arranged: the timer's kind and its name or job number
DONE="$KEYS/upgrade-run.done"              # the schedule a run executed every proposal of: a later start for it does nothing
LOCK="$KEYS/upgrade-run.lock"              # a run is going
UNIT=knos-upgrade
TASK=KnosUpgrade

die() { echo "stopped: $*" >&2; exit 1; }
# field <name>: a value of the schedule file. `indexes`: the proposals' indexes on one line. `plan`: one line per proposal,
# "<index> <the build's executable hash, or - when the file records none> <program>", in the order of the indexes
field() { node -e 'const s = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); const hex = (h) => (/^[0-9a-f]{64}$/.test(h ?? "") ? h : "-"); const v = process.argv[2] === "indexes" ? s.proposals.map((p) => p.index).join(" ") : process.argv[2] === "plan" ? s.proposals.map((p) => `${p.index} ${hex(p.hash)} ${p.program ?? "-"}`).join("\n") : s[process.argv[2]]; if (v === undefined || v === null || v === "") process.exit(1); console.log(v);' "$SCHEDULE" "$1"; }
wsl() { [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft "${KNOS_OSRELEASE:-/proc/sys/kernel/osrelease}" 2>/dev/null; }
# schtasks.exe: on PATH, or in Windows' System32 for a WSL that keeps Windows' PATH off its own (appendWindowsPath=false)
schtasks_exe() {
  command -v schtasks.exe 2>/dev/null && return 0
  local exe="${KNOS_SCHTASKS:-/mnt/c/Windows/System32/schtasks.exe}"
  if [ -x "$exe" ]; then echo "$exe"; else return 1; fi
}
# a unix time as date prints it: GNU date reads it with -d @t, the BSD date of macOS with -r t
date_at() { local t="$1"; shift; date -d "@$t" "$@" 2>/dev/null || date -r "$t" "$@"; }
utc() { date_at "$1" -u "+%Y-%m-%d %H:%M:%S UTC"; }
stamp() { date -u "+%Y-%m-%d %H:%M:%S UTC"; }

# the run is started by a timer, with a bare environment: what the arranging shell had comes first (and --show says
# what the run will have)
# shellcheck disable=SC1090  # written by this script when the run was arranged
if { [ "$ACTION" = run ] || [ "$ACTION" = show ] || [ "$ACTION" = verify ]; } && [ -f "$ENVFILE" ]; then . "$ENVFILE"; fi
command -v node >/dev/null 2>&1 || die "node is not on PATH. Install Node 20 or later."
DEPS="${KNOS_NODE_DIR:-$ROOT/scripts}"

# ---- the Node packages governance.mjs imports ------------------------------------------------------------------------------
# those of <DEPS>/package.json's `dependencies` that are not in <DEPS>/node_modules at the pinned version, one per line
# as name@version (the optional packages are for the rehearsal on a fork, never for an execution)
deps_missing() {
  node -e 'const fs = require("fs"), path = require("path"); const at = process.argv[1];
    const want = JSON.parse(fs.readFileSync(path.join(at, "package.json"), "utf8")).dependencies || {};
    for (const [name, version] of Object.entries(want)) {
      let have = null;
      try { have = JSON.parse(fs.readFileSync(path.join(at, "node_modules", name, "package.json"), "utf8")).version; } catch { /* not there */ }
      if (have !== version) console.log(`${name}@${version}` + (have ? ` (found ${have})` : ""));
    }' "$DEPS"
}
# deps: the packages are there, or are installed now. Says what it found and did, each line with the time. Returns 1,
# with the reason as its last line, when they cannot be had
deps() {
  local missing
  if [ "${KNOS_UPGRADE_DEPS:-1}" = 0 ]; then echo "$(stamp)  packages: not checked (KNOS_UPGRADE_DEPS=0)"; return 0; fi
  missing="$(deps_missing 2>&1)" || { echo "$(stamp)  packages: $DEPS/package.json could not be read: $(printf '%s' "$missing" | tail -n 1)"; return 1; }
  if [ -z "$missing" ]; then echo "$(stamp)  packages: every package $DEPS/package.json pins is installed"; return 0; fi
  missing="$(printf '%s\n' "$missing" | paste -sd ' ' -)"
  echo "$(stamp)  packages: missing from $DEPS/node_modules: $missing"
  if ! command -v npm >/dev/null 2>&1; then echo "$(stamp)  packages: npm is not on PATH, so they cannot be installed: $missing"; return 1; fi
  echo "$(stamp)  packages: npm ci --prefix $DEPS --omit=optional --no-audit --no-fund"
  npm ci --prefix "$DEPS" --omit=optional --no-audit --no-fund < /dev/null 2>&1 | tail -n 15 | sed 's/^/       /' || true
  missing="$(deps_missing 2>&1 | paste -sd ' ' -)"
  if [ -n "$missing" ]; then echo "$(stamp)  packages: npm ci did not install $missing (the lines above say why)"; return 1; fi
  echo "$(stamp)  packages: installed"
}

# ---- the keys the run signs with ---------------------------------------------------------------------------------------
# the key files an execution signs with, one per line, as scripts/governance.mjs finds them: the fee payer's, then
# each member's (KNOS_MEMBERS, else member-N.json in the key folder). Paths only: no key is ever read here
key_files() {
  local m found=0
  echo "${KNOS_FEE_PAYER:-$KEYS/payer.json}"
  if [ -n "${KNOS_MEMBERS:-}" ]; then
    for m in $KNOS_MEMBERS; do echo "$m"; done
  else
    for m in "$KEYS"/member-*.json; do if [ -e "$m" ]; then echo "$m"; found=1; fi; done
    [ "$found" = 1 ] || echo "$KEYS/member-1.json"
  fi
}
# those that cannot be read now, one per line
unreadable() { local f; key_files | while IFS= read -r f; do if [ ! -f "$f" ] || [ ! -r "$f" ]; then echo "$f"; fi; done; }

# ---- the run itself ---------------------------------------------------------------------------------------------------
# what a run is for: the time and every proposal with its build. A run that ended well keeps it in $DONE
schedule_key() { echo "run_at $(field run_at)"; field plan; }
run() {
  local index hash program failed=0 rpc missing why
  [ -f "$SCHEDULE" ] || die "$SCHEDULE is missing: nothing was proposed, or the key folder is another one (KNOS_KEYS)."
  rpc="$(field rpc)" || die "$SCHEDULE names no cluster."
  mkdir -p "$(dirname "$LOG")"
  # a second start after success (the logon trigger after the time trigger, a person after both) does nothing
  if [ "$FORCE" = 0 ] && [ -f "$DONE" ] && [ "$(cat "$DONE")" = "$(schedule_key)" ]; then
    echo "==== $(stamp)  a start for a schedule that is done already (proposals $(field indexes)): nothing was sent. Again all the same: bash scripts/schedule_upgrade.sh --run --force" >> "$LOG"
    tail -n 1 "$LOG"
    return 0
  fi
  # one run at a time: two triggers may start it in the same minute
  if [ -d "$LOCK" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]; then rmdir "$LOCK" 2>/dev/null || true; fi
  if ! mkdir "$LOCK" 2>/dev/null; then
    echo "==== $(stamp)  another upgrade run is going ($LOCK): this start sends nothing" >> "$LOG"
    tail -n 1 "$LOG"
    return 0
  fi
  trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
  # a key the execution signs with that cannot be read would fail each proposal one by one: said once, loudly, first
  missing="$(unreadable)"
  if [ -n "$missing" ]; then
    { echo "==== $(date -u "+%Y-%m-%d %H:%M:%S UTC")  the scheduled upgrade run CANNOT START (cluster $rpc; proposals $(field indexes)): a key file it signs with cannot be read:"
      printf '%s\n' "$missing" | sed 's/^/       /'
      echo "     Nothing was sent. The paths come from $ENVFILE (written when the run was arranged). Is the drive or mount that holds them there?"
      echo "     (A mount made by your profile is made by a login shell: the timer starts the run with bash -l.) Then run it by hand: bash scripts/schedule_upgrade.sh --run"
    } >> "$LOG"
    tail -n "$(( $(printf '%s\n' "$missing" | wc -l) + 3 ))" "$LOG" >&2
    return 1
  fi
  # the packages governance.mjs imports, before anything is sent: without them every proposal would fail one by one
  if ! deps >> "$LOG" 2>&1; then
    why="$(tail -n 1 "$LOG" | sed 's/^[0-9: -]*UTC  packages: //')"
    echo "==== $(stamp)  the scheduled upgrade run CANNOT START (cluster $rpc; proposals $(field indexes)): the Node packages are not there. Nothing was sent. By hand: npm ci --prefix scripts, then bash scripts/schedule_upgrade.sh --run" >> "$LOG"
    echo "stopped: the upgrade run did not start and nothing was sent: $why. Log: $LOG" >&2
    return 1
  fi
  {
    echo "==== $(date -u "+%Y-%m-%d %H:%M:%S UTC")  the scheduled upgrade run starts (cluster $rpc; proposals $(field indexes))"
    while read -r index hash program; do
      # only the build this run was arranged for: a proposal with no recorded build is never executed on its index alone
      if [ "$hash" = - ]; then
        echo "---- $(stamp)  proposal $index ($program): NOT executed: $SCHEDULE records no build for it, and this run executes only the build it was arranged for."
        echo "     Propose again (bash scripts/deploy_v2.sh --propose writes the schedule with each build's hash), then: bash scripts/schedule_upgrade.sh"
        failed=$((failed + 1)); continue
      fi
      echo "---- $(stamp)  node scripts/governance.mjs upgrade execute $index --expect-hash $hash     ($program)"
      if KNOS_KEYS="$KEYS" node "$ROOT/scripts/governance.mjs" upgrade execute "$index" --rpc "$rpc" --expect-hash "$hash" < /dev/null; then
        echo "---- $(stamp)  proposal $index: executed (or executed before)"
      else
        echo "---- $(stamp)  proposal $index: NOT executed (the lines above say why)"; failed=$((failed + 1))
      fi
    done <<< "$(field plan)"
    echo "---- knos status     ($(stamp))"
    if command -v knos >/dev/null 2>&1; then KNOS_RPC="$rpc" knos status || echo "---- knos status found something to look at (the lines above)"
    else echo "---- knos is not on PATH: run it by hand: KNOS_RPC=$rpc knos status"; fi
    if [ "$failed" = 0 ]; then echo "==== $(date -u "+%Y-%m-%d %H:%M:%S UTC")  done: every proposal is executed"
    else echo "==== $(date -u "+%Y-%m-%d %H:%M:%S UTC")  done: $failed proposal(s) NOT executed. Run it again by hand: bash scripts/schedule_upgrade.sh --run"; fi
  } >> "$LOG" 2>&1
  tail -n 3 "$LOG"
  if [ "$failed" != 0 ]; then echo "stopped: $failed proposal(s) NOT executed; the log says why for each: $LOG" >&2; return 1; fi
  schedule_key > "$DONE"
  echo "The site shows them executed with its next build (the pages workflow, every 30 minutes; now: gh workflow run network.yml)."
}

# ---- a dry trigger ----------------------------------------------------------------------------------------------------
# What the timer starts, short of sending: first half here (this shell), second half (--bare) in a login shell with a bare
# environment, as 48 hours later
verify() {
  local missing n
  if [ "$BARE" = 0 ]; then
    [ -f "$ENVFILE" ] || die "nothing is arranged (no $ENVFILE): arrange the run first (bash scripts/schedule_upgrade.sh), then --verify."
    echo "dry trigger at $(stamp): env -i HOME=... KNOS_KEYS=$KEYS /bin/bash -l scripts/schedule_upgrade.sh --verify --bare"
    env -i HOME="${HOME:-/}" KNOS_KEYS="$KEYS" /bin/bash -l "$ROOT/scripts/schedule_upgrade.sh" --verify --bare && return 0
    echo "stopped: the dry trigger failed (the line above says why): the run arranged would not start. Nothing was sent." >&2
    return 1
  fi
  [ -f "$SCHEDULE" ] || die "$SCHEDULE is missing: nothing was proposed, or the key folder is another one (KNOS_KEYS)."
  field rpc >/dev/null || die "$SCHEDULE names no cluster."
  n="$(field plan | awk '$2 == "-"' | wc -l)"
  [ "$(( n ))" = 0 ] || die "$SCHEDULE records no build for $(( n )) proposal(s): the run would execute none of them."
  missing="$(unreadable)"
  [ -z "$missing" ] || die "a key file the run signs with cannot be read from a login shell: $(printf '%s\n' "$missing" | paste -sd ' ' -)"
  deps || die "the Node packages are not there and could not be installed (the line above)."
  if [ "${KNOS_UPGRADE_DEPS:-1}" != 0 ]; then
    ( cd "$DEPS" && node --input-type=module -e 'const p = JSON.parse((await import("node:fs")).readFileSync("package.json", "utf8")); for (const n of Object.keys(p.dependencies || {})) await import(n);' ) \
      || die "node $(node --version 2>/dev/null) could not load a package $DEPS/package.json pins (the lines above)."
  fi
  command -v knos >/dev/null 2>&1 || echo "note: knos is not on PATH in the run's shell: the run will say so instead of printing knos status"
  echo "verified at $(stamp): the run would start. Schedule: proposals $(field indexes) on $(field rpc), run at $(utc "$(field run_at)"); $(( $(key_files | wc -l) )) key files readable; node $(node --version); the packages load. Nothing was sent."
}

# ---- taking an arrangement back --------------------------------------------------------------------------------------
cancel() {
  local kind id
  if [ ! -f "$STATE" ]; then echo "nothing is arranged (no $STATE)"; return 0; fi
  read -r kind id < "$STATE"
  case "$kind" in
    systemd) systemctl --user stop "$id.timer" >/dev/null 2>&1 || true; systemctl --user reset-failed "$id.timer" "$id.service" >/dev/null 2>&1 || true ;;
    at) atrm "$id" >/dev/null 2>&1 || true ;;
    schtasks) "$(schtasks_exe)" /Delete /TN "$id" /F >/dev/null 2>&1 || true ;;
    *) die "$STATE names a timer this script does not know ($kind)." ;;
  esac
  rm -f "${STATE:?}"
  echo "cancelled: the $kind timer $id is gone. The proposals are unchanged on chain; node scripts/governance.mjs cancel upgrade <index> withdraws one."
}

# ---- which timer works here -------------------------------------------------------------------------------------------
works() {
  case "$1" in
    systemd) command -v systemd-run >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1 ;;
    at) command -v at >/dev/null 2>&1 && { pgrep -x atd >/dev/null 2>&1 || systemctl is-active --quiet atd 2>/dev/null; } ;;
    schtasks) [ -n "$(schtasks_exe)" ] && command -v wslpath >/dev/null 2>&1 ;;
  esac
}

arrange() {
  local at kind="" k command id xml distro order="systemd at schtasks" missing nohash user logon exe
  [ -f "$SCHEDULE" ] || die "$SCHEDULE is missing. Propose the upgrades first: bash scripts/deploy_v2.sh --propose"
  at="$(field run_at)" || die "$SCHEDULE names no time (run_at): propose the upgrades again."
  field indexes >/dev/null || die "$SCHEDULE names no proposal."
  # the run executes only the build the schedule records for each proposal: one with none would never run
  nohash="$(field plan | awk '$2 == "-" { print $1 }' | paste -sd ' ' -)"
  [ -z "$nohash" ] || die "$SCHEDULE records no build (hash) for proposal $nohash: it was not written by this version's --propose. Propose again: bash scripts/deploy_v2.sh --propose. Nothing was arranged."
  [ "$at" -gt "$(date +%s)" ] || die "the time in $SCHEDULE ($(utc "$at")) has passed already. Run it now: bash scripts/schedule_upgrade.sh --run"
  # the run signs with these: one that cannot be read now will not be readable then
  missing="$(unreadable)"
  [ -z "$missing" ] || die "the run signs with key files that cannot be read now: $(printf '%s\n' "$missing" | paste -sd ' ' -). Set KNOS_FEE_PAYER and KNOS_MEMBERS to the fee payer's and the members' keypair files (or put payer.json and member-N.json in $KEYS), and arrange it again. Nothing was arranged."
  # under WSL the Windows task first: it starts the distribution, which a timer inside it cannot
  if wsl; then order="schtasks systemd at"; fi
  for k in ${WITH:-$order}; do
    if works "$k"; then kind="$k"; break; fi
  done
  [ -n "$kind" ] || die "no timer works here${WITH:+ (--with $WITH was asked)}: systemd's user manager does not answer, atd is not running, and schtasks.exe is neither on PATH nor at ${KNOS_SCHTASKS:-/mnt/c/Windows/System32/schtasks.exe}. Under WSL: add [boot] systemd=true to /etc/wsl.conf and restart WSL, or install at (sudo apt install at), or run this from a WSL whose PATH has Windows' System32. Or run it by hand after $(utc "$at"): bash scripts/schedule_upgrade.sh --run"
  [ ! -f "$STATE" ] || cancel | sed 's/^/replacing the earlier arrangement: /'
  # what the run needs of this shell, kept beside the keys: where node and knos are, and where the keys are. Paths only,
  # never a key: the key folder, the fee payer's file and the members' (as governance.mjs would find them now)
  ( umask 077
    { echo "# written by scripts/schedule_upgrade.sh when the upgrade run was arranged: paths only, never a key"
      printf 'export PATH=%q\n' "$PATH"
      printf 'export KNOS_KEYS=%q\n' "$KEYS"
      printf 'export KNOS_FEE_PAYER=%q\n' "${KNOS_FEE_PAYER:-$KEYS/payer.json}"
      for k in KNOS_MEMBERS KNOS_SCHEDULE KNOS_NODE_DIR KNOS_UPGRADE_DEPS; do
        if [ -n "${!k:-}" ]; then printf 'export %s=%q\n' "$k" "${!k}"; fi
      done; } > "$ENVFILE" )
  command="$(printf '%q' "$ROOT/scripts/schedule_upgrade.sh")"
  # every timer starts the run through a login shell (bash -l): the profile mounts and exports what a terminal has
  case "$kind" in
    systemd)
      id="$UNIT"
      systemd-run --user --unit "$id" --description "Knos: execute the proposed upgrades" --on-calendar "$(utc "$at")" \
        --timer-property=AccuracySec=1s --timer-property=Persistent=true --setenv=KNOS_KEYS="$KEYS" /bin/bash -l "$ROOT/scripts/schedule_upgrade.sh" --run >/dev/null \
        || die "systemd-run did not make the timer. Try another: --with at, or --with schtasks."
      echo "$kind $id" > "$STATE"
      echo "arranged with systemd: the user timer $id.timer runs the upgrade at $(utc "$at")."
      echo "  see it:    systemctl --user list-timers $id.timer"
      echo "  cancel it: bash scripts/schedule_upgrade.sh --cancel     (or: systemctl --user stop $id.timer)" ;;
    at)
      id="$(echo "KNOS_KEYS=$(printf '%q' "$KEYS") /bin/bash -l $command --run" | at -t "$(date_at "$at" "+%Y%m%d%H%M.%S")" 2>&1 | sed -n 's/^job \([0-9][0-9]*\) .*/\1/p' | tail -1)"
      [ -n "$id" ] || die "at did not take the job. Try another: --with systemd, or --with schtasks."
      echo "$kind $id" > "$STATE"
      echo "arranged with at: job $id runs the upgrade at $(utc "$at")."
      echo "  see it:    atq"
      echo "  cancel it: bash scripts/schedule_upgrade.sh --cancel     (or: atrm $id)" ;;
    schtasks)
      id="$TASK" distro="${KNOS_WSL_DISTRO:-${WSL_DISTRO_NAME:-Ubuntu-24.04}}" xml="$KEYS/upgrade-run.task.xml"
      # an XML task, because its start time is written as a UTC instant: `schtasks /ST` reads the time in the Windows
      # user's locale and time zone, which this script cannot know. UTF-16 with a mark, as the Task Scheduler wants it
      # the Windows user whose logon also starts the run: whoami.exe beside schtasks.exe says who this is
      exe="$(schtasks_exe)"
      user="${KNOS_WIN_USER:-$("$(dirname "$exe")/whoami.exe" 2>/dev/null | tr -d '\r' | head -n 1 || true)}"
      [ "$user" != - ] || user=""
      task_xml() {      # $1: the user of the logon trigger, or nothing for a task without one
        printf '<?xml version="1.0" encoding="UTF-16"?>\n<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        printf '  <RegistrationInfo><Description>Knos: execute the proposed upgrades, then knos status</Description></RegistrationInfo>\n'
        printf '  <Triggers><TimeTrigger><StartBoundary>%s</StartBoundary><Enabled>true</Enabled></TimeTrigger>' "$(date_at "$at" -u "+%Y-%m-%dT%H:%M:%SZ")"
        # at this user's next logon, from the time on and for 14 days: a start nobody was logged on for is made then
        if [ -n "$1" ]; then
          printf '<LogonTrigger><StartBoundary>%s</StartBoundary><EndBoundary>%s</EndBoundary><Enabled>true</Enabled><UserId>%s</UserId></LogonTrigger>' \
            "$(date_at "$at" -u "+%Y-%m-%dT%H:%M:%SZ")" "$(date_at "$((at + 1209600))" -u "+%Y-%m-%dT%H:%M:%SZ")" "$(printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g')"
        fi
        printf '</Triggers>\n'
        printf '  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><StartWhenAvailable>true</StartWhenAvailable><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'
        printf '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><WakeToRun>true</WakeToRun><ExecutionTimeLimit>PT1H</ExecutionTimeLimit></Settings>\n'
        # wsl.exe inside a headless console: started by the Task Scheduler in a console of its own, wsl.exe was ended
        # with STATUS_CONTROL_C_EXIT after about 20 seconds (seen on Windows 10), taking the run with it half way
        printf '  <Actions><Exec><Command>C:\\Windows\\System32\\conhost.exe</Command><Arguments>--headless C:\\Windows\\System32\\wsl.exe -d %s -- env KNOS_KEYS=%s /bin/bash -l %s --run</Arguments></Exec></Actions>\n</Task>\n' \
          "$distro" "$(printf '%q' "$KEYS" | sed 's/&/\&amp;/g; s/</\&lt;/g')" "$(printf '%s' "$command" | sed 's/&/\&amp;/g; s/</\&lt;/g')"
      }
      logon="at the next logon of $user"
      task_xml "$user" | { printf '\xff\xfe'; iconv -f UTF-8 -t UTF-16LE; } > "$xml"
      if [ -z "$user" ] || ! "$exe" /Create /TN "$id" /XML "$(wslpath -w "$xml")" /F >/dev/null; then
        # without the logon trigger: Windows did not take it, or nobody could be named
        logon=""
        task_xml "" | { printf '\xff\xfe'; iconv -f UTF-8 -t UTF-16LE; } > "$xml"
        "$exe" /Create /TN "$id" /XML "$(wslpath -w "$xml")" /F >/dev/null || die "schtasks.exe did not make the task (the lines above say why)."
      fi
      echo "$kind $id" > "$STATE"
      echo "arranged with the Windows Task Scheduler: the task $id starts wsl.exe -d $distro at $(utc "$at"), whether or not a WSL window is open."
      echo "  It starts at that time; as soon as possible after it when that start was missed (the machine was off or asleep);"
      if [ -n "$logon" ]; then echo "  and $logon after that time, for 14 days. No password is stored. A second start after success does nothing."
      else echo "  NOTE: no logon trigger (Windows took none, or KNOS_WIN_USER names nobody): be logged on to Windows at that time, or run it by hand after it."; fi
      echo "  check it:  schtasks.exe /Query /TN $id /V /FO LIST     Next Run Time: the time above, in Windows' own zone. Last Result: 267011 before"
      echo "             the first start (the task has not run yet), 0 after a run that ended well. Then: bash scripts/schedule_upgrade.sh --show"
      echo "  cancel it: bash scripts/schedule_upgrade.sh --cancel     (or: schtasks.exe /Delete /TN $id /F)" ;;
  esac
  if [ "$kind" != schtasks ] && wsl; then
    echo "NOTE: this is WSL. A $kind timer fires only if this distribution is running at that time: keep a WSL window open until then,"
    echo "      or arrange it with Windows instead: bash scripts/schedule_upgrade.sh --with schtasks"
  fi
  deps | sed 's/^[0-9: -]*UTC  //' || echo "NOTE: the run checks again and stops with nothing sent if they are still missing then. Now: npm ci --prefix scripts"
  echo "A dry trigger, now: bash scripts/schedule_upgrade.sh --verify"
  echo "The run starts with bash -l and reads $ENVFILE: the fee payer's and $(( $(key_files | wc -l) - 1 )) member key file(s), each readable now."
  echo "It will run, for proposals $(field indexes) on $(field rpc): node scripts/governance.mjs upgrade execute <index>, then knos status."
  echo "Each is executed only while its buffer holds the build proposed:"
  field plan | while read -r index hash program; do echo "  proposal $index: $program, build $hash"; done
  echo "The log: $LOG     (the upgrades can be executed from $(utc "$(field executable_from)"); the run is ten minutes later)"
}

show() {
  if [ -f "$SCHEDULE" ]; then echo "schedule: proposals $(field indexes) on $(field rpc), executable from $(utc "$(field executable_from)"), run at $(utc "$(field run_at)")"
    field plan | while read -r index hash program; do echo "  proposal $index: $program, build $hash"; done
  else echo "schedule: none ($SCHEDULE does not exist)"; fi
  if [ -f "$STATE" ]; then echo "timer: $(cat "$STATE")"; else echo "timer: none arranged"; fi
  if [ -f "$SCHEDULE" ] && [ -f "$DONE" ] && [ "$(cat "$DONE")" = "$(schedule_key)" ]; then echo "done: a run executed every proposal of this schedule; another start does nothing"
  elif [ -f "$SCHEDULE" ]; then echo "done: no run has executed every proposal of this schedule yet"; fi
  local missing
  missing="$(unreadable)"
  # $(( )) around wc: the BSD wc of macOS pads its count with spaces
  if [ -z "$missing" ]; then echo "keys: the $(( $(key_files | wc -l) )) key files the run signs with can be read now"
  else echo "keys: the run could NOT start now: it cannot read $(printf '%s\n' "$missing" | paste -sd ' ' -)"; fi
  if [ "${KNOS_UPGRADE_DEPS:-1}" = 0 ]; then echo "packages: not checked (KNOS_UPGRADE_DEPS=0)"
  else missing="$(deps_missing 2>&1 | paste -sd ' ' -)"
    if [ -z "$missing" ]; then echo "packages: every package $DEPS/package.json pins is installed"
    else echo "packages: MISSING from $DEPS/node_modules: $missing (the run installs them first: npm ci --prefix scripts --omit=optional)"; fi
  fi
  if [ -f "$LOG" ]; then echo "log ($LOG), its last lines:"; tail -n 12 "$LOG" | sed 's/^/  /'; else echo "log: nothing has run yet"; fi
}

case "$ACTION" in
  run) run ;;
  cancel) cancel ;;
  show) show ;;
  verify) verify ;;
  schedule) arrange ;;
esac
