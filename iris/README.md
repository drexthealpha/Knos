# Knos on InterSystems IRIS

An IRIS Interoperability production where an AI Hub agent decides if a lab's locked test criteria are met, and only then a payout step runs.

- Online demo, no login: https://glowing-xylophone-x5vxgjgjgv9399xq-52773.app.github.dev/knos/ (GitHub shows a notice first: press Continue).
  Online 13:00 to 23:00 UTC on 14 Nov, and from 13:00 UTC on 15 Nov to 05:00 UTC on 16 Nov, when voting ends.
- Video, 43 s, a live run on 13 Nov 2026: [knos-iris.mp4](https://raw.githubusercontent.com/drexthealpha/Knos/main/iris/media/knos-iris.mp4)
- [Judge it in 2 minutes](#judge-it-in-2-minutes): on the online demo, or with one command on your machine.

Built and tested on build 154 (`irishealth-community-2026.3.0AI.154.0`).

## The lab's story

A hospital lab funds a startup to build the online shop for its test kits. Step one pays $120 when the checkout answers
in under 300 ms. The test passes and the AI Hub agent in IRIS says the criterion is met. Then the lab's approver presses
**Approve**, because a payout above $50 waits for a person. A failing test pays nothing.

Two choices are mine, and they shape the rest:

- **An agent that can only say no.** A lab cannot let a model pay anyone. So the agent has no tool that moves money: it
  may only say met, not met or insufficient. Code checks that answer, and a person approves anything large.
- **The trace stays inside IRIS.** A lab cannot send its data to an outside tracing service. IRIS already keeps an
  audited record of every message, so every step of the decision, the model call included, is an interoperability
  message in the decision's own session.

## Judge it in 2 minutes

On the online demo:

1. Open the demo link above (press Continue on GitHub's notice) - see "Decisions" and three sample buttons.
2. Press **A passing test, $20** - see a new decision marked paid: "Paid in play money".
3. Click that decision - see "How it decided": the referee's model call on NEAR AI Cloud with its tokens and cost, and the
   session's messages read from IRIS.

On your machine, with Docker and about 4 GB free (the first build takes about 4 minutes):

```sh
git clone https://github.com/drexthealpha/Knos && cd Knos/iris
docker compose -f docker-compose.public.yml up -d --build && bash scripts/ready.sh
```

When it prints `READY`, open http://localhost:52773/knos/ and press **A passing test, $20** - see "Paid in play money".
This one-command edition is the public IRIS for Health Community image (2026.2) in replay mode: it does not run the AI
Hub agent (its image has no AI Hub), and the rules referee decides.

## The contest task, part by part

| The task asks for | The feature doing it | How to see it |
|---|---|---|
| An Interoperability workflow | `Knos.Iris.Production`, 22 items. Services: `ProofIn`, `BriefIn`, `GitHubCheckRunPoller` (custom inbound adapter), `HL7LabIn` (HL7 ORU files), `FHIRLabIn` (FHIR Observation files), `DeadlineWatch` (not paid at the deadline), `DailyDigest` (the day's decisions and model cost), `SpendCapWatch` (alert before the model cap), `ApproverReminder` (payouts left waiting). Processes: `ProofDecision` (BPL), `DecisionRouter` (routing rule). Operations: `BriefLock`, `Referee` (the AI Hub agent), `PayoutApprovers` (Workflow), `SolanaRead` (custom outbound adapter), `SolanaSubmit` (Java PEX), `TraceSink`, `Ens.Alert`, `ReceiptFile` (a JSON receipt per decision), `DecisionFHIR` (a FHIR R4 Task per decision), `ResultHL7Out` (the decision back to the lab as HL7), `DigestFile` | Interoperability > Production |
| An AI Hub agent | operation `Referee` running `Knos.Iris.AI.LocalReferee`: in the online demo it asks NEAR AI Cloud (deepseek-ai/DeepSeek-V4.1-Flash-1017) through AI Hub's openai provider, one call a sample and no tools (the brief and the proof are in its question); on your machine with `KNOS_AI_MODE=local` it asks `qwen2.5:1.5b-instruct` in the compose file's `ollama` service, no key; in replay mode (the default) the rules referee decides, with no model | the Verdict message of each decision |
| A decision-making task | the agent answers met, not met or insufficient; code checks that answer, then `Knos.Iris.Rule.PayoutGate` says PAY, HUMAN, REFUND_AT_DEADLINE or REJECT | the Decision message |
| A person where it matters | IRIS Workflow, role `PayoutApprovers`, for a met decision above 50 USDC | the inbox on `/knos/` or Interoperability > Workflow Inbox |
| Every step traceable | each model call, tool call, rule and approval is a `Knos.Iris.Msg.Span` in the decision's own session | the trace on `/knos/`, or Visual Trace |

## What is new, and why

- **The trace is the production's own message log.** Every step of the agent's decision is an interoperability
  message, kept in a Langfuse-style SQL table, inside the lab's own IRIS. It implements the Community idea
  [DPI-I-689](https://ideas.intersystems.com/ideas/DPI-I-689).
- **An agent that can only say no.** It has no tool that moves money; code checks its answer, and a person approves
  anything large.
- **Vector Search keeps the agent honest.** The proof's two nearest criteria come from IRIS Vector Search
  (snowflake-arctic-embed-s, run in Embedded Python). A verdict that cites a criterion outside those two is capped at
  0.6 confidence and goes to a person.
- **The brief is locked by a hash.** The brief is hashed with Knos's own `knos.ready.criteria_hash`, run in Embedded
  Python from the same `src/knos` that the Knos app uses. Proof against a changed brief is refused before any model is
  asked.

## Build 154 with AI Hub

You need the image file `irishealth-community-2026.3.0AI.154.0-docker.tar.gz` from the
[AI Hub Early Access portal](https://evaluation.intersystems.com/Eval/early-access/AIHub) (an InterSystems login).

```sh
git clone https://github.com/drexthealpha/Knos && cd Knos/iris
bash scripts/load-image.sh ~/Downloads/irishealth-community-2026.3.0AI.154.0-docker.tar.gz
bash scripts/env-secrets.sh && docker compose up -d --build
bash scripts/ready.sh
```

When `ready.sh` prints `READY`, open http://localhost:52773/knos/ and press **A passing test, $20**. Replay mode, the
default, needs no key; the model, its provider and its key are set in `iris/.env`
([the full IRIS reference](https://github.com/drexthealpha/Knos/blob/main/docs/reference/IRIS.md)).

## Why I built this

A solo founder in Lagos, building Knos since 1 Sep 2026. IRIS, Docker and the build would not fit on an 8 GB laptop,
so every IRIS build and test moved to one GitHub Codespace
([the problems I hit](https://github.com/drexthealpha/Knos/blob/main/docs/reference/IRIS.md#problems-i-hit-and-how-i-fixed-them)).
Claude Code wrote most of the code; the design choices above, and every decision about what the agent may do, are mine.
