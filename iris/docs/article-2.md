# Interoperability as an LLM trace tool (DPI-I-689): tokens, cost and tool calls in Visual Trace

The Community Opportunity idea DPI-I-689 asks whether interoperability can do the traceability job of an LLM pipeline.
In Knos Referee on IRIS every step of an agent's decision is an interoperability message, so Visual Trace already shows
the pipeline, and SQL can read it.

## The Span message

`Knos.Iris.Msg.Span` carries trace id, span id, parent, kind (llm, tool, rag, policy, rule, workflow, chain), name,
input, output, score, milliseconds, tokens, cost and model. The referee sends one for its call; the BPL sends one for the
gate; Workflow adds the approval. `TraceSink` keeps each in `Knos_Iris_Data.Span` with its session id.

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

Each Verdict carries input tokens, output tokens and cost in US dollars, from the provider's own usage. In replay mode the
recorded usage is shown, and a rules decision shows 0. A table across the four providers needs a key for each; the
numbers will be added from live runs.

## Building with IRIS Agentic Dev

The classes were written as UDL files and compiled into a running build 154 container with one script
(`iris/scripts/compile-probe.sh`), so a change reaches the production without a rebuild.
