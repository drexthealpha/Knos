#!/usr/bin/env bash
# Deploy the second deployment (programs-v2) to devnet, set it up, and hand both programs' upgrade authority to the
# vault of the upgrade multisig, so that from then on a program changes only by a proposal that waits 48 hours in
# public. Run it again after any failure: every step reads the chain first and does only what is missing. The last
# line it prints says what is on chain now.
#
#   bash scripts/deploy_v2.sh               devnet (or the cluster of KNOS_RPC; mainnet-beta is refused)
#   bash scripts/deploy_v2.sh --localnet    the same steps against a local validator this script starts and stops:
#                                           a dry run with the real keys that touches no cluster. With KNOS_RPC set
#                                           it uses the local validator or Surfpool already running there instead.
#   bash scripts/deploy_v2.sh --localnet --keep     leaves that validator running, to try governance.mjs against it
#
# Since 0.3.13, one more thing a run (each alone, never two in one run; each safe to run again):
#   bash scripts/deploy_v2.sh --new         deploy the NEW programs knos_meter, knos_passkey and upgrade_gate at their
#                                           pinned ids, from <name>-keypair.json in the key folder (the gate's may be
#                                           named knos_gate-keypair.json), with the same resumable buffers, and hand
#                                           their upgrade authority to the upgrade vault. Needs the multisigs (the
#                                           plain run made them).
#   bash scripts/deploy_v2.sh --rc          a STAGING copy of the 2.1 builds of knos_oidc and knos_pay under fresh ids
#                                           (keypairs made in <key folder>/rc; upgrade authority: the fee payer), with
#                                           the faucet, GitHub's genesis keys and the fee account set up on it, and
#                                           <key folder>/rc/program_ids.json written: a client run with
#                                           KNOS_PROGRAM_IDS=<that file> talks to the staging programs, so every new
#                                           instruction can be tried on devnet before the real upgrade executes. The
#                                           staging escrow reads tokens of the verifier its build names (OIDC_ID in
#                                           knos_pay's source): the script says which one that is.
#   bash scripts/deploy_v2.sh --rc-close    close the staging programs and their buffers; the SOL returns to the fee
#                                           payer. Closed ids can never be used again: the next --rc makes new ones.
#   bash scripts/deploy_v2.sh --propose [--replace] [--ungated]
#                                           the upgrade of the four programs the upgrade vault holds (knos_oidc, knos_pay,
#                                           knos_meter, knos_passkey) to the verified builds; one that runs this build
#                                           already is skipped. Each
#                                           build is written to a buffer (resumable), its record at the upgrade gate is
#                                           waited for (program.yml's gate job has GitHub sign the hash of each build
#                                           it made on main or a release tag, and a relayer carries that to the gate;
#                                           the record is written here first when KNOS_GATE_TOKENS has the token), the
#                                           buffer is handed to the upgrade vault, the proposal is created and approved
#                                           by the member keys of the key folder. It prints when all can be executed
#                                           and writes that to <key folder>/upgrade-schedule.json, which
#                                           scripts/schedule_upgrade.sh reads. A build with no record at the gate
#                                           after the wait is refused. --ungated is for an emergency only (GitHub or
#                                           every relayer is down and a fix cannot wait): it proposes such a build
#                                           without waiting, and says so loudly, here and in the proposal's own output.
#                                           While an older proposal for one of the four can still run and would deploy
#                                           ANOTHER build, nothing is proposed: --replace first withdraws each of those
#                                           by the member keys' votes (printing its index, program and build), then
#                                           proposes. Two approved proposals for one program would both execute.
#                                           Before any of that it makes its PLAN: the programs whose build here is not
#                                           the one the chain runs. A release says which programs it changes
#                                           (KNOS_CHANGES; 0.3.18: knos_oidc and knos_pay, one set), and a program outside that list
#                                           whose build differs STOPS the run with nothing withdrawn, written or
#                                           proposed: its file is then not the verified build the chain runs (the
#                                           earlier proposals have not executed, or it is a rebuild whose bytes moved
#                                           with a version or a linked crate), and proposing it would upgrade a
#                                           program the release never meant to touch.
#   Each also takes --localnet with KNOS_RPC naming the validator a `--localnet --keep` run left running.
#
# Steps (each reads the chain first; a step that is already done says so and sends nothing)
#   1 multisigs  both Squads multisigs exist as the design fixes them (governance.mjs show --check); created with
#                governance.mjs create when they do not (it takes the member keys of the key folder, threshold 2)
#   2 build      the verified build of both programs, program.yml's command: solana-verify build "$PWD"
#                --workspace-path "$PWD/programs-v2" --library-name <name> (from the repository's root), for knos_oidc,
#                then knos_pay, in the docker image program.yml pins, the repository mounted (knos_meter, a member of
#                the workspace, reads crates/knos-oidc-interface); the default
#                features, which is the devnet build. Prints each executable hash. Not repeated while programs-v2
#                and the interface crate are unchanged since the last build.
#   3 deploy     solana program deploy, each program under its own keypair, with a buffer keypair kept in the key
#                folder (the same command continues a deploy that failed half way), --max-sign-attempts 60 and a
#                compute unit price. Skipped for a program whose on-chain bytes are already this build.
#   4 faucet     InitFaucet: the escrow's test-USDC mint
#   5 keys       RegisterKey and KeyParams for GitHub's four genesis keys. They verify for 30 days from now; the
#                rotate workflow's Refresh keeps them alive after that
#   6 fee        the fee owner's token account for the faucet's mint
#   7 hand-over  after checking both multisigs on chain once more: solana program set-upgrade-authority to the
#                upgrade vault, with --skip-new-upgrade-authority-signer-check (a vault cannot sign from a command
#                line). Last, because nothing above can be done by this script afterwards.
#   then         every address of the deployment, every transaction on chain that touches one, and one line that
#                says what is on chain now. The exit code is 0 only when the deployment is complete.
#
# What it reads
#   KNOS_KEYS          the key folder (default: .knos-keys in the repository, which git ignores). It holds
#                      knos_oidc_v2-keypair.json, knos_pay_v2-keypair.json, upgrade-create-key.json,
#                      guardian-create-key.json, payer.json, member-1.json, member-2.json, member-3.json; this script
#                      adds the buffer keypairs (--propose: one per program
#                      and build, <name>-upgrade-buffer-<the build's hash, 16 characters>.json)
#   KNOS_FEE_PAYER     the fee payer's keypair (default: payer.json in the key folder). It pays, and it is the
#                      programs' upgrade authority until step 8
#   KNOS_MEMBERS       the multisig members' keypair files or addresses, separated by spaces (default: member-N.json)
#   KNOS_RPC           the cluster (default https://api.devnet.solana.com)
#   KNOS_SO_DIR        a folder with knos_oidc.so and knos_pay.so to deploy instead of building: the verified-build
#                      artifacts of program.yml, say. Step 2 then only prints their hashes. --new reads knos_meter.so,
#                      knos_passkey.so and upgrade_gate.so there (upgrade_gate is never built here: it comes from
#                      program.yml's artifacts)
#   KNOS_RC_SO_DIR     --rc: a folder with the knos_oidc.so and knos_pay.so to stage, when they are not the builds
#                      above (a build of knos_pay whose OIDC_ID is the staging verifier, say)
#   KNOS_GATE_TOKENS   --propose: a folder with <program>.jwt for each of the four, the tokens program.yml asked GitHub
#                      for (audience gate:<program>:<executable hash>). With them a missing record is written
#   KNOS_CHANGES       --propose: the programs this release changes, separated by spaces (default: "knos_oidc knos_pay",
#                      0.3.18's one proposal set). Only these are proposed; see --propose above
#   KNOS_GATE_WAIT     --propose: how many seconds to wait for a build's record at the upgrade gate before refusing
#                      (default 1800: program.yml's verified builds and the relay take about that long after a push)
#   KNOS_PRIORITY_FEE  micro-lamports per compute unit for the deploy (default 1000)
#   KNOS_USE_RPC=1     send the deploy's writes through the RPC endpoint (--use-rpc): for a provider's endpoint. It is
#                      always on for an endpoint on this machine (a local validator or a Surfpool fork)
#   KNOS_CLONE_FROM    --localnet: the cluster whose Squads program the local validator copies (default
#                      https://api.devnet.solana.com, the one the real deploy will meet)
#   KNOS_LOCAL_PORT    --localnet: the local validator's RPC port (default 8899)
#   PYTHON             the Python that has this repository's requirements (default python3; pip install -e .)
#
# Needs: solana and solana-keygen (agave 2.3 or later), node 20 or later with `npm ci --prefix scripts` done, Python
# with this repository's requirements (pip install -e .), and for step 2 solana-verify and a running docker.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD

