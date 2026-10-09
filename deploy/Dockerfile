# Knos in the buyer's own cloud: one image, three roles (record, relay, site). docs/SELFHOST.md.
#
#   KNOS_COMMIT=$(git rev-parse HEAD) docker compose -f deploy/compose.yaml build
#
# Built from the repository root (compose sets the context). Every FROM names its base by digest, and every Python
# package is installed by its hash: requirements/faucet.txt (solders and the memory engine, what the faucet job installs)
# and the last line of requirements/sign.txt, which names the released knos wheel and its hash (written at a release by
# scripts/pinned_workflows.py lock). No source tree is installed: the image runs the wheel PyPI has under that hash.
#
# python:3.12-slim as Docker Hub listed it on 6 Oct 2026 (the multi-platform index digest):
#   https://hub.docker.com/v2/namespaces/library/repositories/python/tags/3.12-slim
# Move it on purpose, never by a tag: replace the digest in all three FROM lines below together.

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS install
WORKDIR /build
COPY requirements/faucet.txt requirements/sign.txt ./
RUN python -m venv /opt/knos \
 && /opt/knos/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes --no-deps --only-binary :all: -r faucet.txt \
 && tail -n 1 sign.txt > knos.txt \
 && grep -Eq '^knos==[0-9][0-9.]* --hash=sha256:[0-9a-f]{64}$' knos.txt \
 && /opt/knos/bin/pip install --no-cache-dir --disable-pip-version-check --require-hashes --no-deps --only-binary :all: -r knos.txt \
 && /opt/knos/bin/python -m knos.selfhost --help > /dev/null    # the wheel must have knos.selfhost (0.3.23 on)

# The static site, built as the Pages build builds it (scripts/build_site.sh needs the standard library only), from the
# commit named: the page hands out a workflow only when it is named by a full commit.
FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f AS site
ARG KNOS_COMMIT
WORKDIR /src
COPY . .
RUN bash scripts/build_site.sh /site "$KNOS_COMMIT"

FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
COPY --from=install /opt/knos /opt/knos
COPY --from=site /site /srv/knos/site
RUN useradd --system --uid 10001 --home-dir /var/lib/knos --no-create-home knos \
 && mkdir -p /var/lib/knos /etc/knos /run/secrets \
 && chown knos /var/lib/knos
ENV PATH=/opt/knos/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER knos
WORKDIR /var/lib/knos
ENTRYPOINT ["python", "-m", "knos.selfhost"]
CMD ["--help"]
