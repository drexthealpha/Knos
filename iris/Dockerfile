# Knos Referee on IRIS: InterSystems IRIS for Health build 154 with Knos's own code (src/knos) inside, the production
# compiled and started at build time. Built from the repository root (iris/docker-compose.yml: context ..).
# The base image comes from the EAP portal (iris/scripts/load-image.sh); this image and any built on it are never pushed.
ARG IMAGE=irishealth-community:2026.3.0AI.154.0
FROM $IMAGE
USER root
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
ENV PYTHONPATH=/home/irisowner/knos/src:/home/irisowner/knos/iris/python
# every IRIS process (the production's jobs too) finds Knos and knos_iris, whatever its environment
RUN ln -sfn /home/irisowner/knos/src/knos /usr/irissys/mgr/python/knos \
 && ln -sfn /home/irisowner/knos/iris/python/knos_iris /usr/irissys/mgr/python/knos_iris
RUN iris start IRIS \
 && iris session IRIS < /home/irisowner/knos/iris/iris.script \
 && iris stop IRIS quietly
