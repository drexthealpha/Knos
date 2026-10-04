#!/usr/bin/env bash
# Execute the proposed upgrades when their 48 hours have passed, unattended.
#
# `bash scripts/deploy_v2.sh --propose` wrote <key folder>/upgrade-schedule.json: each proposal's index and the time
# from which all of them can be executed, plus ten minutes (run_at). This script arranges for one run at that time:
#
#     node scripts/governance.mjs upgrade execute <index>      for each proposal, in the order of their indexes
#     knos status                                              what is on chain afterwards
#
# with every line of both appended to <key folder>/upgrade-run.log.
#
#   bash scripts/schedule_upgrade.sh              arrange the run, and print how to cancel it
#   bash scripts/schedule_upgrade.sh --show       what is arranged, and what the log says so far
#   bash scripts/schedule_upgrade.sh --cancel     take the arrangement back (the proposals stay as they are on chain)
#   bash scripts/schedule_upgrade.sh --run        the run itself, now: what the timer calls. Safe by hand too: a
#                                                 proposal whose time has not come is refused by governance.mjs and by
#                                                 the Squads program, and one already executed is left alone
#   --with systemd|at|schtasks                    choose the timer instead of taking the first that works here
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
#
# Needs: node 20 or later with `npm ci --prefix scripts` done, `knos` on PATH (pip install -e . or pipx install knos),
# and one of the three timers.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD

ACTION=schedule WITH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --show) ACTION=show ;;
    --cancel) ACTION=cancel ;;
    --run) ACTION=run ;;
    --with) shift; WITH="${1:-}"; case "$WITH" in systemd|at|schtasks) ;; *) echo "--with takes systemd, at or schtasks" >&2; exit 2 ;; esac ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "usage: bash scripts/schedule_upgrade.sh [--show | --cancel | --run] [--with systemd|at|schtasks]" >&2; exit 2 ;;
  esac
  shift
done

KEYS="${KNOS_KEYS:-$ROOT/.knos-keys}"
SCHEDULE="${KNOS_SCHEDULE:-$KEYS/upgrade-schedule.json}"
LOG="$KEYS/upgrade-run.log"
ENVFILE="$KEYS/upgrade-run.env"
STATE="$KEYS/upgrade-run.timer"            # how the run was arranged: the timer's kind and its name or job number
UNIT=knos-upgrade
TASK=KnosUpgrade

die() { echo "stopped: $*" >&2; exit 1; }
field() { node -e 'const s = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8")); const v = process.argv[2] === "indexes" ? s.proposals.map((p) => p.index).join(" ") : s[process.argv[2]]; if (v === undefined || v === null || v === "") process.exit(1); console.log(v);' "$SCHEDULE" "$1"; }
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

