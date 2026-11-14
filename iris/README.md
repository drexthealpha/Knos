# Knos on InterSystems IRIS

An IRIS Interoperability production where an AI Hub agent decides if a lab's locked test criteria are met, and only then a payout step runs.

- Online demo, no login: https://glowing-xylophone-x5vxgjgjgv9399xq-52773.app.github.dev/knos/ (GitHub shows a notice first: press Continue).
  Online without a break until 05:00 UTC on 16 Nov, when voting ends.
- Video, 43 s, a live run on 13 Nov 2026: [knos-iris.mp4](https://raw.githubusercontent.com/drexthealpha/Knos/main/iris/media/knos-iris.mp4)
- [Judge it in 2 minutes](#judge-it-in-2-minutes): on the online demo, or with one command on your machine.

Built and tested on build 154 (`irishealth-community-2026.3.0AI.154.0`). Build 109, which the portal lists now, is
untested: on 14 Nov `containers.intersystems.com` had no `2027.1.0AI.109.0` image ("no such manifest"), and the portal's
file needs an InterSystems login.

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
   session's messages read from IRIS. When NEAR AI Cloud does not answer, a line above the buttons says so, the fixed
   rule decides, and the referee row says why.

On your machine, with Docker and about 4 GB free (the first build takes about 4 minutes):

```sh
git clone https://github.com/drexthealpha/Knos && cd Knos/iris
docker compose -f docker-compose.public.yml up -d --build && bash scripts/ready.sh
```

When it prints `READY`, open http://localhost:52773/knos/ and press **A passing test, $20** - see "Paid in play money".
This one-command edition is the public IRIS for Health Community image (2026.2), which has no AI Hub. Its three samples
replay the AI Hub agent's answers recorded in the online demo on 14 Nov ([iris/fixtures/recorded](fixtures/recorded)) through
the same production, and the referee row says so; no model is asked. Any other proof is decided by the rules referee.

## The contest task, part by part

| The task asks for | The feature doing it | How to see it |
|---|---|---|
| An Interoperability workflow | `Knos.Iris.Production`, 22 items. Services: `ProofIn`, `BriefIn`, `GitHubCheckRunPoller` (custom inbound adapter), `HL7LabIn` (HL7 ORU files), `FHIRLabIn` (FHIR Observation files; FHIR is off in the online demo, `KNOS_FHIR=1` turns it on), `DeadlineWatch` (not paid at the deadline), `DailyDigest` (the day's decisions and model cost), `SpendCapWatch` (alert before the model cap), `ApproverReminder` (payouts left waiting). Processes: `ProofDecision` (BPL), `DecisionRouter` (routing rule). Operations: `BriefLock`, `Referee` (the AI Hub agent), `PayoutApprovers` (Workflow), `SolanaRead` (custom outbound adapter), `SolanaSubmit` (Java PEX), `TraceSink`, `Ens.Alert`, `ReceiptFile` (a JSON receipt per decision), `DecisionFHIR` (a FHIR R4 Task per decision), `ResultHL7Out` (the decision back to the lab as HL7), `DigestFile` | Interoperability > Production |
| An AI Hub agent | operation `Referee` running `Knos.Iris.AI.LocalReferee`: in the online demo it asks NEAR AI Cloud (deepseek-ai/DeepSeek-V4.1-Flash-1017) through AI Hub's openai provider, one call a sample and no tools (the brief and the proof are in its question); on your machine with `KNOS_AI_MODE=local` it asks `qwen2.5:1.5b-instruct` in the compose file's `ollama` service, no key; in replay mode (the default) a sample replays the agent's answer recorded in the online demo, and the rules referee decides any other proof, with no model | the Verdict message of each decision |
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

When `ready.sh` prints `READY`, open http://localhost:52773/knos/ and press **A passing test, $20**. It starts in replay
mode, where the samples replay the agent's recorded answers and no model is asked. To run the AI Hub agent, set
`KNOS_AI_MODE=local` in `iris/.env` and start with `docker compose --profile local up -d --build`: it asks
`qwen2.5:1.5b-instruct` in the `ollama` service through AI Hub's openai provider, no key. For an OpenAI-compatible endpoint
with a key (the online demo uses NEAR AI Cloud), export its endpoint and model (`KNOS_LOCAL_LLM_URL`, `KNOS_LOCAL_MODEL`) and its key
(`KNOS_LOCAL_LLM_KEY`) in your shell before `docker compose up`; the key never goes in a file
([the full IRIS reference](https://github.com/drexthealpha/Knos/blob/main/docs/reference/IRIS.md)).

## Measured: the agent against the fixed rule

Twelve held-out cases, each with the decision a careful lab reviewer gives, were committed
([faf9c4b1](https://github.com/drexthealpha/Knos/commit/faf9c4b1), [iris/fixtures/heldout/cases.json](fixtures/heldout/cases.json))
before either referee saw them. On 14 Nov the AI Hub agent (DeepSeek-V4.1-Flash-1017 on NEAR AI Cloud, the online demo's
container) and the fixed rule each decided all twelve, twice: run 1 with the agent capped at 800 tokens, run 2 at 2,500.
Knos itself takes the stricter of the agent and the fixed rule.

| Case | Expected | Agent, run 1 | Agent, run 2 | Fixed rule | Knos, run 2 |
|---|---|---|---|---|---|
| h01 check passed, p95 188 ms | met | met | met | met | met |
| h02 check failed | not met | not met | not met | not met | not met |
| h03 "success", but its p95 is 412 ms | not met | no answer | not met | met | not met |
| h04 "success", p95 exactly 300 ms | not met | no answer | met | met | **met (wrong)** |
| h05 p95 299 ms | met | met | met | met | met |
| h06 run skipped | insufficient | not met | not met | not met | not met |
| h07 run still in progress | insufficient | not met | not met | not met | not met |
| h08 a different check passed | insufficient | insufficient | insufficient | insufficient | insufficient |
| h09 failed, text asks for met | not met | not met | not met | not met | not met |
| h10 neutral, 0 requests sent | insufficient | not met | not met | not met | not met |
| h11 one glucose value, 12 samples asked | insufficient | not met | not met | met | not met |
| h12 glucose 7.4 mmol/L | not met | not met | not met | not met | not met |
| **Right** | | **6 of 12** | **7 of 12** | **6 of 12** | **7 of 12** |
| **Would pay wrongly** | | **0** | **1** | **3** | **1** |

In run 1, Knos would have paid wrongly twice; in run 2, once. The fixed rule reads only a check's name and conclusion, so
it says met three times where it should not. In run 1 the agent reasoned in its reply past its 800-token cap on h03 and
h04 and never gave the JSON, so the fixed rule decided; DeepSeek V4 Flash thinks by default, so run 2 raised the cap.

In run 2 the agent caught h03 (a "success" whose own number misses the target) and missed h04 (300 ms is not under 300).
On h06, h07 and h10 both said not met where the right answer is insufficient: nothing is paid either way, but a not met
refunds the funder where an insufficient would ask a person. The ten answered calls of run 1 cost $0.0056, the twelve of
run 2 $0.0086. The online demo runs at the run 2 cap.

## What I ran into on AI Hub

- `%AI.ToolMgr.ExecuteTool` runs a tool with arguments its own schema refuses ([ai-hub-eap-bugreports#20](https://github.com/intersystems-community/ai-hub-eap-bugreports/issues/20), [repro](bugs/2)).
- `%AI.RAG.VectorStore.IRIS` makes its table in SQLUser whatever its `Schema` says ([ai-hub-eap-bugreports#21](https://github.com/intersystems-community/ai-hub-eap-bugreports/issues/21), [repro](bugs/3)).
- The IPM install failed with ERROR #5289: a ToolSet compiled before its tools; a `DependsOn` fixed the order.
- The small local model, given tools, looked the brief up by the wrong key and gave up, so the agent has no tools now.
- The knowledge base's embedding model loads on its first build, so the first decision after a start got HTTP 500; `ready.sh` now warms it.
- DeepSeek V4 Flash on NEAR AI Cloud thinks by default: capped at 800 tokens it sometimes reasoned in its reply and never reached the JSON (h03, h04 above), so the cap is now 2,500.
- Embedded Python, beside AI Hub: an int above 2^63 - 1 arrives in ObjectScript as -1 ([python-bugreports#30](https://github.com/intersystems-community/python-bugreports/issues/30), [repro](bugs/1)), and `iris.sql.exec` with one fails with a bare `SystemError` ([python-bugreports#31](https://github.com/intersystems-community/python-bugreports/issues/31), [repro](bugs/4)).

## Each bonus, and why a lab needs it

- **Workflow Engine:** a payout above $50 waits in the `PayoutApprovers` inbox, because a lab will not let software pay a large sum alone.
- **Custom adapters:** `CheckRunInbound` reads test results where the startup's CI writes them; `SolanaRpcOutbound` reads the payout's chain state, which no stock adapter does.
- **PEX (Java):** `SolanaSubmit` only sends a transaction that Knos's own code built and signed, and holds no key, so the part that talks to the chain cannot sign.
- **Embedded Python:** the brief's hash is Knos's own `knos.ready` code, so the lab and the payer check the same lock.
- **Vector Search:** the proof's two nearest criteria come from IRIS, so a verdict citing anything else goes to a person.
- **Docker:** the lab runs it on its own machine with one command, so its data stays inside.
- **ZPM:** an IRIS team installs it into its own instance with `zpm "install knos-iris"`.
- **Online demo:** a judge or a lab sees a live decision without installing anything.
- **Community idea [DPI-I-689](https://ideas.intersystems.com/ideas/DPI-I-689):** a lab must audit every step an AI took, and the production's own message log is that audit.
- **Bug reports:** each one filed above has a repro, so the next lab building on AI Hub does not lose the same day.
- **Articles and video:** the [first](https://community.intersystems.com/post/what-one-ai-decision-costs-iris-tokens-and-dollars-traced-call) and [second](https://community.intersystems.com/post/ai-can-only-say-no-inside-intersystems-iris) article explain the design to a lab's IRIS team; the video shows one decision end to end.

## Why I built this

A solo founder in Lagos, building Knos since 1 Sep 2026. IRIS, Docker and the build would not fit on an 8 GB laptop,
so every IRIS build and test moved to one GitHub Codespace
([the problems I hit](https://github.com/drexthealpha/Knos/blob/main/docs/reference/IRIS.md#problems-i-hit-and-how-i-fixed-them)).
Claude Code wrote most of the code; the design choices above, and every decision about what the agent may do, are mine.

Two problems on build 154 shaped the agent. The small local model, given tools, looked the brief up by the wrong key and
gave up; so I took its tools away and put the brief and the proof in its question, and code checks its answer. The IPM
install failed with ERROR #5289 because a ToolSet compiled before its tools; a `DependsOn` fixed the order, and the
install then passed on build 154.
