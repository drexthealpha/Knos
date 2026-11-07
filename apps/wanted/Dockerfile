# Knos's demand check as one service: the web page + JSON API on $PORT (default 8080). Built from the ROOT of the Knos
# monorepo, so the app and the Knos it records and locks pre-orders with are the same commit:
#   docker build -f apps/wanted/Dockerfile -t knos-demand . && docker run -p 8080:8080 --env-file apps/wanted/.env knos-demand
# Qloo is reached from the server: its REST API first (knos_wanted.qloo_rest: QLOO_API_KEY + QLOO_BASE_URL; the decision
# needs it), and optionally `qloo mcp` (@qloo/qloo-harness, Node 22.19+) via the official MCP SDK for the older flow. Without
# QLOO_API_KEY the decision is "cannot decide: no Qloo evidence" and the MCP flow runs on Knos's MOCK (synthetic) server.
FROM node:22.19-bookworm-slim AS node

# knos-frost: the Zcash Foundation's frost-ed25519 (=3.0.0, Cargo.lock) as the referee's FROST command (knos.threshold)
FROM rust:1.88-slim-bookworm AS frost
WORKDIR /b
COPY tools/knos-frost ./
RUN cargo build --release --locked && strip target/release/knos-frost

FROM python:3.12-slim
COPY --from=node /usr/local/ /usr/local/
COPY --from=frost /b/target/release/knos-frost /usr/local/bin/knos-frost
RUN npm install --global --no-audit --no-fund @qloo/qloo-harness@0.1.26 && qloo --version
WORKDIR /src
COPY pyproject.toml README.md README.pypi.md LICENSE ./
COPY src ./src
COPY terms ./terms
COPY config/fees.yaml config/leitner.yaml config/referee-frost.json ./config/
COPY plugin/skills ./plugin/skills
COPY apps/wanted ./apps/wanted
COPY examples/autoresearch ./examples/autoresearch
COPY docs/idt/summary.json ./docs/idt/summary.json
RUN pip install --no-cache-dir . "./apps/wanted[escrow,auth,config,evidence,attest,saml]" && sh apps/wanted/bridge/install.sh
WORKDIR /app
RUN useradd --create-home app && mkdir -p /data && chown app /data
# the NEAR job runner of /near/ (knos_wanted.near_live): the agents, the checker and the job code, writable by the app
COPY --chown=app near/agents /app/near/agents
COPY --chown=app near/web/jobs_api.py near/web/latest.json near/web/market.json near/web/totals.json /app/near/web/
RUN chown -R app /app/near
USER app
ENV KNOS_NEAR_ROOT=/app HOST=0.0.0.0 PORT=8080 KNOS_WANTED_CACHE=/data/qloo-mcp KNOS_WANTED_STATE=/data/state KNOS_WANTED_RECORD=/data/record \
    PYTHONPATH=/src/apps/wanted KNOS_CLUSTER=devnet KNOS_FROST_BIN=/usr/local/bin/knos-frost KNOS_REFEREE_FROST_GROUP=/src/config/referee-frost.json
# QLOO_API_KEY and QLOO_BASE_URL come from the host's environment (Render's secrets): no Qloo host is named here
EXPOSE 8080
CMD ["python", "-m", "knos_wanted", "serve"]