LOCALNET=0 KEEP=0 MODE="" UNGATED=0 REPLACE=0
for arg in "$@"; do
  case "$arg" in
    --localnet) LOCALNET=1 ;;
    --keep) KEEP=1 ;;
    --new|--rc|--rc-close|--propose)
      [ -z "$MODE" ] || { echo "one of --new, --rc, --rc-close, --propose in a run, not ${MODE} and ${arg}" >&2; exit 2; }
      MODE="$arg" ;;
    --ungated) UNGATED=1 ;;
    --replace) REPLACE=1 ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "usage: bash scripts/deploy_v2.sh [--localnet [--keep]] [--new | --rc | --rc-close | --propose [--replace] [--ungated]]" >&2; exit 2 ;;
  esac
done
if [ "$UNGATED" = 1 ] && [ "$MODE" != --propose ]; then echo "--ungated goes with --propose" >&2; exit 2; fi
if [ "$REPLACE" = 1 ] && [ "$MODE" != --propose ]; then echo "--replace goes with --propose" >&2; exit 2; fi

KEYS="${KNOS_KEYS:-$ROOT/.knos-keys}"
PAYER="${KNOS_FEE_PAYER:-$KEYS/payer.json}"
PRICE="${KNOS_PRIORITY_FEE:-1000}"
PYTHON="${PYTHON:-python3}"
VERIFY_IMAGE="${KNOS_VERIFY_IMAGE:-solanafoundation/solana-verifiable-build:2.3.11}"   # the image program.yml builds in
RPC="${KNOS_RPC:-https://api.devnet.solana.com}"
GATE_WAIT="${KNOS_GATE_WAIT:-1800}"
PROGRAMS="knos_oidc knos_pay"
NEW_PROGRAMS="knos_meter knos_passkey upgrade_gate"
UPGRADES="knos_oidc knos_pay knos_meter knos_passkey"   # what --propose proposes: every program the upgrade vault holds, in the order they execute
# The programs THIS release changes. --propose proposes these and no other: a build of another program that is not what
# the chain runs stops the run before anything is sent (plan, below). 0.3.18 changes knos_oidc and knos_pay; knos_meter and
# knos_passkey stay the builds of the tag scripts/bump_version.py holds their crates at (FROZEN_AT).
CHANGES="${KNOS_CHANGES:-knos_oidc knos_pay}"
RC="$KEYS/rc"                                  # the staging keypairs and ids file
SCHEDULE="$KEYS/upgrade-schedule.json"         # when the proposed upgrades can be executed: scripts/schedule_upgrade.sh reads it
WORK="" VALIDATOR=""

