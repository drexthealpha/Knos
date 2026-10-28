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

XData MessageMap
{
<MapItems>
<MapItem MessageType="Knos.Iris.Msg.Span"><Method>Keep</Method></MapItem>
</MapItems>
}
}
