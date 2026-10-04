#!/usr/bin/env bash
# The upgrade drill: a program of the second deployment is upgraded through the upgrade multisig, on a validator on this
# machine that runs the real Squads program, and the 48 hours are shown to hold. Nothing here reaches a public cluster:
# any endpoint that is not on this machine is refused.
#
#   bash scripts/drill_upgrade.sh --from-devnet [knos_pay|knos_oidc]      (default knos_pay)
#       starts a validator of its own that holds, copied from devnet: the bytes of both programs as deployed (their
#       upgrade authority is the upgrade vault there, and so here), the Squads program, and both multisig accounts with
#       one change: each member's key is replaced by a key made for the drill, because the members' real keys are not
#       on this machine and must not be. Threshold, time lock and everything else are devnet's. Needs no key at all.
#       The validator is stopped and its folder removed at the end (--keep leaves both).
#   bash scripts/deploy_v2.sh --localnet --keep          the deployment on a local validator; it prints the ledger folder
#   KNOS_LEDGER=<that ledger> bash scripts/drill_upgrade.sh [knos_pay|knos_oidc]
#       against that validator, with the key folder's own member keys
#
# Steps (the first thing that is not as it should be stops the run, exit 1)
#   1 the cluster   a validator on this machine; both multisigs are as the design fixes them (governance.mjs show
#                   --check); the program's upgrade authority is the upgrade vault
#   2 propose       a no-op upgrade: the program's own bytes are dumped, written to a buffer and handed to the vault;
#                   governance.mjs upgrade propose, approved by the member keys given
#   3 too early     governance.mjs upgrade execute is refused by its own reading of the proposal; sent anyway
#                   (--unchecked), the Squads program refuses it (TimeLockNotReleased). The program is unchanged
#   4 48 hours      the clock is moved past the time lock (see "The clock" below)
#   5 execute       governance.mjs upgrade execute: the program was deployed again in a later slot, with the same
#                   executable hash, and its upgrade authority is still the vault
#   6 cancel        a second buffer and proposal, approved; governance.mjs cancel upgrade, by the member keys; execute is
#                   refused by the script and, sent anyway, by the Squads program (InvalidProposalStatus), before its
#                   48 hours and after them. The program is unchanged
#
# The clock. A Surfpool fork moves its clock when asked (surfnet_timeTravel), and that is tried first. A
# solana-test-validator has no such call: it is stopped and started again on the same ledger with --warp-slot. Measured
# with agave 3.0.0: after a warp the Clock sysvar reads the time the epoch began plus 0.3 s for each slot of the epoch
# (the runtime lets the clock run at most 25% behind 0.4 s a slot; from a snapshot it read 0.4 s a slot), and never
# less than before. So 48 hours take up to 576,000 slots inside one epoch, and an epoch of the default length (432,000 slots) can carry the clock 36 hours at
# most: scripts/deploy_v2.sh --localnet starts its validator with epochs of 1,728,000 slots, and a validator started
# any other way needs --slots-per-epoch 1728000. A warp starts from the newest snapshot, not from the ledger's last
# block, so the script waits for a snapshot newer than its own transactions before it restarts (up to a minute or two
# each time). The restart needs KNOS_LEDGER (and finds the validator's process by it, or takes KNOS_VALIDATOR_PID).
# The validator is left running afterwards.
#
# What it reads
#   KNOS_RPC            the validator (default http://127.0.0.1:8899); must be on this machine
#   KNOS_CLONE_FROM     --from-devnet: the cluster copied (default https://api.devnet.solana.com)
#   KNOS_LOCAL_PORT     --from-devnet: the validator's RPC port (default 8899)
#   KNOS_LEDGER         the test validator's ledger folder, for the restart that moves the clock
#   KNOS_VALIDATOR_PID  its process id (default: found by the ledger folder)
#   KNOS_KEYS, KNOS_FEE_PAYER, KNOS_MEMBERS    as scripts/deploy_v2.sh and scripts/governance.mjs read them: the fee
#                       payer and at least as many member keys as the multisig's threshold
#   KNOS_DRILL_LOG      a file that gets one line per step: its name, what was checked, pass (tab separated).
#                       python scripts/drills.py --upgrade-log FILE puts those rows in docs/DRILLS.md
#   PYTHON              the Python that has this repository's requirements (default python3)
#
# Needs: solana, solana-keygen and (for the restart) solana-test-validator; node 20 or later with
# `npm ci --prefix scripts` done; Python with this repository's requirements (pip install -e .).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD

NAME=knos_pay FROM_DEVNET=0 KEEP=0
for arg in "$@"; do
  case "$arg" in
    knos_pay|knos_oidc) NAME="$arg" ;;
    --from-devnet) FROM_DEVNET=1 ;;
    --keep) KEEP=1 ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "usage: bash scripts/drill_upgrade.sh [--from-devnet [--keep]] [knos_pay|knos_oidc]" >&2; exit 2 ;;
  esac
done

KEYS="${KNOS_KEYS:-$ROOT/.knos-keys}"
PAYER="${KNOS_FEE_PAYER:-$KEYS/payer.json}"
PYTHON="${PYTHON:-python3}"
RPC="${KNOS_RPC:-http://127.0.0.1:8899}"
LEDGER="${KNOS_LEDGER:-}"
LOG="${KNOS_DRILL_LOG:-}"
LOCK=172800
WORK="$(mktemp -d "${TMPDIR:-/tmp}/knos-drill.XXXXXX")"
OUT="$WORK/out.txt"
OWN=0       # 1: the validator is this script's own (--from-devnet)
SETUP="the validator at $RPC"
cleanup() {
  local pid
  if [ "$OWN" = 1 ] && [ "$KEEP" = 0 ]; then pid="$(validator_pid || true)"; [ -z "$pid" ] || kill "$pid" 2>/dev/null || true; fi
  if [ "$OWN" = 0 ] || [ "$KEEP" = 0 ]; then rm -rf "$WORK"; fi
}
trap cleanup EXIT