die() { echo "stopped: $*" >&2; exit 1; }
step() { echo; echo "[$1/7] $2"; }
part() { echo; echo "[$1] $2"; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is not on PATH. $2"; }
pinned() { "$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$ROOT/programs-v2/program_ids.json" "$1"; }
py() { PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" "$ROOT/scripts/deploy_v2.py" --rpc "$RPC" --payer "$PAYER" "$@"; }
governance() { KNOS_KEYS="$KEYS" KNOS_FEE_PAYER="$PAYER" node "$ROOT/scripts/governance.mjs" "$@" --rpc "$RPC"; }
sol() { solana --url "$RPC" --keypair "$PAYER" --commitment confirmed "$@"; }
# sol, tried up to three times: a public endpoint drops requests, and a fork reading an account for the first time can fail
# the first try. Only for a command that continues where it stopped when it is sent again (the deploy does: same buffer)
sol_again() {
  local n=1
  until sol "$@"; do
    [ "$n" -lt 3 ] || return 1
    n=$((n + 1)); echo "  the solana command failed: trying again in 5 seconds (try $n of 3)" >&2; sleep 5
  done
}
# the number in the first line of `solana <rent|balance> --lamports`. awk reads to the end and never exits early: `solana
# rent` prints an empty line after its number, and a reader that had already gone would make that write fail (Broken
# pipe), solana exit 101, and pipefail stop this script half way with no word of why
lamports() { sol "$@" --lamports | awk 'NF >= 2 && !n++ { print $(NF - 1) }'; }
# HAVE (the executable hash on chain, or "absent") and AUTHORITY (the upgrade authority, or "none") of a program
program_state() {
  local state
  state="$(py program "$1")" || die "cannot read $1 from $RPC. Run this script again."
  read -r HAVE AUTHORITY <<< "$state"
}

cleanup() {
  if [ -n "$VALIDATOR" ] && [ "$KEEP" = 0 ]; then kill "$VALIDATOR" 2>/dev/null || true; wait "$VALIDATOR" 2>/dev/null || true; fi
  if [ -n "$WORK" ] && [ "$KEEP" = 0 ]; then rm -rf "$WORK"; fi
}
trap cleanup EXIT

# ---- a local validator for the dry run ------------------------------------------------------------------------------
start_localnet() {
  need solana-test-validator "It comes with the Solana command line tools."
  local port="${KNOS_LOCAL_PORT:-8899}" from="${KNOS_CLONE_FROM:-https://api.devnet.solana.com}"
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/knos-localnet.XXXXXX")"
  RPC="http://127.0.0.1:$port"
  # the one program this deployment meets on a cluster that it does not deploy: Squads v4, with its config account.
  # Epochs four times the default length: scripts/drill_upgrade.sh moves this validator's clock 48 hours with --warp-slot,
  # and one epoch of the default length carries the clock 36 hours at most
  solana-test-validator --reset --quiet --ledger "$WORK/ledger" --bind-address 127.0.0.1 --rpc-port "$port" --faucet-port "$((port + 2))" \
    --gossip-port "$((port + 3))" --dynamic-port-range "$((port + 4))-$((port + 40))" --slots-per-epoch 1728000 --url "$from" \
    --clone-upgradeable-program "$(pinned squads_program)" --clone BSTq9w3kZwNwpBXJEvTZz2G9ZTNyKBvoSeXMvwb4cNZr > "$WORK/validator.log" 2>&1 &
  VALIDATOR=$!
  for _ in $(seq 90); do
    solana --url "$RPC" cluster-version >/dev/null 2>&1 && break
    kill -0 "$VALIDATOR" 2>/dev/null || { tail -5 "$WORK/validator.log" >&2; die "the local validator did not start (it copies the Squads program from $from: set KNOS_CLONE_FROM to a cluster you can reach)."; }
    sleep 1
  done
  solana --url "$RPC" cluster-version >/dev/null 2>&1 || die "the local validator did not answer on $RPC within 90 seconds."
  echo "local validator on $RPC (ledger $WORK/ledger, the Squads program copied from $from)"
}

localnet_keys() {
  # the dry run uses the real program keypairs and create keys (the addresses are pinned); what only pays or votes
  # may be a throwaway key
  [ -n "$WORK" ] || WORK="$(mktemp -d "${TMPDIR:-/tmp}/knos-localnet.XXXXXX")"
  if [ ! -f "$PAYER" ]; then
    PAYER="$WORK/payer.json"
    solana-keygen new --no-bip39-passphrase --silent --force --outfile "$PAYER" >/dev/null
    echo "no fee payer key file: using a throwaway one for this dry run"
  fi
  if [ -z "${KNOS_MEMBERS:-}" ] && [ ! -f "$KEYS/member-1.json" ]; then
    KNOS_MEMBERS=""
    for n in 1 2 3; do
      solana-keygen new --no-bip39-passphrase --silent --force --outfile "$WORK/member-$n.json" >/dev/null
      KNOS_MEMBERS="$KNOS_MEMBERS $WORK/member-$n.json"
    done
    export KNOS_MEMBERS
    echo "no member key files: using three throwaway members for this dry run"
  fi
  solana --url "$RPC" airdrop 100 "$(solana-keygen pubkey "$PAYER")" >/dev/null || die "the local cluster at $RPC gave the fee payer no SOL."
}

# ---- the steps ------------------------------------------------------------------------------------------------------
multisigs() {
  if governance show --check >/dev/null 2>&1; then echo "  both multisigs exist as the design fixes them"; return; fi
  governance create | sed 's/^/  /'
  governance show --check >/dev/null || die "the multisigs are not right on chain: node scripts/governance.mjs show --rpc $RPC says what is wrong."
}

# sha256 [--check --status] <files>: sha256sum's lines and --check, from shasum -a 256 where there is no sha256sum (macOS)
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

sources_hash() { (cd "$ROOT" && find programs-v2 crates/knos-oidc-interface -type f -not -path '*/target/*' -print0 | LC_ALL=C sort -z | while IFS= read -r -d '' f; do sha256 "$f"; done | sha256 | cut -d' ' -f1); }

# build <names>: the verified build of each (or the files of KNOS_SO_DIR), and its executable hash
build() {
  local name stamp want files=""
  if [ -n "${KNOS_SO_DIR:-}" ]; then
    SO_DIR="$(cd "$KNOS_SO_DIR" && pwd)"
    echo "  not built here: deploying the files of $SO_DIR"
  else
    SO_DIR="$ROOT/programs-v2/target/deploy"
    for name in "$@"; do
      [ "$name" != upgrade_gate ] || die "upgrade_gate is not built here (its verified build is program.yml's: examples/upgrade_gate is its own workspace, built into its own folder). Download program.yml's artifacts and name their folder with KNOS_SO_DIR."
      files="$files $name.so"
    done
    stamp="$SO_DIR/.verified-build"
    [ "$*" = "$PROGRAMS" ] || stamp="$SO_DIR/.verified-build-new"
    [ "$*" != "$UPGRADES" ] || stamp="$SO_DIR/.verified-build-upgrades"
    want="$(sources_hash) $VERIFY_IMAGE"
    if [ -f "$stamp" ] && [ "$(head -1 "$stamp")" = "$want" ] && (cd "$SO_DIR" && tail -n +2 "$stamp" | sha256 --check --status); then
      echo "  programs-v2 is unchanged since the last verified build: not built again"
    else
      need solana-verify "Install it: cargo install --locked solana-verify"
      docker info >/dev/null 2>&1 || die "docker is not running, and the verified build runs in it. Start docker; or deploy files built elsewhere with KNOS_SO_DIR."
      rm -f "${stamp:?}"
      for name in "$@"; do
        # programs/ holds the first deployment's crate of the same name, and solana-verify builds the first manifest
        # `find <mount>` lists, then hashes whatever programs-v2/target/deploy holds. Where programs/ is listed first
        # (NTFS: WSL under /mnt/c, Git Bash) it builds that crate, and a file left here (build_programs_v2.sh's cargo
        # build-sbf) would be stamped as this build. So the file goes first, and the build must make it again.
        rm -f "${SO_DIR:?}/$name.so"
        solana-verify build "$ROOT" --workspace-path "$ROOT/programs-v2" --library-name "$name" --base-image "$VERIFY_IMAGE" || true
        [ -f "$SO_DIR/$name.so" ] || die "solana-verify built no $SO_DIR/$name.so (its output above says why). Its line 'Building manifest path' names the crate it built: if that is programs/$name, the first deployment's crate of the same name, it was listed before programs-v2/$name on this file system. Build from a clone on a Linux file system (on WSL, under ~, not /mnt/c), or deploy program.yml's artifacts with KNOS_SO_DIR. Nothing is stamped."
      done
      # shellcheck disable=SC2086  # files is a list of names
      { echo "$want"; (cd "$SO_DIR" && sha256 $files); } > "$stamp"
    fi
  fi
  for name in "$@"; do
    [ -f "$SO_DIR/$name.so" ] || die "$SO_DIR/$name.so is missing."
    echo "  $name: executable hash $(py hash "$SO_DIR/$name.so")"
  done
}

# stops unless the fee payer can pay for what a file takes at its peak: a buffer of twice its size (it comes back) and,
# for a first deploy ($3 = 1), the program data of twice its size
afford() {
  local what="$1" so="$2" data="$3" size cost balance
  size="$(wc -c < "$so")"
  cost=$(( $(lamports rent $((2 * size + 37))) + data * $(lamports rent $((2 * size + 45))) + 50000000 ))
  balance="$(lamports balance "$PAYER_ADDRESS")"
  [ "$balance" -ge "$cost" ] || die "the fee payer $PAYER_ADDRESS holds $balance lamports and $what takes about $cost (part of it comes back). Fund it: solana airdrop 2 $PAYER_ADDRESS --url $RPC, or https://faucet.solana.com"
}

# deploy_one <name> <address> <program keypair> <buffer keypair> <file>: the program runs this build afterwards. Skipped
# when it does already; continued, with the same buffer, when an earlier run stopped half way
deploy_one() {
  local name="$1" id="$2" key="$3" buffer="$4" so="$5" want size
  want="$(py hash "$so")"
  program_state "$id"
  if [ "$HAVE" = "$want" ]; then echo "  $name $id: this build is on chain already"; return; fi
  [ -f "$key" ] || die "$key is missing: the program's keypair, whose address is $id."
  [ "$(solana-keygen pubkey "$key")" = "$id" ] || die "$key is the keypair of $(solana-keygen pubkey "$key"), not of $name ($id)."
  if [ "$HAVE" != absent ] && [ "$AUTHORITY" != "$PAYER_ADDRESS" ]; then
    die "$name $id is deployed with another build ($HAVE), and its upgrade authority is $AUTHORITY, not the fee payer. An upgrade now goes through the multisig: bash scripts/deploy_v2.sh --propose (it writes the new build to a buffer, then runs node scripts/governance.mjs upgrade propose $name <buffer address>)"
  fi
  size="$(wc -c < "$so")"
  afford "deploying $name" "$so" 1
  [ -f "$buffer" ] || solana-keygen new --no-bip39-passphrase --silent --outfile "$buffer" >/dev/null
  # shellcheck disable=SC2086  # USE_RPC is one flag or nothing
  if ! sol_again program deploy "$so" --program-id "$key" --buffer "$buffer" --upgrade-authority "$PAYER" --fee-payer "$PAYER" \
    --max-len $((2 * size)) --max-sign-attempts 60 --with-compute-unit-price "$PRICE" $USE_RPC 2>&1 | sed 's/^/  /'; then
    die "deploying $name did not finish. Run this script again: the same buffer ($buffer) continues the deploy where it stopped."
  fi
  program_state "$id"
  [ "$HAVE" = "$want" ] || die "$name was deployed but the chain shows $HAVE, not this build ($want). Run this script again."
  echo "  $name $id: deployed, executable hash $HAVE"
}

deploy() {
  local name
  for name in $PROGRAMS; do
    deploy_one "$name" "$(pinned "$name")" "$KEYS/${name}_v2-keypair.json" "$KEYS/${name}_v2-buffer.json" "$SO_DIR/$name.so"
  done
}

# the keypair file of a new program: <name>-keypair.json in the key folder (the gate's is also looked for under the name
# it was made with)
new_key() {
  local name="$1" file
  for file in "$KEYS/$name-keypair.json" "$KEYS/${name/upgrade_gate/knos_gate}-keypair.json"; do
    if [ -f "$file" ]; then echo "$file"; return; fi
  done
  echo "$KEYS/$name-keypair.json"
}

deploy_new() {
  local name
  for name in $NEW_PROGRAMS; do
    deploy_one "$name" "$(py id "$name")" "$(new_key "$name")" "$KEYS/$name-buffer.json" "$SO_DIR/$name.so"
  done
}

# handover <names>: each program's upgrade authority is the upgrade vault afterwards
handover() {
  local name id vault
  vault="$(pinned upgrade_authority)"
  governance show --check >/dev/null || die "the multisigs are not right on chain (node scripts/governance.mjs show --rpc $RPC says what is wrong): the upgrade authority was NOT handed over."
  for name in "$@"; do
    id="$(py id "$name")"
    program_state "$name"
    if [ "$AUTHORITY" = "$vault" ]; then echo "  $name: its upgrade authority is the upgrade vault already"; continue; fi
    [ "$AUTHORITY" = "$PAYER_ADDRESS" ] || die "$name's upgrade authority is $AUTHORITY: neither the fee payer nor the upgrade vault. Nothing was changed."
    # not sent again by itself: a second try after a lost answer would fail because the first one worked. The chain is asked instead.
    sol program set-upgrade-authority "$id" --new-upgrade-authority "$vault" --skip-new-upgrade-authority-signer-check --upgrade-authority "$PAYER" 2>&1 | sed 's/^/  /' || true
    program_state "$name"
    [ "$AUTHORITY" = "$vault" ] || die "$name's upgrade authority is still $AUTHORITY. Run this script again."
    echo "  $name: upgrade authority handed to the upgrade vault $vault"
  done
}

# ---- --rc: a staging copy of the 2.1 builds --------------------------------------------------------------------------
rc_deploy() {
  local name from="${KNOS_RC_SO_DIR:-$SO_DIR}" trusts
  mkdir -p "$RC"; chmod 700 "$RC"
  for name in $PROGRAMS; do
    [ -f "$from/$name.so" ] || die "$from/$name.so is missing."
    [ -f "$RC/$name-keypair.json" ] || solana-keygen new --no-bip39-passphrase --silent --outfile "$RC/$name-keypair.json" >/dev/null
    deploy_one "$name (staging)" "$(solana-keygen pubkey "$RC/$name-keypair.json")" "$RC/$name-keypair.json" "$RC/$name-buffer.json" "$from/$name.so"
  done
  py rc-ids "$(solana-keygen pubkey "$RC/knos_oidc-keypair.json")" "$(solana-keygen pubkey "$RC/knos_pay-keypair.json")" "$RC/program_ids.json"
  # the set-up of a deployment, on the staging programs: the same steps, told where they are by the ids file
  echo "  the faucet's test-USDC mint, GitHub's four genesis keys and the fee owner's token account, on the staging programs:"
  KNOS_PROGRAM_IDS="$RC/program_ids.json" py faucet
  KNOS_PROGRAM_IDS="$RC/program_ids.json" py keys
  KNOS_PROGRAM_IDS="$RC/program_ids.json" py fee-account
  trusts="$(sed -n 's/^pub const OIDC_ID: Pubkey = pubkey!("\(.*\)");.*/\1/p' "$ROOT/programs-v2/knos_pay/src/lib.rs" | head -1)"
  echo
  program_state "$(solana-keygen pubkey "$RC/knos_pay-keypair.json")"       # who holds it, as the chain says: an earlier run may have had another payer
  echo "STAGING: knos_oidc $(solana-keygen pubkey "$RC/knos_oidc-keypair.json") and knos_pay $(solana-keygen pubkey "$RC/knos_pay-keypair.json"), upgrade authority $AUTHORITY$([ "$AUTHORITY" = "$PAYER_ADDRESS" ] && echo " (the fee payer)" || echo " (NOT this run's fee payer $PAYER_ADDRESS: only that key can close them)")."
  if [ -z "${KNOS_RC_SO_DIR:-}" ] && [ -n "$trusts" ]; then
    echo "NOTE: this build of knos_pay accepts tokens verified by knos_oidc $trusts (OIDC_ID in its source), NOT by the staging verifier."
    echo "      What needs no token (Version, FundOrderWallet, SetBalanceX, SetPlan, TopUp, Cancel by the funder, RefundOrder, Assign) and the"
    echo "      staging verifier's own instructions run as they are; a token path of the staging escrow runs against the verifier at"
    echo "      $trusts as it is deployed now. To stage those too, build knos_pay with OIDC_ID set to the staging verifier and name the"
    echo "      folder with KNOS_RC_SO_DIR."
  fi
  echo "Use it:    export KNOS_PROGRAM_IDS=$RC/program_ids.json     (the Python client, deploy_v2.py and knos-settle/agent read it)"
  echo "Close it:  bash scripts/deploy_v2.sh --rc-close             (the SOL returns to the fee payer)"
}

rc_close() {
  local name id file before after closed=0
  if [ ! -d "$RC" ]; then echo "  there is no staging deployment in $RC: nothing to close"; return; fi
  before="$(lamports balance "$PAYER_ADDRESS")"
  for name in $PROGRAMS; do
    file="$RC/$name-keypair.json"
    [ -f "$file" ] || continue
    id="$(solana-keygen pubkey "$file")"
    case " $(pinned knos_oidc) $(pinned knos_pay) $(py id knos_meter) $(py id knos_passkey) $(py id upgrade_gate) " in
      *" $id "*) die "$file is the keypair of a PINNED program ($id), not of a staging one. Nothing was closed." ;;
    esac
    program_state "$id"
    if [ "$HAVE" = absent ]; then
      echo "  $name (staging) $id: not on chain (closed already, or never deployed)"
    else
      [ "$AUTHORITY" = "$PAYER_ADDRESS" ] || die "$name (staging) $id has the upgrade authority $AUTHORITY, not the fee payer: this script cannot close it."
      # not sent again by itself: a second try after a lost answer would fail because the first one worked. The chain is asked instead.
      sol program close "$id" --authority "$PAYER" --recipient "$PAYER_ADDRESS" --bypass-warning 2>&1 | sed 's/^/  /' || true
      program_state "$id"
      [ "$HAVE" = absent ] || die "$name (staging) $id is still on chain. Run this script again."
      echo "  $name (staging) $id: closed"; closed=$((closed + 1))
    fi
    # a buffer a deploy left half written holds SOL too
    if [ -f "$RC/$name-buffer.json" ] && [ "$(py buffer "$(solana-keygen pubkey "$RC/$name-buffer.json")")" != absent ]; then
      sol program close "$(solana-keygen pubkey "$RC/$name-buffer.json")" --authority "$PAYER" --recipient "$PAYER_ADDRESS" --bypass-warning 2>&1 | sed 's/^/  /' || true
    fi
  done
  after="$(lamports balance "$PAYER_ADDRESS")"
  # a closed program id can never be deployed to again: the folder is set aside, so the next --rc makes new ids
  mv "$RC" "$RC.closed.$(date -u +%Y%m%dT%H%M%SZ)"
  echo "  closed $closed staging program(s); the fee payer holds $after lamports, $((after - before)) more than before."
  echo "  The staging ids file went with them: unset KNOS_PROGRAM_IDS."
}

# ---- --propose: the upgrade of the four programs, through the multisig -----------------------------------------------
# withdraw_older: no proposal that can still run would deploy another build of one of the four than this one afterwards.
# Without --replace such a proposal stops the run (deploy_v2.py stale says which and how); with it each is withdrawn by the
# member keys' votes first: an approved one is cancelled, inside its 48 hours too, one still collecting approvals is rejected
withdraw_older() {
  local name builds="" found rc=0 index program hash status left flag=""
  [ "$REPLACE" != 1 ] || flag="--replace"
  for name in $UPGRADES; do builds="$builds $name=$(py hash "$SO_DIR/$name.so")"; done
  # shellcheck disable=SC2086  # builds is a list of name=hash, flag one flag or nothing
  found="$(py $flag stale $builds)" || rc=$?
  [ "$rc" != 5 ] || exit 1                                   # the refusal was printed: what would run, and --replace
  [ "$rc" = 0 ] || die "the upgrade multisig's proposals could not be read from $RPC. Nothing was withdrawn and nothing proposed. Run this script again."
  if [ -z "$found" ]; then echo "  no older proposal that can still run would deploy another build of these programs"; return; fi
  while read -r index program hash status; do
    echo "  REPLACING proposal $index: $program, build $hash ($status). It is withdrawn by the members' votes and can never be executed afterwards:"
    governance cancel upgrade "$index" | sed 's/^/  /' || die "proposal $index ($program, build $hash) was NOT withdrawn (the lines above say why): it can still be executed. Nothing was proposed. Run this again with the member keys it needs."
  done <<< "$found"
  # the chain is asked again: only what it shows as withdrawn counts
  # shellcheck disable=SC2086
  left="$(py --replace stale $builds)" || die "the upgrade multisig's proposals could not be read again from $RPC. Run this script again."
  [ -z "$left" ] || die "still not withdrawn: $(echo "$left" | awk '{ printf "%sproposal %s (%s, build %s)", sep, $1, $2, $3; sep = ", " }'). Nothing was proposed. Run this again with the member keys it needs (KNOS_MEMBERS)."
  # the schedule of the withdrawn proposals names nothing that may run now
  if [ -f "$SCHEDULE" ]; then mv "$SCHEDULE" "$SCHEDULE.withdrawn"; echo "  the schedule of the withdrawn proposals was set aside ($SCHEDULE.withdrawn)"; fi
  if [ -f "$KEYS/upgrade-run.timer" ]; then
    echo "  NOTE: a timer for the withdrawn proposals is still arranged ($(cat "$KEYS/upgrade-run.timer")). It can execute none of them: take it back with"
    echo "        bash scripts/schedule_upgrade.sh --cancel     (arranging the new run, after this, replaces it too)"
  fi
}

# plan: PLAN is the programs this run will propose, in the order of UPGRADES: those whose build in SO_DIR is not the one
# the chain runs. It only reads. A program this release does not change (it is not in CHANGES) must run the build in
# SO_DIR already; when it does not, nothing may be proposed at all, and the run stops here saying the three things that
# can be true. So a rebuild of an unchanged program is never proposed because its bytes moved with a version string.
plan() {
  local name id want held_at
  PLAN=""
  held_at="$(sed -n 's/^FROZEN_AT = "\(.*\)"$/\1/p' "$ROOT/scripts/bump_version.py")"
  for name in $UPGRADES; do
    id="$(pinned "$name")"
    want="$(py hash "$SO_DIR/$name.so")"
    program_state "$name"
    [ "$HAVE" != absent ] || die "$name $id is not deployed on this cluster: there is nothing to upgrade. The plain run deploys it."
    [ "$HAVE" != "$want" ] || continue
    case " $CHANGES " in
      *" $name "*) PLAN="$PLAN $name" ;;
      *) die "$name is not a program this release changes (it changes: $CHANGES), and the build in $SO_DIR ($want) is not the one $name $id runs ($HAVE). Nothing was withdrawn, written or proposed. One of three things is true. (1) The proposals made before this release have not all executed: knos status says which program still runs its older build. Wait for them, then run this again. (2) This file is a rebuild from the release's tree, and its bytes moved though no line of $name did: a crate's version is in a build's bytes, and knos_pay links knos_oidc (programs-v2/knos_pay/Cargo.toml), so a change to what it reads from there changes knos_pay's build too. The chain runs the verified build of the v$held_at tag (program.yml's run on that tag): put that run's $name.so in KNOS_SO_DIR in place of this one, and say in the release's notes that $name is verified at v$held_at. (3) The release does change $name: say so with KNOS_CHANGES=\"$CHANGES $name\", and it is proposed with the others." ;;
    esac
  done
  PLAN="${PLAN# }"
  echo "  the plan: propose ${PLAN:-nothing} (this release changes: $CHANGES)"
}

