# Knos's demand check as one service: the web page + JSON API on $PORT (default 8080). Built from the ROOT of the Knos
# monorepo, so the app and the Knos it records and locks pre-orders with are the same commit:
#   docker build -f apps/wanted/Dockerfile -t knos-demand . && docker run -p 8080:8080 --env-file apps/wanted/.env knos-demand
# The demand check reads free, keyless public sources (knos_wanted.open_signals): no key is needed for it.
FROM node:22.19-bookworm-slim AS node

# knos-frost: the Zcash Foundation's frost-ed25519 (=3.0.0, Cargo.lock) as the referee's FROST command (knos.threshold)
FROM rust:1.88-slim-bookworm AS frost
WORKDIR /b
COPY tools/knos-frost ./
RUN cargo build --release --locked && strip target/release/knos-frost

FROM python:3.12-slim
COPY --from=node /usr/local/ /usr/local/
COPY --from=frost /b/target/release/knos-frost /usr/local/bin/knos-frost
WORKDIR /src
COPY pyproject.toml README.md README.pypi.md LICENSE ./
COPY src ./src
COPY terms ./terms
COPY config/fees.yaml config/leitner.yaml config/referees.yaml config/referee-frost.json ./config/
COPY plugin/skills ./plugin/skills
COPY apps/wanted ./apps/wanted
COPY examples/autoresearch ./examples/autoresearch
COPY docs/idt/summary.json ./docs/idt/summary.json
RUN pip install --no-cache-dir . "./apps/wanted[hold,auth,config,evidence,attest,saml,nearai]" "numpy==2.3.4"
WORKDIR /app
RUN useradd --create-home app && mkdir -p /data && chown app /data
# the NEAR job runner of /near/ (knos_wanted.near_live): the agents, the checker and the job code, writable by the app
COPY --chown=app near/agents /app/near/agents
COPY --chown=app near/web/jobs_api.py near/web/latest.json near/web/market.json near/web/totals.json /app/near/web/
COPY --chown=app near/scripts/near_counters.py /app/near/scripts/
COPY --chown=app near/claims/claims.json near/claims/usdc_market.json /app/near/claims/
COPY --chown=app near/balances.json /app/near/
COPY --chown=app scripts/near_balances.py scripts/tool_manifest.py /app/scripts/
# /api/tools lists what scripts/tool_manifest.py listed() passes (IQ L49): the manifests beside their locked tests
COPY --chown=app tools/limit-check/manifest.json /app/tools/limit-check/
COPY --chown=app web/i18n /app/web/i18n
RUN chown -R app /app/near
USER app
ENV KNOS_NEAR_ROOT=/app HOST=0.0.0.0 PORT=8080 KNOS_WANTED_STATE=/data/state KNOS_WANTED_RECORD=/data/record \
    PYTHONPATH=/src/apps/wanted KNOS_CLUSTER=devnet KNOS_FROST_BIN=/usr/local/bin/knos-frost KNOS_REFEREE_FROST_GROUP=/src/config/referee-frost.json
EXPOSE 8080
CMD ["python", "-m", "knos_wanted", "serve"]