die() { echo "stopped: $*" >&2; exit 1; }
step() { echo; echo "[$1/6] $2"; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not on PATH. $2"; }
pinned() { "$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$ROOT/programs-v2/program_ids.json" "$1"; }
py() { PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" "$ROOT/scripts/deploy_v2.py" --rpc "$RPC" --payer "$PAYER" "$@"; }
sol() { solana --url "$RPC" --keypair "$PAYER" --commitment confirmed "$@"; }
governance() { KNOS_KEYS="$KEYS" KNOS_FEE_PAYER="$PAYER" node "$ROOT/scripts/governance.mjs" "$@" --rpc "$RPC"; }
# the chain's clock, in seconds
now() { PYTHONPATH="$ROOT/src" "$PYTHON" -c 'import sys; from knos import chain; print(chain.Ledger(sys.argv[1]).now())' "$RPC"; }
day() { "$PYTHON" -c 'import sys, datetime; print(datetime.datetime.fromtimestamp(int(sys.argv[1]), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))' "$1"; }
passed() { echo "  ok  $2"; if [ -n "$LOG" ]; then printf '%s\t%s\tpass\n' "$1" "$2" >> "$LOG"; fi; }
# HAVE (the executable hash on chain), AUTHORITY (the upgrade authority) and SLOT (the slot of the last deployment) of the program
program_state() {
  local state
  state="$(py program "$NAME")" || die "cannot read $NAME from $RPC."
  read -r HAVE AUTHORITY <<< "$state"
  [ "$HAVE" != absent ] || die "$NAME $ID is not deployed on $RPC. Deploy first: bash scripts/deploy_v2.sh --localnet --keep"
  SLOT="$(sol program show "$ID" | awk '/Last Deployed In Slot/ { print $NF }')"
  [ -n "$SLOT" ] || die "solana program show $ID did not say in which slot $NAME was last deployed."
}
# runs governance.mjs, keeps what it printed in $OUT, shows it indented; its exit code is the function's
gov() { local rc=0; governance "$@" > "$OUT" 2>&1 || rc=$?; sed 's/^/    /' "$OUT"; return "$rc"; }
# a refusal: the command must fail, and what it printed must contain $1
refused() {
  local want="$1"; shift
  if gov "$@"; then die "node scripts/governance.mjs $* went through, and it must be refused."; fi
  grep -q "$want" "$OUT" || die "node scripts/governance.mjs $* was refused, but not for the reason expected ($want)."
}

# ---- the clock --------------------------------------------------------------------------------------------------------
validator_pid() {
  if [ -n "${KNOS_VALIDATOR_PID:-}" ]; then echo "$KNOS_VALIDATOR_PID"; return; fi
  pgrep -f "solana-test-validator.*--ledger $LEDGER( |$)" | head -1
}

# the slot of the newest full snapshot in the ledger folder (0: none)
newest_snapshot() {
  local best=0 f n
  for f in "$LEDGER"/snapshot-*.tar.*; do
    n="${f##*/snapshot-}"; n="${n%%-*}"
    case "$n" in ''|*[!0-9]*) continue ;; esac
    if [ "$n" -gt "$best" ]; then best="$n"; fi
  done
  echo "$best"
}

restart_at_slot() {
  local slot="$1" port="${RPC##*:}" pid mark
  need solana-test-validator "It comes with the Solana command line tools."
  pid="$(validator_pid)" || true
  [ -n "$pid" ] || die "no solana-test-validator runs on the ledger $LEDGER. Set KNOS_VALIDATOR_PID, or start it: bash scripts/deploy_v2.sh --localnet --keep"
  # A restart with --warp-slot does not replay the ledger: it warps from the newest snapshot, and with none from
  # genesis (measured: a proposal approved a minute before the restart, and the fee payer's SOL, were gone after it).
  # So the restart waits for a full snapshot that is newer than everything done so far; a test validator writes one
  # every 100 slots.
  mark="$(sol slot)"
  for _ in $(seq 300); do [ "$(newest_snapshot)" -ge "$mark" ] && break; sleep 1; done
  [ "$(newest_snapshot)" -ge "$mark" ] || die "the validator wrote no full snapshot at or after slot $mark within 300 seconds (the newest in $LEDGER is of slot $(newest_snapshot)): without one a restart would lose what was done so far."
  kill "$pid"
  for _ in $(seq 60); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  kill -0 "$pid" 2>/dev/null && die "the validator (pid $pid) did not stop within 60 seconds."
  # the same ledger and ports as scripts/deploy_v2.sh gave it; no --reset: every account stays
  nohup solana-test-validator --quiet --ledger "$LEDGER" --bind-address 127.0.0.1 --rpc-port "$port" --faucet-port "$((port + 2))" \
    --gossip-port "$((port + 3))" --dynamic-port-range "$((port + 4))-$((port + 40))" --warp-slot "$slot" > "$LEDGER/validator-warp.log" 2>&1 &
  KNOS_VALIDATOR_PID=$!
  disown
  for _ in $(seq 180); do solana --url "$RPC" cluster-version >/dev/null 2>&1 && break; sleep 1; done
  solana --url "$RPC" cluster-version >/dev/null 2>&1 || { tail -5 "$LEDGER/validator-warp.log" >&2; die "the validator did not come back on $RPC within 180 seconds after --warp-slot $slot."; }
  # the slot it warped to still carries the old clock: the warped one is in the blocks made after it
  for _ in $(seq 120); do [ "$(sol slot 2>/dev/null || echo 0)" -gt "$((slot + 2))" ] && return 0; sleep 1; done
  die "the validator came back at slot $slot and made no block after it within 120 seconds."
}

# moves the chain's clock to $1 or later
warp_to() {
  local target="$1" have rc=0 slot room jump tries=0
  have="$(now)"
  if [ "$have" -ge "$target" ]; then return 0; fi
  # a Surfpool fork: asked until it is there (a move can land minutes short), as scripts/rehearse_fork.py does
  PYTHONPATH="$ROOT/src" "$PYTHON" - "$RPC" "$target" <<'PY' || rc=$?
import sys
from knos import chain
url, target = sys.argv[1], int(sys.argv[2])
asked = target + 300
for _ in range(6):
    try:
        chain.call(url, "surfnet_timeTravel", [{"absoluteTimestamp": asked * 1000}], timeout=60)
    except chain.RpcError as why:
        sys.exit(3 if "ethod not found" in str(why) else f"surfnet_timeTravel failed: {why}")
    have = chain.Ledger(url).now()
    if have >= target:
        sys.exit(0)
    asked += target - have + 300
sys.exit("the fork's clock did not reach the time asked for after six tries")
PY
  if [ "$rc" = 0 ]; then return 0; fi
  [ "$rc" = 3 ] || die "the clock could not be moved on $RPC."
  [ -n "$LEDGER" ] || die "$RPC is not a Surfpool fork, so its clock moves only by a restart with --warp-slot: set KNOS_LEDGER to the validator's ledger folder (scripts/deploy_v2.sh --localnet --keep prints it)."
  [ -d "$LEDGER" ] || die "the ledger folder $LEDGER does not exist."
  while [ "$(now)" -lt "$target" ]; do
    tries=$((tries + 1))
    [ "$tries" -le 3 ] || die "the validator's clock reads $(day "$(now)") after three restarts with --warp-slot, and $(day "$target") was asked."
    # 0.3 s a slot, and 15 minutes over: a validator that has run for a while is a little ahead of 0.3 s a slot already
    jump=$(( (target - $(now) + 900) * 10 / 3 ))
    room="$(sol epoch-info --output json | "$PYTHON" -c 'import json, sys; e = json.load(sys.stdin); print(e["slotsInEpoch"] - e["slotIndex"])')"
    [ "$jump" -lt "$((room - 64))" ] || die "the clock has to move $jump slots and this epoch has $room left; a warp into the next epoch starts the count again. Start the validator with --slots-per-epoch 1728000 or more (scripts/deploy_v2.sh --localnet does)."
    slot="$(sol slot)"
    echo "  the validator is restarted on its ledger with --warp-slot $((slot + jump)) (slot $slot now)"
    restart_at_slot "$((slot + jump))"
  done
}

# ---- a validator of this script's own, with devnet's programs and multisigs ---------------------------------------------
from_devnet() {
  need solana-test-validator "It comes with the Solana command line tools."
  local port="${KNOS_LOCAL_PORT:-8899}" from="${KNOS_CLONE_FROM:-https://api.devnet.solana.com}" n
  KEYS="$WORK/keys" PAYER="$WORK/keys/payer.json" LEDGER="$WORK/ledger" RPC="http://127.0.0.1:$port" OWN=1
  # the members are the keys made below (member-N.json in $KEYS), never the operator's own: governance.mjs takes
  # KNOS_MEMBERS before the key folder, and a release shell has it set to the real members' files
  unset KNOS_MEMBERS
  mkdir -p "$KEYS"
  for n in payer member-1 member-2 member-3 member-4 member-5; do solana-keygen new --no-bip39-passphrase --silent --force --outfile "$KEYS/$n.json" >/dev/null; done
  # both multisig accounts as the cluster has them, with each member's key replaced by one made above (sorted, as the
  # Squads program keeps its members); the files a validator loads with --account. Unused member keys are removed.
  PYTHONPATH="$ROOT/src" "$PYTHON" - "$from" "$WORK" "$ROOT/programs-v2/program_ids.json" <<'PY' || die "the multisig accounts could not be read from $from."
import base64, json, os, sys
from solders.keypair import Keypair
from knos import chain
url, work, ids = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3]))
files = [f"{work}/keys/member-{n}.json" for n in range(1, 6)]
made = {f: Keypair.from_bytes(bytes(json.load(open(f)))).pubkey() for f in files}
most = 0
for name in ("upgrade_multisig", "guardian_multisig"):
    v = chain.call(url, "getAccountInfo", [ids[name], {"encoding": "base64"}], timeout=60)["value"]
    if v is None or v["owner"] != ids["squads_program"]:
        sys.exit(f"{name} {ids[name]} is not an account of the Squads program on {url}")
    d = bytearray(base64.b64decode(v["data"][0]))
    at = 94 + (33 if d[94] else 1) + 1                      # past the rent collector and the bump: the member list
    count = int.from_bytes(d[at:at + 4], "little")
    if count > len(files):
        sys.exit(f"{name} has {count} members; this drill makes keys for {len(files)}")
    for k, key in enumerate(sorted(list(made.values())[:count], key=bytes)):
        d[at + 4 + 33 * k:at + 36 + 33 * k] = bytes(key)
    most = max(most, count)
    json.dump({"pubkey": ids[name], "account": {"lamports": v["lamports"], "data": [base64.b64encode(bytes(d)).decode(), "base64"], "owner": v["owner"],
                                                "executable": False, "rentEpoch": 0, "space": len(d)}}, open(f"{work}/{name}.json", "w"))
    print(f"  {name} {ids[name]}: threshold {int.from_bytes(d[72:74], 'little')} of {count}, time lock {int.from_bytes(d[74:78], 'little')} s, as on {url}; its members' keys replaced")