propose() {
  local name id so want buffer address state held vault outs="" flag rc wait="$GATE_WAIT" kept size have
  vault="$(pinned upgrade_authority)"
  governance show --check >/dev/null || die "the multisigs are not right on chain (node scripts/governance.mjs show --rpc $RPC says what is wrong). Nothing was proposed."
  if [ "$UNGATED" = 1 ]; then
    echo "  UNGATED: --ungated WAS PASSED. THIS IS FOR AN EMERGENCY ONLY: a build that no record at the upgrade gate vouches for will be"
    echo "  UNGATED: proposed without waiting for one. Without the flag this script waits for program.yml's record and refuses a build that has none."
    wait=0
  fi
  plan
  withdraw_older
  for name in $UPGRADES; do
    id="$(pinned "$name")" so="$SO_DIR/$name.so"
    want="$(py hash "$so")"
    # a buffer of its own for each program and each build: a buffer that an earlier proposal handed to the vault holds that
    # proposal's build for good, and this script could never write to it again
    buffer="$KEYS/$name-upgrade-buffer-${want:0:16}.json"
    program_state "$name"
    [ "$HAVE" != absent ] || die "$name $id is not deployed on this cluster: there is nothing to upgrade. The plain run deploys it."
    if [ "$HAVE" = "$want" ]; then echo "  $name $id: runs this build already ($want): nothing to propose"; continue; fi
    [ "$AUTHORITY" = "$vault" ] || die "$name's upgrade authority is $AUTHORITY, not the upgrade vault $vault: the multisig could not execute an upgrade. Nothing was proposed."
    # this build's own proposal from an earlier run (whatever buffer file that run had): proposed with ITS buffer, so
    # governance.mjs continues that proposal and there are never two for one build
    kept="$(py kept "$name=$want")" || die "the upgrade multisig's proposals could not be read from $RPC. Run this script again."
    if [ -n "$kept" ]; then
      address="$kept"; echo "  $name: a proposal that can still run carries this build already (buffer $address): continuing with it"
    else
      [ -f "$buffer" ] || solana-keygen new --no-bip39-passphrase --silent --outfile "$buffer" >/dev/null
      address="$(solana-keygen pubkey "$buffer")"
    fi
    state="$(py buffer "$address")"; held="${state#* }"
    if [ "${state%% *}" = "$want" ]; then
      echo "  $name: the buffer $address holds this build already"
    else
      [ "$state" = absent ] || [ "$held" = "$PAYER_ADDRESS" ] || die "the buffer $address holds another build and its authority is $held: this script cannot write to it. Move $buffer away and run again: a new buffer is made."
      afford "the buffer of $name" "$so" 0
      # shellcheck disable=SC2086  # USE_RPC is one flag or nothing
      if ! sol_again program write-buffer "$so" --buffer "$buffer" --buffer-authority "$PAYER" --fee-payer "$PAYER" \
        --max-sign-attempts 60 --with-compute-unit-price "$PRICE" $USE_RPC 2>&1 | sed 's/^/  /'; then
        die "writing the buffer of $name did not finish. Run this script again: the same buffer ($buffer) continues where it stopped."
      fi
      state="$(py buffer "$address")"; held="${state#* }"
      [ "${state%% *}" = "$want" ] || die "the buffer $address was written but the chain shows ${state%% *}, not this build ($want). Run this script again."
      echo "  $name: the build $want is in the buffer $address"
    fi
    # the gate: GitHub's signed statement that its runner built exactly these bytes. program.yml's gate job asks for it
    # after the verified builds and a relayer carries it, so the record may still be on its way: it is waited for
    flag=""; rc=0
    if [ -n "${KNOS_GATE_TOKENS:-}" ] && [ -f "$KNOS_GATE_TOKENS/$name.jwt" ]; then py --wait "$wait" gate "$name" "$so" "$KNOS_GATE_TOKENS/$name.jwt" || rc=$?; else py --wait "$wait" gate "$name" "$so" || rc=$?; fi
    if [ "$rc" != 0 ]; then
      if [ "$UNGATED" != 1 ]; then
        [ "$rc" != 3 ] || die "the upgrade gate is not deployed on this cluster, so no record vouches for this build. Deploy it first (bash scripts/deploy_v2.sh --new) and run this again. The buffer is written and stays. (In an emergency only: --propose --ungated.)"
        die "the upgrade gate holds no record of this build of $name after $wait seconds. program.yml records the builds it makes on main and on a release tag: push the commit this build is of, let its gate job finish, and run this again (or put its token in KNOS_GATE_TOKENS/$name.jwt). If the hash above is not the one that run printed, this file is not the build GitHub made: take the run's artifacts (KNOS_SO_DIR). The buffer is written and stays. (In an emergency only: --propose --ungated.)"
      fi
      echo "  UNGATED: NO RECORD AT THE UPGRADE GATE VOUCHES FOR THIS BUILD OF $name. It is proposed because --ungated was passed:"
      echo "  UNGATED: the members have only their own rebuild to compare $want with (from the root of a clone: solana-verify build \"\$PWD\" --workspace-path \"\$PWD/programs-v2\" --library-name $name --base-image $VERIFY_IMAGE)."
      flag="--ungated"
    fi
    # the loader refuses an Upgrade to a build larger than the program's data account has room for (a deploy leaves
    # room for twice the first build). Extended here, before the buffer is the vault's: ExtendProgram changes no code,
    # and anyone may send it while the cluster has not activated ExtendProgramChecked
    size="$(wc -c < "$so" | tr -d ' ')"; have="$(py room "$name")"
    if [ "$size" -gt "$have" ]; then
      echo "  $name: this build is $size bytes and the program's data account has room for $have. It is extended by $((size - have)) bytes first (the fee payer pays their rent; no code changes):"
      py extend "$name" $((size - have)) || die "$name's data account could not be extended, so this build ($size bytes) cannot be upgraded to (room: $have). Where the cluster has activated ExtendProgramChecked only the upgrade authority can extend a program, and that is the upgrade vault: the extension then has to be a proposal of the multisig, executed before this upgrade, which this script does not make. Nothing was proposed for $name; its buffer is written and stays with the fee payer."
      have="$(py room "$name")"
      [ "$size" -le "$have" ] || die "$name's data account still has room for $have bytes only, and this build is $size. Run this script again."
    fi
    if [ "$held" != "$vault" ]; then
      [ "$held" = "$PAYER_ADDRESS" ] || die "the buffer $address has the authority $held: neither the fee payer nor the upgrade vault."
      # not sent again by itself: the chain is asked instead
      sol program set-buffer-authority "$address" --new-buffer-authority "$vault" --buffer-authority "$PAYER" 2>&1 | sed 's/^/  /' || true
      state="$(py buffer "$address")"
      [ "${state#* }" = "$vault" ] || die "the buffer's authority is still ${state#* }. Run this script again."
      echo "  $name: the buffer is the upgrade vault's now"
    fi
    : > "${KEYS:?}/${name:?}-upgrade.json.new"
    # shellcheck disable=SC2086  # flag is one flag or nothing
    governance upgrade propose "$name" "$address" --out "$KEYS/$name-upgrade.json.new" $flag | sed 's/^/  /'
    # only what this run's proposal wrote counts: an earlier run's file is never read as this one's
    [ -s "$KEYS/$name-upgrade.json.new" ] || die "the proposal for $name was not made (the lines above say why). Run this script again."
    mv "$KEYS/$name-upgrade.json.new" "$KEYS/$name-upgrade.json"
    outs="$outs $KEYS/$name-upgrade.json"
  done
  echo
  if [ -z "$outs" ]; then echo "on chain now: all four programs run these builds already. Nothing is proposed and nothing is scheduled."; return; fi
  # shellcheck disable=SC2086  # outs is a list of files
  py schedule "$SCHEDULE" $outs
  echo "Next: bash scripts/schedule_upgrade.sh     (at that time it executes the proposals, then runs knos status; it says how to cancel)"
  echo "Until then anyone can read the proposals on chain, and the members can cancel one: node scripts/governance.mjs cancel upgrade <index>"
}

