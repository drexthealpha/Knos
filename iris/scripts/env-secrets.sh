#!/usr/bin/env bash
# Fills IRIS_PASSWORD, KNOS_WEBHOOK_SECRET and KNOS_VERDICT_SECRET in iris/.env with random values where they are empty
# (a value already set is kept). Prints the names it filled, never the values.   bash iris/scripts/env-secrets.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
for name in IRIS_PASSWORD KNOS_WEBHOOK_SECRET KNOS_VERDICT_SECRET; do
  if ! grep -qE "^${name}=.+" .env; then
    v=$(openssl rand -hex 16)
    if grep -qE "^${name}=" .env; then sed -i "s/^${name}=.*/${name}=${v}/" .env; else echo "${name}=${v}" >> .env; fi
    echo "filled ${name} in iris/.env"
  fi
done