# the run is started by a timer, with a bare environment: what the arranging shell had comes first (and --show says
# what the run will have)
# shellcheck disable=SC1090  # written by this script when the run was arranged
if { [ "$ACTION" = run ] || [ "$ACTION" = show ]; } && [ -f "$ENVFILE" ]; then . "$ENVFILE"; fi
command -v node >/dev/null 2>&1 || die "node is not on PATH. Install Node 20 or later."

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
run() {
  local index failed=0 rpc missing
  [ -f "$SCHEDULE" ] || die "$SCHEDULE is missing: nothing was proposed, or the key folder is another one (KNOS_KEYS)."
  rpc="$(field rpc)" || die "$SCHEDULE names no cluster."
  mkdir -p "$(dirname "$LOG")"
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
  {
    echo "==== $(date -u "+%Y-%m-%d %H:%M:%S UTC")  the scheduled upgrade run starts (cluster $rpc; proposals $(field indexes))"
    for index in $(field indexes); do
      echo "---- node scripts/governance.mjs upgrade execute $index"
      if KNOS_KEYS="$KEYS" node "$ROOT/scripts/governance.mjs" upgrade execute "$index" --rpc "$rpc"; then
        echo "---- proposal $index: executed (or executed before)"
      else
        echo "---- proposal $index: NOT executed (the lines above say why)"; failed=$((failed + 1))
      fi
    done
    echo "---- knos status"
    if command -v knos >/dev/null 2>&1; then KNOS_RPC="$rpc" knos status || echo "---- knos status found something to look at (the lines above)"
    else echo "---- knos is not on PATH: run it by hand: KNOS_RPC=$rpc knos status"; fi
    if [ "$failed" = 0 ]; then echo "==== $(date -u "+%Y-%m-%d %H:%M:%S UTC")  done: every proposal is executed"
    else echo "==== $(date -u "+%Y-%m-%d %H:%M:%S UTC")  done: $failed proposal(s) NOT executed. Run it again by hand: bash scripts/schedule_upgrade.sh --run"; fi
  } >> "$LOG" 2>&1
  tail -n 3 "$LOG"
  [ "$failed" = 0 ]
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
  local at kind="" k command id xml distro order="systemd at schtasks" missing
  [ -f "$SCHEDULE" ] || die "$SCHEDULE is missing. Propose the upgrades first: bash scripts/deploy_v2.sh --propose"
  at="$(field run_at)" || die "$SCHEDULE names no time (run_at): propose the upgrades again."
  field indexes >/dev/null || die "$SCHEDULE names no proposal."
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
      for k in KNOS_MEMBERS KNOS_SCHEDULE; do
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
      { printf '<?xml version="1.0" encoding="UTF-16"?>\n<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        printf '  <RegistrationInfo><Description>Knos: execute the proposed upgrades, then knos status</Description></RegistrationInfo>\n'
        printf '  <Triggers><TimeTrigger><StartBoundary>%s</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>\n' "$(date_at "$at" -u "+%Y-%m-%dT%H:%M:%SZ")"
        printf '  <Settings><StartWhenAvailable>true</StartWhenAvailable><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'
        printf '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><WakeToRun>true</WakeToRun><ExecutionTimeLimit>PT1H</ExecutionTimeLimit></Settings>\n'
        # wsl.exe inside a headless console: started by the Task Scheduler in a console of its own, wsl.exe was ended
        # with STATUS_CONTROL_C_EXIT after about 20 seconds (seen on Windows 10), taking the run with it half way
        printf '  <Actions><Exec><Command>C:\\Windows\\System32\\conhost.exe</Command><Arguments>--headless C:\\Windows\\System32\\wsl.exe -d %s -- env KNOS_KEYS=%s /bin/bash -l %s --run</Arguments></Exec></Actions>\n</Task>\n' \
          "$distro" "$(printf '%q' "$KEYS" | sed 's/&/\&amp;/g; s/</\&lt;/g')" "$(printf '%s' "$command" | sed 's/&/\&amp;/g; s/</\&lt;/g')"
      } | { printf '\xff\xfe'; iconv -f UTF-8 -t UTF-16LE; } > "$xml"
      "$(schtasks_exe)" /Create /TN "$id" /XML "$(wslpath -w "$xml")" /F >/dev/null || die "schtasks.exe did not make the task (the lines above say why)."
      echo "$kind $id" > "$STATE"
      echo "arranged with the Windows Task Scheduler: the task $id starts wsl.exe -d $distro at $(utc "$at"), whether or not a WSL window is open."
      echo "  see it:    schtasks.exe /Query /TN $id /V /FO LIST"
      echo "  cancel it: bash scripts/schedule_upgrade.sh --cancel     (or: schtasks.exe /Delete /TN $id /F)" ;;
  esac
  if [ "$kind" != schtasks ] && wsl; then
    echo "NOTE: this is WSL. A $kind timer fires only if this distribution is running at that time: keep a WSL window open until then,"
    echo "      or arrange it with Windows instead: bash scripts/schedule_upgrade.sh --with schtasks"
  fi
  echo "The run starts with bash -l and reads $ENVFILE: the fee payer's and $(( $(key_files | wc -l) - 1 )) member key file(s), each readable now."
  echo "It will run, for proposals $(field indexes) on $(field rpc): node scripts/governance.mjs upgrade execute <index>, then knos status."
  echo "The log: $LOG     (the upgrades can be executed from $(utc "$(field executable_from)"); the run is ten minutes later)"
}

show() {
  if [ -f "$SCHEDULE" ]; then echo "schedule: proposals $(field indexes) on $(field rpc), executable from $(utc "$(field executable_from)"), run at $(utc "$(field run_at)")"
  else echo "schedule: none ($SCHEDULE does not exist)"; fi
  if [ -f "$STATE" ]; then echo "timer: $(cat "$STATE")"; else echo "timer: none arranged"; fi
  local missing
  missing="$(unreadable)"
  # $(( )) around wc: the BSD wc of macOS pads its count with spaces
  if [ -z "$missing" ]; then echo "keys: the $(( $(key_files | wc -l) )) key files the run signs with can be read now"
  else echo "keys: the run could NOT start now: it cannot read $(printf '%s\n' "$missing" | paste -sd ' ' -)"; fi
  if [ -f "$LOG" ]; then echo "log ($LOG), its last lines:"; tail -n 12 "$LOG" | sed 's/^/  /'; else echo "log: nothing has run yet"; fi
}

case "$ACTION" in
  run) run ;;
  cancel) cancel ;;
  show) show ;;
  schedule) arrange ;;
esac