# ---- run ------------------------------------------------------------------------------------------------------------
need solana "Install the Solana command line tools (agave 2.3 or later)."
need solana-keygen "It comes with the Solana command line tools."
need node "Install Node 20 or later."
node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' || die "node is older than 20 ($(node --version)): governance.mjs needs Node 20 or later."
[ -d "$ROOT/scripts/node_modules/@sqds/multisig" ] || die "the scripts' packages are not installed. Run: npm ci --prefix scripts"
PYTHONPATH="$ROOT/src" "$PYTHON" -c 'import solders' 2>/dev/null || die "$PYTHON cannot import solders. Run: pip install -e .   (or set PYTHON to the Python that has it)"

USE_RPC=""
if [ "${KNOS_USE_RPC:-0}" = 1 ]; then USE_RPC="--use-rpc"; fi
if [ "$LOCALNET" = 1 ] && [ -z "${KNOS_RPC:-}" ]; then start_localnet; fi
# an endpoint on this machine (a validator, a Surfpool fork) has no TPU to send to: the deploy goes through the RPC
case "$RPC" in http://127.0.0.1:*|http://localhost:*|http://\[::1\]:*) USE_RPC="--use-rpc" ;; esac
CLUSTER="$(py cluster)" || die "cannot reach the cluster at $RPC. Set KNOS_RPC to an endpoint that answers."
# a validator on this machine is local whatever it says it is: a Surfpool fork answers with the genesis of the cluster it copies
case "$RPC" in http://127.0.0.1:*|http://localhost:*|http://\[::1\]:*) CLUSTER="local ($CLUSTER)" ;; esac
if [ "$LOCALNET" = 1 ]; then
  case "$CLUSTER" in local*) ;; *) die "--localnet was asked, and $RPC is $CLUSTER, not a validator on this machine. Unset KNOS_RPC, or point it at one." ;; esac
  localnet_keys
