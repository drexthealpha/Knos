# Knos on InterSystems IRIS

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

[Watch the 43-second video](https://drexthealpha.github.io/Knos/iris/) ·
[Full install steps](https://github.com/drexthealpha/Knos#from-the-intersystems-contest)

**One story.** A hospital lab funds a startup to build the online shop for its test kits. Step one pays $120 when the
checkout answers in under 300 ms. The test passes and an AI agent in IRIS says yes. Then the lab's approver presses
**Approve**. A failing test pays nothing.

## Quick start

You need Docker with about 4 GB free and the AI Hub image file, build 154
(`irishealth-community-2026.3.0AI.154.0-docker.tar.gz`), from the
[AI Hub Early Access portal](https://evaluation.intersystems.com/Eval/early-access/AIHub).

```sh
git clone https://github.com/drexthealpha/Knos && cd Knos/iris
bash scripts/load-image.sh ~/Downloads/irishealth-community-2026.3.0AI.154.0-docker.tar.gz
bash scripts/env-secrets.sh && docker compose up -d --build
bash scripts/ready.sh
```

When `ready.sh` prints `READY`, open http://localhost:52773/knos/ and press **A passing test, $20**. Replay mode, the
default, needs no key: the rules referee decides, with no model.

Troubleshooting and all 22 parts of the production are in
[the full IRIS section](https://github.com/drexthealpha/Knos#from-the-intersystems-contest).
