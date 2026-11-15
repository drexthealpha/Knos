#!/usr/bin/env bash
# Build the four programs of programs-v2 for one sBPF version, the same way every time, and record what was built.
#
#   bash scripts/build_sbf.sh [v3|v2|v1|v0] [deploy|test|both]        # default: v3 deploy
#
#   deploy  the builds a cluster runs (no test features): knos_oidc, knos_pay (devnet default features), knos_meter,
#           knos_passkey  -> programs-v2/target/arch-<v>/deploy/<name>.so
#   test    the testkeys builds the tests load (never deployed) -> tests/fixtures/platform/<name>_<v>_test.so
#
# Pinned toolchain (the script refuses another, so two people get the same bytes): cargo-build-sbf 4.4.0 (Agave
# 4.4.0-beta.0, the release devnet runs) with platform-tools v1.57. An sBPF v3 file from cargo-build-sbf 2.3.13 and
# platform-tools v1.48 does NOT load in Agave 4.4 ("invalid file header": the v3 format changed), so v3 needs these.
# CARGO_BUILD_SBF names the binary when it is not the one on PATH. Also pinned: the lockfile as committed (--locked), overflow checks on (programs-v2/Cargo.toml). The ELF's
# e_flags is the sBPF version (0 = v0 ... 3 = v3); the script checks it.
#
# It writes programs-v2/target/arch-<v>/HASHES-<v>.txt (not committed): for each program the sha256 of the file and the hash
# `solana-verify get-executable-hash` prints (sha256 of the file without its trailing zero bytes: what
# `solana-verify get-program-hash` prints for a deployed program). The verified (docker) build is the same command
# inside solana-verify's image, which needs docker (docs/reference/PLATFORM.md says which command and image):
#   solana-verify build "$PWD" --workspace-path "$PWD/programs-v2" --library-name <name> --arch v3 \
#       --base-image <a 4.4 toolchain image; program.yml does not use one yet (docs/reference/PLATFORM.md, section 8)>
#
# CARGO_TARGET_DIR is set per version, so the builds of two versions never overwrite each other. Heavy: run it under
# flock ~/knos/HEAVY.lock on a shared machine.
set -euo pipefail
cd "$(dirname "$0")/.."
arch="${1:-v3}"; what="${2:-deploy}"
case "$arch" in v0|v1|v2|v3) ;; *) echo "usage: bash scripts/build_sbf.sh [v3|v2|v1|v0] [deploy|test|both]" >&2; exit 2 ;; esac
case "$what" in deploy|test|both) ;; *) echo "usage: bash scripts/build_sbf.sh [v3|v2|v1|v0] [deploy|test|both]" >&2; exit 2 ;; esac
sbf="${CARGO_BUILD_SBF:-cargo-build-sbf}"
want_sbf="4.4.0"; want_tools="v1.57"
have="$("$sbf" --version 2>/dev/null | head -1)"
case "$have" in *"$want_sbf"*) ;; *) echo "need cargo-build-sbf $want_sbf, found: ${have:-none}" >&2; exit 3 ;; esac
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR_BASE:-$PWD/programs-v2/target}/arch-$arch"
# A panic message carries the path of the file it is in. Without this, a build in /home/alice and one in /home/bob
# differ in those bytes; with it, both say /build (this checkout) and /cargo (the crates cargo downloaded).
cargo_home="${CARGO_HOME:-$HOME/.cargo}"
export RUSTFLAGS="${RUSTFLAGS:+$RUSTFLAGS }--remap-path-prefix=$PWD=/build --remap-path-prefix=$cargo_home=/cargo"
out="$CARGO_TARGET_DIR"; fix="tests/fixtures/platform"
mkdir -p "$out" "$fix"
version_of() { od -An -tu4 -j48 -N4 "$1" | tr -d ' '; }      # ELF64 e_flags, at byte 48
exe_hash() { python3 - "$1" <<'PY'
import hashlib, sys
d = open(sys.argv[1], "rb").read().rstrip(b"\0")
print(hashlib.sha256(d).hexdigest())
PY
}
build() {   # build <crate> <copy to, or -> [cargo build-sbf arguments]
  local crate="$1" to="$2"; shift 2
  rm -f "$CARGO_TARGET_DIR/deploy/$crate.so"
  (cd "programs-v2/$crate" && "$sbf" --arch "$arch" --tools-version "$want_tools" ${SBF_ARGS:-} -- --locked "$@" 2>&1 | grep -E "^(error|warning: unused)|Finished" || true)
  local so="$CARGO_TARGET_DIR/deploy/$crate.so"
  [ -f "$so" ] || { echo "no $so: the build failed" >&2; exit 4; }
  local v; v="$(version_of "$so")"
  [ "v$v" = "$arch" ] || { echo "$so has e_flags $v, not $arch" >&2; exit 5; }
  if [ "$to" != "-" ]; then cp "$so" "$to"; fi
}
if [ "$what" = test ] || [ "$what" = both ]; then
  build knos_oidc "$fix/knos_oidc_${arch}_test.so" --features testkeys
  build knos_pay "$fix/knos_pay_${arch}_test.so" --features testkeys
  build knos_meter "$fix/knos_meter_${arch}_test.so" --features testkeys
  build knos_passkey "$fix/knos_passkey_${arch}_test.so"
  (cd "$fix" && sha256sum knos_*_"${arch}"_test.so > "SHA256SUMS-$arch")
fi
if [ "$what" = deploy ] || [ "$what" = both ]; then
  hashes="$out/HASHES-$arch.txt"
  {
    echo "# sBPF $arch deploy builds of programs-v2 (scripts/build_sbf.sh $arch deploy)"
    echo "# source: $(git rev-parse HEAD 2>/dev/null || echo unknown)$(git diff --quiet HEAD -- programs-v2 2>/dev/null || echo ' + uncommitted changes in programs-v2')"
    echo "# toolchain: $have, platform-tools $want_tools, rustc $(rustc --version 2>/dev/null | cut -d' ' -f2)"
    echo "# name  e_flags  bytes  sha256(file)  solana-verify executable hash"
  } > "$hashes"
  for crate in knos_oidc knos_pay knos_meter knos_passkey; do
    build "$crate" -
    so="$CARGO_TARGET_DIR/deploy/$crate.so"
    echo "$crate  $(version_of "$so")  $(stat -c %s "$so")  $(sha256sum "$so" | cut -d' ' -f1)  $(exe_hash "$so")" >> "$hashes"
  done
  cat "$hashes"
fi
