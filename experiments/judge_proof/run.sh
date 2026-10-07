#!/usr/bin/env bash
# Build the judge's guest, prove one run of it, verify the proof, and print what was measured.
#
#   R0VM=/path/to/r0vm ./run.sh [fixtures/honest.txt] [succinct|composite|groth16]
#
# Needs: a nightly Rust with the rust-src component (the guest's target, riscv32im-risc0-zkvm-elf, is in upstream
# Rust and its standard library is built here from source), a stable Rust for the host, and the r0vm binary of
# RISC Zero 3.0.6 (the file cargo-risczero-x86_64-unknown-linux-gnu.tgz of that release holds it).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
submission="${1:-$here/fixtures/honest.txt}"
kind="${2:-succinct}"
out="${OUT:-$here/out}"
: "${R0VM:?set R0VM to the r0vm binary of RISC Zero 3.0.6}"
mkdir -p "$out"

flags=(-C passes=lower-atomic -C link-arg=-Ttext=0x00200800 -C link-arg=--fatal-warnings -C panic=abort
       --cfg 'getrandom_backend="custom"')
encoded="$(IFS=$'\x1f'; echo "${flags[*]}")"
(cd "$here/guest" && CARGO_TARGET_DIR="${GUEST_TARGET:-$out/target-guest}" CARGO_ENCODED_RUSTFLAGS="$encoded" \
  cargo +nightly build --release --locked --target riscv32im-risc0-zkvm-elf \
  -Zbuild-std=alloc,core,proc_macro,panic_abort,std -Zbuild-std-features=compiler-builtins-mem)
(cd "$here/host" && CARGO_TARGET_DIR="${HOST_TARGET:-$out/target-host}" cargo build --release --locked)
host="${HOST_TARGET:-$out/target-host}/release/judge-host"
elf="${GUEST_TARGET:-$out/target-guest}/riscv32im-risc0-zkvm-elf/release/judge-guest"

"$host" image "$elf" "$out/judge.bin" | tee "$out/image.txt"
image="$(awk '/^image_id/{print $2}' "$out/image.txt")"
"$host" plain "$here/checks.txt" "$submission" | tee "$out/plain.txt"
# RISC0_DEV_MODE must be off: with it on the receipt is a placeholder and proves nothing
RISC0_DEV_MODE=0 RISC0_SERVER_PATH="$R0VM" "${PYTHON:-python3}" "$here/measure.py" "$out/prove.json" \
  "$host" prove "$out/judge.bin" "$submission" "$out/receipt.bin" "$kind" | tee "$out/prove.txt"
RISC0_DEV_MODE=0 "${PYTHON:-python3}" "$here/measure.py" "$out/verify.json" \
  "$host" verify "$out/receipt.bin" "$image" | tee "$out/verify.txt"
cat "$out/prove.json" "$out/verify.json"
[ "$(grep '^journal' "$out/plain.txt")" = "$(grep '^journal' "$out/verify.txt")" ] && echo "same journal as the plain run"
