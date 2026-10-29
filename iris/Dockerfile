# Knos Referee on IRIS: InterSystems IRIS for Health build 154 with Knos's own code (src/knos) inside, the production
# compiled and started at build time. Built from the repository root (iris/docker-compose.yml: context ..).
# The base image comes from the EAP portal (iris/scripts/load-image.sh); this image and any built on it are never pushed.
ARG IMAGE=irishealth-community:2026.3.0AI.154.0
FROM $IMAGE
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
COPY --chown=irisowner:irisowner src/knos /home/irisowner/knos/src/knos
COPY --chown=irisowner:irisowner iris /home/irisowner/knos/iris
# the Java PEX operation, compiled with the image's own JDK against its own PEX jar (no Maven, no other image)
RUN cd /home/irisowner/knos/iris/java \
 && javac -d /tmp/pex -cp "/usr/irissys/dev/java/lib/1.8/*" src/main/java/knos/iris/pex/SolanaSubmitOperation.java \
 && (cd /tmp/pex && jar xf /usr/irissys/dev/java/lib/1.8/intersystems-pex-1.0.0-shaded.jar) \
 && jar cf /home/irisowner/knos/java/knos-iris-pex.jar -C /tmp/pex . && rm -rf /tmp/pex
ENV PYTHONPATH=/home/irisowner/knos/src:/home/irisowner/knos/iris/python KNOS_IRIS_HOME=/home/irisowner/knos
# every IRIS process (the production's jobs too) finds Knos and knos_iris, whatever its environment
RUN ln -sfn /home/irisowner/knos/src/knos /usr/irissys/mgr/python/knos \
 && ln -sfn /home/irisowner/knos/iris/python/knos_iris /usr/irissys/mgr/python/knos_iris
# IRIS's own memory, capped the same at build and at run. At build on 154 a merge restarts IRIS and the install session
# then waits forever (`iris merge` the same), and uncapped IRIS takes 25% of the VM (1,834 MB, which took Docker down),
# so the build writes merge.cpf's three values straight into iris.cpf; at run compose applies merge.cpf
RUN sed -i -e 's/^globals=.*/globals=0,0,192,0,0,0/' -e 's/^routines=.*/routines=48/' -e 's/^gmheap=.*/gmheap=98304/' /usr/irissys/iris.cpf \
 && grep -E '^(globals|routines|gmheap)=' /usr/irissys/iris.cpf \
 && iris start IRIS \
 && iris session IRIS < /home/irisowner/knos/iris/iris.script \
 && iris stop IRIS quietly
