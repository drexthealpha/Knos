# For the Glama listing check: the server must start and answer an MCP
# introspection request. Knos is a stdio server, so this image is only ever
# a harness for that check - a real user runs `pip install knos` on the
# machine whose repos and agent history they want read. In a container it
# has neither, and answers accordingly rather than failing.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir knos==0.1.2

WORKDIR /repo
ENTRYPOINT ["python", "-m", "knos.mcp"]
