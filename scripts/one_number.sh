#!/usr/bin/env bash
# H7 test_one_number: grep the tracked tree for the retired figures and list every hit that remains, with its file:line
# and the reason it stays (scripts/one_number_reasons.tsv: a path pattern, a line pattern, the reason; the first rule
# that matches wins). A hit no rule explains is printed as NO REASON and the script exits 1.
#
#   bash scripts/one_number.sh            # the list, then one line of counts
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
RULES=scripts/one_number_reasons.tsv
PATTERNS=(-e '(^|[^0-9.])2\.5%' -e '\b48 h' -e '48-hour' -e '2\.08x' -e '2\.11x' -e '63/63' -e '\+0\.033' -e 'fee of 0\.05')

git grep -n -I -E "${PATTERNS[@]}" -- . ':!scripts/one_number.sh' ":!$RULES" ':!world/' | awk -v rules="$RULES" '
BEGIN {
  FS = "\t"
  while ((getline r < rules) > 0) {
    if (r ~ /^#/ || r == "") continue
    split(r, f, "\t"); n++; P[n] = f[1]; L[n] = f[2]; W[n] = f[3]
  }
  FS = ":"
}
{
  path = $1; line = $2; text = substr($0, length(path) + length(line) + 3)
  why = ""
  for (i = 1; i <= n; i++) if (path ~ P[i] && text ~ L[i]) { why = W[i]; break }
  if (why == "") { why = "NO REASON"; bad++ }
  hits++; by[why]++
  printf "%s:%s\t%s\n", path, line, why
}
END {
  printf "\n%d hits, %d with a reason, %d with none\n", hits, hits - bad, bad
  for (w in by) printf "  %4d  %s\n", by[w], w
  exit bad > 0
}'
