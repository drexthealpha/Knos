#!/usr/bin/env bash
# I6 test_iris_repro: each repro in iris/repro/ run on a build 154 container; PASS when at least one AI Hub and one
# Embedded Python repro show their bug, each with its one-paragraph REPORT.md.   bash iris/tests/test_iris_repro.sh <container> <result file>
set -uo pipefail
c="$1"; out="$2"
here="$(cd "$(dirname "$0")/.." && pwd)"
command -v cygpath >/dev/null && W="$(cygpath -w "$here")" || W="$here"
export MSYS_NO_PATHCONV=1
ai=0; epy=0
for d in "$here"/repro/*/; do
  name=$(basename "$d")
  if [ -f "$d/run.sh" ]; then got=$(bash "$d/run.sh" "$c" 2>&1 | tail -4 | tr '\n' ' ')
  else got=$(docker exec -i "$c" iris session IRIS -U %SYS < "$W/repro/$name/repro.script" 2>&1 | grep -v '^%SYS>\|^USER>\|^$' | tail -4 | tr '\n' ' '); fi
  rep=$(printf '%s' "$got" | grep -q "REPRODUCED:" && echo yes || echo no)
  [ "$rep" = yes ] && case "$name" in aihub-*) ai=$((ai+1));; epy-*) epy=$((epy+1));; esac
  echo "$([ "$rep" = yes ] && echo 'ok  ' || echo 'FAIL') $name: $(printf '%s' "$got" | cut -c1-230); report $([ -s "$d/REPORT.md" ] && echo written || echo missing)" | tee -a "$out"
done
if [ $ai -ge 1 ] && [ $epy -ge 1 ]; then echo "PASS test_iris_repro: $ai AI Hub and $epy Embedded Python repro(s) show their bug on build 154" | tee -a "$out"; exit 0; fi
echo "FAIL test_iris_repro: on build 154, $ai AI Hub and $epy Embedded Python leads reproduced; tried: every folder above" | tee -a "$out"
exit 1