for f in files[most:]:
    os.remove(f)
PY
  solana-test-validator --reset --quiet --ledger "$LEDGER" --bind-address 127.0.0.1 --rpc-port "$port" --faucet-port "$((port + 2))" \
    --gossip-port "$((port + 3))" --dynamic-port-range "$((port + 4))-$((port + 40))" --slots-per-epoch 1728000 --url "$from" \
    --clone-upgradeable-program "$(pinned squads_program)" --clone BSTq9w3kZwNwpBXJEvTZz2G9ZTNyKBvoSeXMvwb4cNZr \
    --clone-upgradeable-program "$(pinned knos_oidc)" --clone-upgradeable-program "$(pinned knos_pay)" \
    --account "$(pinned upgrade_multisig)" "$WORK/upgrade_multisig.json" --account "$(pinned guardian_multisig)" "$WORK/guardian_multisig.json" \
    > "$WORK/validator.log" 2>&1 &
  KNOS_VALIDATOR_PID=$!
  for _ in $(seq 120); do solana --url "$RPC" cluster-version >/dev/null 2>&1 && break; sleep 1; done
  solana --url "$RPC" cluster-version >/dev/null 2>&1 || { tail -5 "$WORK/validator.log" >&2; die "the local validator did not start within 120 seconds (it copies accounts from $from: set KNOS_CLONE_FROM to an endpoint that answers)."; }
  solana --url "$RPC" airdrop 100 "$(solana-keygen pubkey "$PAYER")" >/dev/null || die "the local validator gave the fee payer no SOL."
  SETUP="a local validator that holds, copied from $from, the bytes of both programs as deployed, the Squads program and both multisig accounts, each member's key replaced by a key made for the drill"
  echo "local validator on $RPC (folder $WORK): $SETUP"
}

