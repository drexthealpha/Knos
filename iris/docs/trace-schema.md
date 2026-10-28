# The trace schema

`Knos_Iris_Data.Span` (one row per `Knos.Iris.Msg.Span`) against Langfuse's trace and observation model.

| Column | Meaning | Langfuse field |
|---|---|---|
| SessionId | the interoperability session of the decision | trace.id |
| TraceId | the same session, as the span carries it | observation.traceId |
| SpanId | this step | observation.id |
| ParentId | the step it belongs to | observation.parentObservationId |
| Kind | llm, tool, rag, policy, rule, workflow, chain | observation.type (GENERATION for llm, SPAN otherwise) |
| Name | the item or tool | observation.name |
| Model | the model that answered | observation.model |
| InputJSON, OutputJSON | what went in and out | observation.input, observation.output |
| Tokens | input and output tokens | observation.usage.total |
| CostUSD | the provider's usage times its price | observation.calculatedTotalCost |
| Ms | latency in milliseconds | derived from startTime and endTime |
| Score | confidence of the step | score.value |
| StartedAt | when it began | observation.startTime |
