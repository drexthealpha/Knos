/// Every Span message of a decision, kept in Knos_Iris_Data.Span with its session (the SQL view and /traces read it).
Class Knos.Iris.BO.TraceSink Extends Ens.BusinessOperation
{
Method Keep(pRequest As Knos.Iris.Msg.Span, Output pResponse As Ens.Response) As %Status
{
    set r = ##class(Knos.Iris.Data.Span).%New()
    set r.SessionId = ..%SessionId, r.TraceId = pRequest.TraceId, r.SpanId = pRequest.SpanId, r.ParentId = pRequest.ParentId
    set r.Kind = pRequest.Kind, r.Name = pRequest.Name, r.InputJSON = pRequest.InputJSON, r.OutputJSON = pRequest.OutputJSON
    set r.Score = pRequest.Score, r.Ms = pRequest.Ms, r.Tokens = pRequest.Tokens, r.CostUSD = pRequest.CostUSD, r.Model = pRequest.Model
    return r.%Save()
}

/// A verdict reached without the referee (the brief no longer matches its lock), kept as a span like the referee's own
Method KeepVerdict(pRequest As Knos.Iris.Msg.Verdict, Output pResponse As Ens.Response) As %Status
{
    set r = ##class(Knos.Iris.Data.Span).%New()
    set r.SessionId = ..%SessionId, r.Kind = "verdict", r.Name = "verdict without the referee", r.Model = pRequest.Model
    set r.OutputJSON = {"decision": (pRequest.Decision), "confidence": (+pRequest.Confidence)}.%ToJSON()
    return r.%Save()
}

/// The decision of a proof that came in with no caller waiting for the reply (a file adapter's or poller's), so the
/// session holds its Decision message all the same; nothing is stored, the message itself is the record
Method KeepDecision(pRequest As Knos.Iris.Msg.Decision, Output pResponse As Ens.Response) As %Status
{
    return $$$OK
}

XData MessageMap
{
<MapItems>
<MapItem MessageType="Knos.Iris.Msg.Span"><Method>Keep</Method></MapItem>
<MapItem MessageType="Knos.Iris.Msg.Verdict"><Method>KeepVerdict</Method></MapItem>
<MapItem MessageType="Knos.Iris.Msg.Decision"><Method>KeepDecision</Method></MapItem>
</MapItems>
}
}