# ---- a buffer with the program's own bytes, owned by the vault -----------------------------------------------------------
BUFFER=""
noop_buffer() {
  local file="$WORK/$NAME-$1.so" key="$WORK/buffer-$1.json"
  sol program dump "$ID" "$file" >/dev/null || die "cannot dump $NAME from $RPC."
  solana-keygen new --no-bip39-passphrase --silent --force --outfile "$key" >/dev/null
  BUFFER="$(solana-keygen pubkey "$key")"
  sol program write-buffer "$file" --buffer "$key" --buffer-authority "$PAYER" --use-rpc >/dev/null || die "the buffer could not be written (the fee payer needs about 3 SOL: solana airdrop 10 $PAYER_ADDRESS --url $RPC)."
  sol program set-buffer-authority "$BUFFER" --new-buffer-authority "$VAULT" >/dev/null || die "the buffer $BUFFER could not be handed to the upgrade vault."
}

# proposes the upgrade to $BUFFER: INDEX (the proposal) and FROM (the unix time its time lock ends). GATE says how the
# upgrade gate took it. The no-op buffer holds the bytes the program already runs. When the gate has no record of
# them, governance.mjs refuses them first, and the drill then proposes them with --ungated: the gate is checked to
# refuse, and the time lock and the vote are what this drill is about. Why there is no record is said as it is on this
# cluster: the gate program is not on it (a validator of deploy_v2.sh --localnet, or one copied from devnet without
# the gate), or the program was last deployed before the gate (the 2.0 programs: none can be made for them), or
# neither, and then only that the gate holds none. A build the gate has a record of is proposed as it is.
INDEX="" FROM="" GATE=""
# why the upgrade gate holds no record of the bytes $NAME runs (deployed in slot $SLOT), as this cluster shows it
no_record() {
  local gate gate_slot
  gate="$(sed -n 's/^export const UPGRADE_GATE = new PublicKey("\([1-9A-HJ-NP-Za-km-z]*\)").*/\1/p' "$ROOT/scripts/governance.mjs")"
  gate_slot="$(sol program show "$gate" 2>/dev/null | awk '/Last Deployed In Slot/ { print $NF }' || true)"
  if [ -z "$gate_slot" ]; then
    echo "the upgrade gate program ${gate:-of governance.mjs} is not on this cluster, so it holds no record of these bytes"
  elif [ -n "$SLOT" ] && [ "$SLOT" -lt "$gate_slot" ]; then
    echo "the upgrade gate holds no record of these bytes ($NAME was last deployed in slot $SLOT, before the gate, deployed in slot $gate_slot)"
  else
    echo "the upgrade gate holds no record of these bytes"
  fi
}
propose() {
  local iso
  if gov upgrade propose "$NAME" "$BUFFER"; then
    GATE="the upgrade gate holds a record that GitHub built it"
  else
    grep -q "the upgrade gate has no record that GitHub built" "$OUT" || die "the upgrade could not be proposed."
    GATE="governance.mjs refused it first because $(no_record), so it was proposed with --ungated"
    gov upgrade propose "$NAME" "$BUFFER" --ungated || die "the upgrade could not be proposed, even with --ungated."
  fi
  INDEX="$(sed -n 's/^on chain now: proposal \([0-9][0-9]*\) of the upgrade multisig is approved.*/\1/p' "$OUT")"
  [ -n "$INDEX" ] || die "the proposal is not approved: the member keys given are fewer than the multisig's threshold. Set KNOS_MEMBERS to enough of them."
  iso="$(sed -n 's/.*it can be executed from \([0-9TZ:-]*\) .*/\1/p' "$OUT")"
  [ -n "$iso" ] || die "governance.mjs did not say when proposal $INDEX can be executed."
  FROM="$("$PYTHON" -c 'import sys, datetime; print(int(datetime.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).timestamp()))' "$iso")"
}

