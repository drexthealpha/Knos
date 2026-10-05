#!/bin/bash
# Fuzz the verifier's two coverage-guided targets (programs-v2/knos_oidc/fuzz) for a fixed time each and say what came
# of it: how many inputs each tried, how large its corpus is, whether it found a crash.
#
#   bash scripts/fuzz_nightly.sh [SECONDS]      run from the root of the repository; SECONDS is for EACH target, 300 if not given
#
# What it does: finds the fuzz targets of knos_oidc (`cargo fuzz list`: today `claims`, the claim reader against
# serde_json, and `rsa_verify`, the RSA arithmetic against big integers and the `rsa` crate), and runs each for
# SECONDS with libFuzzer (cargo-fuzz needs a nightly toolchain: FUZZ_TOOLCHAIN names it, `nightly` when it is not set).
# A target starts from what earlier runs found (fuzz/corpus/<target>, which the workflow keeps from night to night) and
# from the committed seeds (fuzz/seeds/<target>: forged tokens and Project Wycheproof's vectors). For each target it
# reads the executions libFuzzer reports at the end (`stat::number_of_executed_units`), counts the files in its corpus
# and the crashes it wrote, and says so three times:
#
#   - a line appended to fuzz_targets.jsonl (FUZZ_LINES), one per target and run, never rewritten:
#       {"target": "rsa_verify", "executions": <count>, "corpus": <files>, "crashes": 0, "seconds": 300,
#        "commit": "<sha>", "run": "<url of the run>", "date": "<UTC, to the second>"}
#   - fuzz.json (FUZZ_JSON), written whole: the same objects under "targets", "total_executions", and at the top
#     the fields `scripts/bench_docs.py --set claim_parser_executions=NUMBER --source TEXT` takes, which are the
#     claim parser's own (`executions` and `source` are of the target `claims`; of the first target when there is
#     no `claims`): {"target", "executions", "seconds", "commit", "run", "date", "crashed", "source", ...};
#   - a table in the job summary ($GITHUB_STEP_SUMMARY, or the screen).
# program.yml uploads both files, the corpus and any crash as artifacts. Nothing is committed.
#
# When the fuzzer finds an input that fails a target it says so in the summary, keeps the input in
# programs-v2/knos_oidc/fuzz/artifacts/<target> (program.yml uploads that folder), goes on to the next target, and this
# script exits 1 at the end (the files are written, with "crashed": true). A run that does not finish for another
# reason (it does not build, no memory left) exits 1 and writes no file: a count of a run that stopped early would
# not be a measurement.
# When there is no fuzz target (the directory is not there, or holds none) it says so and exits 0 with no file.
set -euo pipefail

seconds="${1:-300}"
case "$seconds" in ''|*[!0-9]*|0) echo "The time to fuzz is a whole number of seconds, such as 300."; exit 2;; esac
crate="${FUZZ_CRATE:-programs-v2/knos_oidc}"      # FUZZ_CRATE is for trying this script on another crate
toolchain="${FUZZ_TOOLCHAIN:-nightly}"
out="${FUZZ_JSON:-fuzz.json}"
lines="${FUZZ_LINES:-fuzz_targets.jsonl}"
summary="${GITHUB_STEP_SUMMARY:-/dev/stdout}"

if [ ! -f "$crate/fuzz/Cargo.toml" ] || [ -z "$(find "$crate/fuzz/fuzz_targets" -name '*.rs' 2>/dev/null | head -1)" ]; then
  echo "There is no fuzz target in $crate/fuzz yet, so nothing was fuzzed. It is added with \`cargo fuzz init\` in $crate." | tee -a "$summary"
  exit 0
fi

targets=$(cd "$crate" && cargo "+$toolchain" fuzz list)
[ -n "$targets" ] || { echo "cargo fuzz lists no target in $crate/fuzz, so nothing was fuzzed." | tee -a "$summary"; exit 0; }

