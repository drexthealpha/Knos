"""The online demo's files (Round 9, U3): a Hugging Face Docker Space that runs the public edition of Knos on IRIS
(iris/docker-compose.public.yml: IRIS for Health Community 2026.2, replay mode, no key). The Space's Dockerfile is
iris/Dockerfile with its sources taken from a clone of this repository at one commit (a Space builds from its own
files, not from this repository), plus what a Space needs: the port, and the container's user ID 1000.

    python iris/space/make_space.py <commit> <out dir>   -> <out>/Dockerfile and <out>/README.md
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "containers.intersystems.com/intersystems/irishealth-community:2026.2"   # as docker-compose.public.yml


def dockerfile(commit: str) -> str:
    src = (ROOT / "iris" / "Dockerfile").read_text(encoding="utf-8")
    src = re.sub(r"(?m)^ARG IMAGE=.*\n", "", src)   # declared once, above the first FROM (the clone's stage)
    # every bind mount and COPY of a source reads it from the clone
    src = re.sub(r"--mount=type=bind,source=([^,\s]+)", r"--mount=type=bind,from=src,source=/src/\1", src)
    src = re.sub(r"(?m)^COPY --chown=irisowner:irisowner (?!--from)(\S+) ", r"COPY --from=src --chown=irisowner:irisowner /src/\1 ", src)
    head = (f"# Knos on IRIS, the public edition, for a Hugging Face Docker Space: made by iris/space/make_space.py from\n"
            f"# iris/Dockerfile at commit {commit} of https://github.com/drexthealpha/Knos (replay mode: no key, no money moves).\n"
            f"ARG IMAGE={IMAGE}\n"
            "FROM alpine:3.20 AS src\n"
            "RUN apk add --no-cache git \\\n"
            f" && git clone https://github.com/drexthealpha/Knos /src && cd /src && git checkout {commit} && rm -rf .git\n\n")
    tail = ("\n# a Space runs the container as user ID 1000: irisowner takes that ID (the image's own uid-1000 user is removed),\n"
            "# and what irisowner owned is given to it again\n"
            "USER root\n"
            "RUN old=$(id -u irisowner) && (userdel -r ubuntu 2>/dev/null || true) && usermod -u 1000 irisowner \\\n"
            " && find / -xdev -user \"$old\" -exec chown -h irisowner {} + 2>/dev/null; true\n"
            "USER irisowner\n"
            "ENV IRIS_PASSWORD=knos-public-demo KNOS_WEBHOOK_SECRET=knos-public-demo-webhook KNOS_VERDICT_SECRET=knos-public-demo-verdict KNOS_AI_MODE=replay\n"
            "EXPOSE 52773\n"
            "CMD [\"--after\", \"sh /home/irisowner/knos/iris/scripts/iris-password.sh\"]\n")
    return head + src + tail


def readme(commit: str) -> str:
    return ("---\ntitle: Knos on IRIS\nemoji: 🧪\ncolorFrom: gray\ncolorTo: blue\nsdk: docker\napp_port: 52773\npinned: false\n"
            "license: mit\nshort_description: An IRIS production that pays lab work only when its test passed.\n---\n\n"
            "Knos on InterSystems IRIS, the public edition (IRIS for Health Community 2026.2, replay mode: no key, test money only).\n\n"
            "Open `/knos/` on this Space and press **A passing test, $20**. The management portal is at `/csp/sys/UtilHome.csp` "
            "(user `_SYSTEM`, password `knos-public-demo`, a demo with nothing private in it).\n\n"
            f"Source: https://github.com/drexthealpha/Knos (commit {commit}); made by `iris/space/make_space.py`.\n")


if __name__ == "__main__":
    commit, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    (out / "Dockerfile").write_text(dockerfile(commit), encoding="utf-8", newline="\n")
    (out / "README.md").write_text(readme(commit), encoding="utf-8", newline="\n")
    print(out / "Dockerfile", out / "README.md")