# ---- run ----------------------------------------------------------------------------------------------------------------
need solana "Install the Solana command line tools (agave 2.3 or later)."
need solana-keygen "It comes with the Solana command line tools."
need node "Install Node 20 or later."
[ -d "$ROOT/scripts/node_modules/@sqds/multisig" ] || die "the scripts' packages are not installed. Run: npm ci --prefix scripts"
if [ "$FROM_DEVNET" = 1 ]; then from_devnet; fi
case "$RPC" in http://127.0.0.1:*|http://localhost:*|http://\[::1\]:*) ;; *) die "$RPC is not on this machine. This drill moves a clock and upgrades a program: it runs only against a local validator or fork." ;; esac
[ -f "$PAYER" ] || die "the fee payer's keypair $PAYER is missing. Set KNOS_FEE_PAYER (scripts/deploy_v2.sh --localnet prints the one it used)."
PAYER_ADDRESS="$(solana-keygen pubkey "$PAYER")"
ID="$(pinned "$NAME")" VAULT="$(pinned upgrade_authority)"
if [ -n "$LOG" ]; then : > "$LOG"; fi

step 1 "the cluster"
py cluster >/dev/null || die "cannot reach the validator at $RPC. Start one: bash scripts/deploy_v2.sh --localnet --keep"
governance show --check >/dev/null 2>&1 || die "the multisigs are not right on $RPC: node scripts/governance.mjs show --rpc $RPC says what is wrong."
program_state
[ "$AUTHORITY" = "$VAULT" ] || die "$NAME's upgrade authority is $AUTHORITY, not the upgrade vault $VAULT: there is nothing to drill."
HASH0="$HAVE" SLOT0="$SLOT"
echo "  ok  $RPC; both multisigs are as the design fixes them; $NAME $ID runs the build $HASH0 (deployed in slot $SLOT0), upgrade authority the vault $VAULT"
sol airdrop 10 "$PAYER_ADDRESS" >/dev/null 2>&1 || true      # a test validator gives SOL; a fork's fee payer was funded by its own cheatcode

