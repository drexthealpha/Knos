# Interoperability as an LLM trace tool: tokens, cost and tool calls in the trace view

Can interoperability do the traceability job of an LLM pipeline? The community idea
[DPI-I-689](https://ideas.intersystems.com/ideas/DPI-I-689) asks exactly that.
In Knos on IRIS every step of an agent's decision is an interoperability message, so Visual Trace already shows
the pipeline, and SQL can read it.

## The Span message

`Knos.Iris.Msg.Span` carries trace id, span id, parent, kind (llm, tool, rag, policy, rule, chain, verdict), name,
input, output, score, milliseconds, tokens, cost and model. The referee sends one for its call; the BPL sends one for the
gate; the approval is the Workflow task message in the same session. `TraceSink` keeps each in `Knos_Iris_Data.Span` with its session id.

## The `%AI.Policy.Audit` hook

`Knos.Iris.AI.TraceAudit` extends `%AI.Policy.Audit`. Its `%LogExecution(call, metadata, result, duration, status)` writes
each tool call the agent makes as a span, so tool calls sit between the referee's request and its response.

## The SQL view next to the Langfuse schema

| Knos_Iris_Data.Span | Langfuse |
|---|---|
| SessionId | trace id |
| SpanId, ParentId | observation id, parent observation id |
| Kind | observation type (generation for llm, span for the rest) |
| Name, Model | name, model |
| Tokens, CostUSD | usage, calculated total cost |
| Ms, StartedAt | latency, start time |
| Score | score |

`GET /api/knos/traces/<session>` returns the spans and the session's messages as nested JSON.

## Tokens and cost per decision

Each Verdict carries input tokens, output tokens and cost in US dollars, from the provider's own usage. A replayed or
rules decision shows 0 tokens. On NEAR AI Cloud (DeepSeek-V4.1-Flash-1017) the 12 held-out calls cost $0.0086 at a
2,500-token cap (iris/README.md, "Measured: the agent against the fixed rule").

## Building with IRIS Agentic Dev

The classes were written as UDL files and compiled into a running build 154 container with one script
(`iris/scripts/compile-probe.sh`), so a change reaches the production without a rebuild.