elif [ "$CLUSTER" = mainnet-beta ]; then
  die "$RPC is mainnet-beta. This is the devnet deployment: a mainnet deployment needs program ids of its own and an outside review first (knos mainnet-check)."
fi
[ -z "${KNOS_PROGRAM_IDS:-}" ] || die "KNOS_PROGRAM_IDS is set ($KNOS_PROGRAM_IDS). This script works on the pinned programs and names the staging ones itself: unset it and run again."
[ -f "$PAYER" ] || die "the fee payer's keypair $PAYER is missing. Set KNOS_FEE_PAYER, or put payer.json in the key folder $KEYS."
PAYER_ADDRESS="$(solana-keygen pubkey "$PAYER")"
echo "cluster $CLUSTER ($RPC); fee payer $PAYER_ADDRESS; key folder $KEYS"

# shellcheck disable=SC2086  # the lists of names are split on purpose
case "$MODE" in
  --new)
    part "new 1/3" "the verified build of the new programs"; build $NEW_PROGRAMS
    part "new 2/3" "deploy knos_meter, knos_passkey and upgrade_gate at their pinned ids"; deploy_new
    part "new 3/3" "their upgrade authority goes to the upgrade vault"; handover $NEW_PROGRAMS
    echo; py summary-new; exit $? ;;
  --rc)
    part "rc 1/2" "the builds to stage"; build $PROGRAMS
    part "rc 2/2" "deploy them under staging ids, and set the staging deployment up"; rc_deploy
    exit 0 ;;
  --rc-close)
    part "rc-close" "close the staging programs"; rc_close
    exit 0 ;;
  --propose)
    part "propose 1/2" "the verified builds of knos_oidc, knos_pay, knos_meter and knos_passkey"; build $UPGRADES
    part "propose 2/2" "older proposals, buffers, the upgrade gate, the proposals"; propose
    exit 0 ;;
esac

# shellcheck disable=SC2086
step 1 "the two multisigs"; multisigs
# shellcheck disable=SC2086
step 2 "the verified build"; build $PROGRAMS
step 3 "deploy"; deploy
step 4 "the faucet's test-USDC mint"; py faucet
step 5 "GitHub's four genesis keys"; py keys
step 6 "the fee owner's token account"; py fee-account
# shellcheck disable=SC2086
step 7 "the upgrade authority goes to the upgrade vault"; handover $PROGRAMS

echo
echo "addresses"
py addresses
echo
echo "transactions on chain that touch them, oldest first"
py transactions "$CLUSTER"
echo
if [ -n "$VALIDATOR" ] && [ "$KEEP" = 1 ]; then echo "the local validator is still running on $RPC (pid $VALIDATOR, ledger $WORK/ledger): stop it with kill $VALIDATOR"; fi
py summary
