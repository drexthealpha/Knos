# Knos Referee on IRIS: InterSystems IRIS for Health build 154 with Knos's own code (src/knos) inside, the production
# compiled at build time. Built from the repository root (iris/docker-compose.yml: context ..).
# The base image comes from the EAP portal (iris/scripts/load-image.sh); this image and any built on it are never pushed.
#
# Multi-stage, as the InterSystems community builds IRIS images (github.com/grongierisc/iris-docker-multi-stage-script,
# intersystems-community/iris-fhir-template): IRIS runs the install in the builder stage, and the final stage starts again
# from the base image and copies in only the databases the install changed (iris/scripts/copy-data.py, about 0.2 GB).
# One IRIS run in one RUN used to write a multi-GB last layer, about 100 minutes on a 5400 rpm disk. Sources come in with
# RUN --mount=type=bind, so the builder writes no source layer; the final stage keeps them in one small layer.
ARG IMAGE=irishealth-community:2026.3.0AI.154.0

# ---- base: what the builder and the final image share (each step cached until its own line changes) ----------------
FROM $IMAGE AS base
# FHIR is optional (KNOS_FHIR=1 loads the R4 endpoint, about 2 GB more at build); the Observation path needs no FHIR server
ARG KNOS_FHIR=0
ENV KNOS_FHIR=$KNOS_FHIR
USER root
# the FHIR core packages HealthShare Foundation loads at install: with FHIR off none (they took the build past 1,800 s
# and Docker down on a 7.8 GB PC); with KNOS_FHIR=1 only R4, the one the endpoint uses
RUN cd /usr/irissys/dev/fhir/fhir-metadata/packages \
 && if [ "$KNOS_FHIR" = "1" ]; then rm -rf hl7.fhir.r3.core hl7.fhir.r5.core hl7.fhir.us.core; else rm -rf ./*; fi
RUN mkdir -p /home/irisowner/knos/inbox/oru /home/irisowner/knos/inbox/verdicts /home/irisowner/knos/inbox/checkruns /home/irisowner/knos/java \
 && chown -R irisowner:irisowner /home/irisowner/knos
USER irisowner
# Knos's only Solana dependency, beside IRIS's own Python (pyproject.toml: solders)
RUN pip3 install --quiet --break-system-packages --target /usr/irissys/mgr/python "solders>=0.21,<0.30" "base58>=2"
ENV PYTHONPATH=/home/irisowner/knos/src:/home/irisowner/knos/iris/python KNOS_IRIS_HOME=/home/irisowner/knos
# every IRIS process (the production's jobs too) finds Knos and knos_iris, whatever its environment
RUN ln -sfn /home/irisowner/knos/src/knos /usr/irissys/mgr/python/knos \
 && ln -sfn /home/irisowner/knos/iris/python/knos_iris /usr/irissys/mgr/python/knos_iris

# ---- jar: the Java PEX operation, compiled with the image's own JDK against its own PEX jar (no Maven, no other image) -
FROM base AS jar
RUN --mount=type=bind,source=iris/java,target=/tmp/java \
    javac -d /tmp/pex -cp "/usr/irissys/dev/java/lib/1.8/*" /tmp/java/src/main/java/knos/iris/pex/SolanaSubmitOperation.java \
 && (cd /tmp/pex && jar xf /usr/irissys/dev/java/lib/1.8/intersystems-pex-1.0.0-shaded.jar) \
 && jar cf /home/irisowner/knos/java/knos-iris-pex.jar -C /tmp/pex . && rm -rf /tmp/pex

# ---- builder: IRIS installs the KNOS namespace, then loads and compiles Knos and sets it up ---------------------------
FROM base AS builder
# IRIS's own memory, capped the same at build and at run. At build on 154 a merge restarts IRIS and the install session
# then waits forever (`iris merge` the same), and uncapped IRIS takes 25% of the VM (1,834 MB, which took Docker down),
# so the build writes merge.cpf's three values straight into iris.cpf; at run compose applies merge.cpf.
# The namespace step needs no Knos source, so a change to iris/src never runs it again.
RUN --mount=type=bind,source=iris/scripts/namespace.script,target=/tmp/namespace.script \
    sed -i -e 's/^globals=.*/globals=0,0,192,0,0,0/' -e 's/^routines=.*/routines=48/' -e 's/^gmheap=.*/gmheap=98304/' /usr/irissys/iris.cpf \
 && grep -E '^(globals|routines|gmheap)=' /usr/irissys/iris.cpf \
 && iris start IRIS \
 && iris session IRIS < /tmp/namespace.script \
 && iris stop IRIS quietly
# iris.script ends with the production stopped cleanly, so a new container auto-starts it without journal recovery.
# The compile runs with 64 MB of global buffers (less memory to page on a 7.8 GB PC), then the run caps are put back.
RUN --mount=type=bind,source=src/knos,target=/home/irisowner/knos/src/knos \
    --mount=type=bind,source=iris/src,target=/home/irisowner/knos/iris/src \
    --mount=type=bind,source=iris/python,target=/home/irisowner/knos/iris/python \
    --mount=type=bind,source=iris/iris.script,target=/tmp/iris.script \
    --mount=type=bind,from=jar,source=/home/irisowner/knos/java,target=/home/irisowner/knos/java \
    sed -i -e 's/^globals=.*/globals=0,0,64,0,0,0/' -e 's/^routines=.*/routines=32/' /usr/irissys/iris.cpf \
 && iris start IRIS \
 && iris session IRIS < /tmp/iris.script \
 && iris stop IRIS quietly \
 && sed -i -e 's/^globals=.*/globals=0,0,192,0,0,0/' -e 's/^routines=.*/routines=48/' /usr/irissys/iris.cpf

# ---- final: the base image plus the changed databases and the files IRIS reads at run ---------------------------------
FROM base AS final
# the builder's iris.cpf (the KNOS namespace and the memory caps), then each database it changed: the system ones file
# by file, the new ones whole; never the shared libraries (HSLIB, ENSLIB, IRISLIB), the journal or the WIJ. --csp and
# -p turn off copy-data.py's whole-folder CSP and Python copies: Python is already here from the base stage.
RUN --mount=type=bind,from=builder,source=/,target=/builder/root \
    --mount=type=bind,source=iris/scripts/copy-data.py,target=/tmp/copy-data.py \
    cp -f /builder/root/usr/irissys/iris.cpf /usr/irissys/iris.cpf \
 && python3 /tmp/copy-data.py -c /usr/irissys/iris.cpf -d /builder/root/ --csp -p -o usr/irissys/csp/healthshare
# the files IRIS uses at run: Knos's package, iris/ (merge.cpf, knos_iris, fixtures, the health check's script), the jar
COPY --chown=irisowner:irisowner src/knos /home/irisowner/knos/src/knos
COPY --chown=irisowner:irisowner iris /home/irisowner/knos/iris
COPY --from=jar --chown=irisowner:irisowner /home/irisowner/knos/java/knos-iris-pex.jar /home/irisowner/knos/java/knos-iris-pex.jar