step 2 "a no-op upgrade is proposed and approved"
noop_buffer 1
propose
FIRST="$INDEX"
[ "$((FROM - $(now)))" -gt "$((LOCK - 3600))" ] || die "proposal $FIRST can be executed $(day "$FROM"), which is not 48 hours after its approval."
passed "an upgrade is proposed" "on $SETUP: the bytes $NAME already runs, in buffer $BUFFER owned by the vault; proposal $FIRST of the upgrade multisig is approved and can be executed from $(day "$FROM"), 48 hours after the vote; $GATE"

step 3 "it cannot be executed before the 48 hours"
refused "It cannot be executed before that" upgrade execute "$FIRST"
refused "TimeLockNotReleased" upgrade execute "$FIRST" --unchecked
program_state
[ "$HAVE $SLOT $AUTHORITY" = "$HASH0 $SLOT0 $VAULT" ] || die "$NAME changed (build $HAVE, slot $SLOT, authority $AUTHORITY) although nothing was executed."
passed "no upgrade before 48 hours" "at $(day "$(now)") governance.mjs refuses to execute proposal $FIRST; sent anyway, the Squads program refuses it (TimeLockNotReleased); $NAME is unchanged (slot $SLOT0)"

step 4 "the clock moves past the time lock"
BEFORE="$(now)"
warp_to "$((FROM + 1))"
echo "  ok  the clock read $(day "$BEFORE") and reads $(day "$(now)") now"

step 5 "the upgrade is executed"
gov upgrade execute "$FIRST" || die "proposal $FIRST could not be executed after its time lock."
program_state
[ "$HAVE" = "$HASH0" ] || die "after the no-op upgrade $NAME runs the build $HAVE, not $HASH0."
[ "$SLOT" -gt "$SLOT0" ] || die "$NAME's last deployment is still slot $SLOT0: the upgrade did not run."
[ "$AUTHORITY" = "$VAULT" ] || die "after the upgrade $NAME's upgrade authority is $AUTHORITY, not the vault."
SLOT1="$SLOT"
passed "an upgrade after 48 hours" "at $(day "$(now)") proposal $FIRST is executed by the Squads program: $NAME was deployed again in slot $SLOT1 (before: $SLOT0) with the same executable hash $HASH0, and its upgrade authority is still the vault"

step 6 "a second upgrade is proposed, approved and cancelled"
noop_buffer 2
propose
SECOND="$INDEX"
gov cancel upgrade "$SECOND" || die "proposal $SECOND could not be cancelled."
grep -q "proposal $SECOND of the upgrade multisig is cancelled" "$OUT" || die "the member keys given did not cancel proposal $SECOND: a cancellation needs as many votes as the threshold."
refused "is cancelled" upgrade execute "$SECOND"
refused "InvalidProposalStatus" upgrade execute "$SECOND" --unchecked
warp_to "$((FROM + 1))"
refused "InvalidProposalStatus" upgrade execute "$SECOND" --unchecked
program_state
[ "$HAVE $SLOT $AUTHORITY" = "$HASH0 $SLOT1 $VAULT" ] || die "$NAME changed (build $HAVE, slot $SLOT, authority $AUTHORITY) although the proposal was cancelled."
passed "a cancelled upgrade never runs" "proposal $SECOND was approved, then cancelled by the members' votes; governance.mjs refuses to execute it and, sent anyway, the Squads program refuses it (InvalidProposalStatus) before its 48 hours and after them; $NAME is unchanged (slot $SLOT1). Its buffer $BUFFER stays with the vault"

echo
echo "the upgrade drill passed on $RPC: proposals $FIRST (executed after 48 hours) and $SECOND (cancelled) of the upgrade multisig $(pinned upgrade_multisig)."
if [ -n "$LEDGER" ] && { [ "$OWN" = 0 ] || [ "$KEEP" = 1 ]; }; then pid="$(validator_pid || true)"; [ -z "$pid" ] || echo "the validator is still running (pid $pid, ledger $LEDGER): stop it with kill $pid"; fi
