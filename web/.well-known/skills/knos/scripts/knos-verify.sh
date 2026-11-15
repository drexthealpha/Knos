#!/usr/bin/env bash
# Run Knos on the committed change in the current checkout (or the one named by the first argument) and print the
# receipt as JSON. Exit 0 pass, 1 fail, 3 refused (the repository's AI policy bans AI-made pull requests).
# Needs the knos command (the knos package from PyPI). Reads the checkout; sends nothing anywhere.
set -euo pipefail
tree="${1:-.}"
shift || true
if ! command -v knos >/dev/null 2>&1; then
  echo "knos is not on PATH: install the knos package (version 0.4.1) and run this again" >&2
  exit 2
fi
exec knos verify --tree "$tree" --agent "Hermes Agent" --json "$@"
