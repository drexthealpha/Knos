#!/bin/bash
# Fuzz the claim parser (programs-v2/knos_oidc/fuzz) for a fixed time and say how many inputs it tried.
#
#   bash scripts/fuzz_nightly.sh [SECONDS]      run from the root of the repository; SECONDS defaults to 300
#
# What it does: finds the fuzz targets of knos_oidc (`cargo fuzz list`), runs each for an equal share of SECONDS with
# libFuzzer (cargo-fuzz needs a nightly toolchain: FUZZ_TOOLCHAIN names it, `nightly` when it is not set), adds up the
# executions libFuzzer reports at the end of each (`stat::number_of_executed_units`), and writes the total twice: to
# the job summary ($GITHUB_STEP_SUMMARY, or the screen), and to fuzz.json, which program.yml uploads as an artifact:
#
#     {"target": "<name>", "executions": <the count>, "seconds": 300, "commit": "<sha>", "run": "<url of the run>",
#      "date": "<UTC, to the second>", "crashed": false, "source": "<one sentence on where the number comes from>"}
#
# `executions` and `source` are what `scripts/bench_docs.py --set NAME=NUMBER --source TEXT` takes for a number that
# only a run can measure. When the fuzzer finds an input that crashes the parser it says so in the summary, keeps the
# input in programs-v2/knos_oidc/fuzz/artifacts (program.yml uploads that folder), and this script exits 1 (the file is
# written, with "crashed": true). A run that does not finish for another reason (it does not build, no memory left)
# exits 1 and writes no file: a count of a run that stopped early would not be a measurement.
# When there is no fuzz target (the directory is not there, or holds none) it says so and exits 0 with no file.
set -euo pipefail

seconds="${1:-300}"
case "$seconds" in ''|*[!0-9]*|0) echo "The time to fuzz is a whole number of seconds, such as 300."; exit 2;; esac
crate="${FUZZ_CRATE:-programs-v2/knos_oidc}"      # FUZZ_CRATE is for trying this script on another crate
toolchain="${FUZZ_TOOLCHAIN:-nightly}"
out="${FUZZ_JSON:-fuzz.json}"
summary="${GITHUB_STEP_SUMMARY:-/dev/stdout}"

if [ ! -f "$crate/fuzz/Cargo.toml" ] || [ -z "$(find "$crate/fuzz/fuzz_targets" -name '*.rs' 2>/dev/null | head -1)" ]; then
  echo "There is no fuzz target in $crate/fuzz yet, so nothing was fuzzed. It is added with \`cargo fuzz init\` in $crate." | tee -a "$summary"
  exit 0
fi

targets=$(cd "$crate" && cargo "+$toolchain" fuzz list)
[ -n "$targets" ] || { echo "cargo fuzz lists no target in $crate/fuzz, so nothing was fuzzed." | tee -a "$summary"; exit 0; }
count=$(printf '%s\n' "$targets" | wc -l | tr -d ' ')
share=$(( seconds / count ))
[ "$share" -ge 1 ] || share=1

total=0
crashed=false
failed=false
log=$(mktemp)
for target in $targets; do
  echo "== fuzzing $target for $share seconds"
  code=0
  (cd "$crate" && cargo "+$toolchain" fuzz run "$target" -- "-max_total_time=$share" -print_final_stats=1 -rss_limit_mb=2048) > "$log" 2>&1 || code=$?
  cat "$log"
  ran=$(sed -n 's/^stat::number_of_executed_units: *\([0-9][0-9]*\).*/\1/p' "$log" | tail -1)
  total=$(( total + ${ran:-0} ))
  # libFuzzer names the file it keeps an input in when it finds one that crashes. Any other failure (it did not build,
  # it ran out of memory) is not a finding about the parser, and no count is written for a run that did not finish.
  if grep -q '^Test unit written to' "$log"; then crashed=true
  elif [ "$code" -ne 0 ]; then failed=true; fi
done
rm -f "$log"

if [ "$failed" = true ]; then
  echo "The fuzzer did not finish: the log above says why. No count was written." | tee -a "$summary"
  exit 1
fi

commit="${GITHUB_SHA:-unknown}"
if [ -n "${GITHUB_RUN_ID:-}" ]; then run="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/$GITHUB_RUN_ID"; else run="a run by hand, not a workflow run"; fi
names=$(printf '%s\n' "$targets" | paste -sd, -)
source="libFuzzer through cargo-fuzz on the claim parser (target $names), $seconds seconds, commit ${commit:0:7}, $run"
printf '{"target": "%s", "executions": %s, "seconds": %s, "commit": "%s", "run": "%s", "date": "%s", "crashed": %s, "source": "%s"}\n' \
  "$names" "$total" "$seconds" "$commit" "$run" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$crashed" "$source" > "$out"

{
  echo "### Claim parser fuzz"
  echo
  echo "| target | seconds | executions | crash |"
  echo "|---|---|---|---|"
  echo "| $names | $seconds | $total | $([ "$crashed" = true ] && echo "yes: the input is in the artifact" || echo none) |"
  echo
  echo "Counted from libFuzzer's final statistics. The same numbers are in the artifact \`$(basename "$out")\`."
} >> "$summary"

if [ "$crashed" = true ]; then
  echo "The fuzzer found an input that makes the claim parser fail. It is in $crate/fuzz/artifacts." | tee -a "$summary"
  exit 1
fi
