# A hermetic judge: the same black-box check, in an image pinned by digest

This folder is not a fourth task. It shows what to add to any black-box bundle (the three beside it, or one made by
`knos accept init`) so that the pull request's code runs in a container, and so that either party can run the judge
again and get the same verdict.

**1. Name the image, by digest, in `.knos/proof.toml` on the default branch** ([proof.toml](proof.toml)):

    [judge]
    image = "docker.io/library/python@sha256:0687a6bc9716edc2a6ee0fbfb0f87e7ee358b262b67c9215de91bc9b2d38ba71"

That is Docker Hub's `python:3.12-alpine` as its registry named it on 4 October 2026. To pin another image:
`docker buildx imagetools inspect <name>:<tag>` prints its digest. A tag alone (`python:3.12`) is refused, because a
tag can be pointed at another image after the bounty is funded. Everything the submission needs must be in the image:
the container has no network, so nothing is installed at judge time.

**2. The terms carry it** ([terms.json](terms.json)): `image` is a field of the terms like `accept`, so it is in the
hash that is funded and cannot change afterwards.

**3. What the submission sees.** Each `$KNOS_RUN <command>` of the check runs in a new container:

| | |
|---|---|
| network | none |
| root file system | read-only |
| `/submission` | the pull request's tree, read-only; the command starts here |
| `/work` | an empty tmpfs (64 MB), also `HOME` and `TMPDIR`; gone when the command ends |
| `/suite` | the bundle's `public/` folder, read-only, if the bundle has one: inputs the buyer lets the submission read |
| user | 65534, no capabilities, no way to gain one |
| limits | 512 MB memory, 1 CPU, 128 processes, 45 seconds a call |

The check itself (`blackbox.py`), its reference answers and the judge run outside the container, as before. A bundle
written for the host sandbox works unchanged if its command only reads the tree and prints; one that writes into the
tree must write to `/work` instead.

**4. Run it again.**

    knos proof judge --base base --pr pr --issue 7 --evidence verdict.json
    knos judge rerun verdict.json --base base --pr pr

The first writes the verdict: `"assurance": "hermetic"`, and under `evidence.image` the digest the runtime reported,
the runtime and its version and the limits; under `evidence.artifact` a hash of each tree. The second checks that the
two folders are those trees, judges them in the same image and prints `agree` or `disagree`. It needs docker or podman
(`KNOS_CONTAINER` chooses).

What this is not: a promise that no submission can cheat. The black-box check was accepted by 0 of the 63 attacks in
[docs/TAMPER.md](../../docs/TAMPER.md); the container's own probes are listed there, and were not run on the machine
that wrote that page. [docs/ASSURANCE.md](../../docs/ASSURANCE.md) has the three assurances side by side.
