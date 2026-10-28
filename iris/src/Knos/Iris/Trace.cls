/// The trace as a Langfuse-style flat view: trace, span, parent, type, name, model, tokens, cost, latency, score, start.
Class Knos.Iris.Trace
{
/// The spans of one session, nested under the decision, as JSON
ClassMethod Session(sid As %Integer) As %DynamicObject
{
    set out = {"session": (sid), "visual_trace": ("/csp/healthshare/knos/EnsPortal.VisualTrace.zen?SESSIONID="_sid), "spans": []}
    set rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT SpanId, ParentId, Kind, Name, Model, Tokens, CostUSD, Ms, Score, StartedAt, InputJSON, OutputJSON FROM Knos_Iris_Data.Span WHERE SessionId = ? ORDER BY ID", sid)
    while rs.%Next() {
        do out.spans.%Push({"span_id": (rs.SpanId), "parent_id": (rs.ParentId), "type": (rs.Kind), "name": (rs.Name), "model": (rs.Model),
          "tokens": (+rs.Tokens), "cost_usd": (+rs.CostUSD), "latency_ms": (+rs.Ms), "score": (rs.Score), "started_at": (rs.StartedAt),
          "input": (rs.InputJSON), "output": (rs.OutputJSON)})
    }
    set rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT ID, SessionId, TimeCreated, SourceConfigName, TargetConfigName, MessageBodyClassName FROM Ens.MessageHeader WHERE SessionId = ? ORDER BY ID", sid)
    set out.messages = []
    while rs.%Next() { do out.messages.%Push({"id": (rs.ID), "at": (rs.TimeCreated), "from": (rs.SourceConfigName), "to": (rs.TargetConfigName), "body": (rs.MessageBodyClassName)}) }
    return out
}
}