commit="${GITHUB_SHA:-unknown}"
if [ -n "${GITHUB_RUN_ID:-}" ]; then run="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/$GITHUB_RUN_ID"; else run="a run by hand, not a workflow run"; fi

total=0
crashed=false
failed=false
found=""            # the targets that found a crash
rows=""             # the summary's table
objects=""          # the targets' JSON objects, comma separated
head_target=""      # the target whose count is the claim parser's: `claims`, or the first
head_count=0
log=$(mktemp)
for target in $targets; do
  echo "== fuzzing $target for $seconds seconds"
  mkdir -p "$crate/fuzz/corpus/$target"
  dirs="fuzz/corpus/$target"       # the first folder is where libFuzzer keeps what it finds; the seeds are only read
  [ -d "$crate/fuzz/seeds/$target" ] && dirs="$dirs fuzz/seeds/$target"
  code=0
  # shellcheck disable=SC2086  # two folders, two words
  (cd "$crate" && cargo "+$toolchain" fuzz run "$target" $dirs -- "-max_total_time=$seconds" -print_final_stats=1 -rss_limit_mb=2048) > "$log" 2>&1 || code=$?
  cat "$log"
  ran=$(sed -n 's/^stat::number_of_executed_units: *\([0-9][0-9]*\).*/\1/p' "$log" | tail -1)
  ran=${ran:-0}
  # libFuzzer names the file it keeps an input in when it finds one that fails. Any other failure (it did not build,
  # it ran out of memory) is not a finding about the verifier, and no count is written for a run that did not finish.
  crashes=$(grep -c '^Test unit written to' "$log" || true)
  if [ "$crashes" -gt 0 ]; then crashed=true; found="$found $target"
  elif [ "$code" -ne 0 ]; then failed=true; fi
  corpus=$(find "$crate/fuzz/corpus/$target" -type f | wc -l | tr -d ' ')
  total=$(( total + ran ))
  if [ -z "$head_target" ] || [ "$target" = claims ]; then head_target=$target; head_count=$ran; fi
  object=$(printf '{"target": "%s", "executions": %s, "corpus": %s, "crashes": %s, "seconds": %s, "commit": "%s", "run": "%s", "date": "%s"}' \
    "$target" "$ran" "$corpus" "$crashes" "$seconds" "$commit" "$run" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
  objects="${objects:+$objects, }$object"
  rows="$rows| $target | $seconds | $ran | $corpus | $([ "$crashes" -gt 0 ] && echo "yes: the input is in the artifact" || echo none) |"$'\n'
done
rm -f "$log"

if [ "$failed" = true ]; then
  echo "The fuzzer did not finish: the log above says why. No count was written." | tee -a "$summary"
  exit 1
fi

printf '%s\n' "$objects" | sed 's/}, {/}\n{/g' >> "$lines"
names=$(printf '%s\n' "$targets" | paste -sd, -)
source="libFuzzer through cargo-fuzz on the target $head_target, $seconds seconds, commit ${commit:0:7}, $run"
printf '{"target": "%s", "executions": %s, "seconds": %s, "commit": "%s", "run": "%s", "date": "%s", "crashed": %s, "source": "%s", "all_targets": "%s", "total_executions": %s, "targets": [%s]}\n' \
  "$head_target" "$head_count" "$seconds" "$commit" "$run" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$crashed" "$source" "$names" "$total" "$objects" > "$out"

{
  echo "### Coverage-guided fuzzing of the verifier"
  echo
  echo "| target | seconds | executions | corpus (files) | crash |"
  echo "|---|---|---|---|---|"
  printf '%s' "$rows"
  echo
  echo "Counted from libFuzzer's final statistics. The same numbers are in the artifacts \`$(basename "$out")\` and \`$(basename "$lines")\`."
} >> "$summary"

if [ "$crashed" = true ]; then
  echo "The fuzzer found an input that fails:$found. It is in $crate/fuzz/artifacts." | tee -a "$summary"
  exit 1
fi
