/// /api/knos: health, lock a brief, send proof, read a decision's trace.
Class Knos.Iris.REST.Api Extends %CSP.REST
{
Parameter CONTENTTYPE = "application/json";
Parameter CHARSET = "utf-8";

XData UrlMap [ XMLNamespace = "http://www.intersystems.com/urlmap" ]
{
<Routes>
<Route Url="/health" Method="GET" Call="Health"/>
<Route Url="/brief" Method="POST" Call="Brief"/>
<Route Url="/proof" Method="POST" Call="Proof"/>
<Route Url="/traces/:s" Method="GET" Call="Traces"/>
</Routes>
}

ClassMethod Health() As %Status
{
    set prod = "", state = 0
    do ##class(Ens.Director).GetProductionStatus(.prod, .state)
    set mode = $select($system.Util.GetEnviron("KNOS_AI_MODE")="live" && ($system.Util.GetEnviron("ANTHROPIC_API_KEY")'=""):"live", 1:"replay")
    set out = {"production": ($case(state, 1:"Running", 2:"Stopped", 3:"Suspended", 4:"Troubled", :"Not running")), "name": (prod),
      "agent": (mode), "provider": ($system.Util.GetEnviron("KNOS_LLM_PROVIDER")), "fhir": (..Fhir()), "java": (..Java()), "vector": (..Vector())}
    write out.%ToJSON()
    return $$$OK
}

ClassMethod Fhir() As %String
{
    try {
        set strategy = ##class(HS.FHIRServer.API.InteractionsStrategy).GetStrategyForEndpoint("/csp/healthshare/knos/fhir/r4")
        return $select($isobject(strategy):"ok", 1:"no endpoint")
    } catch e { return "error: "_e.Name }
}

ClassMethod Java() As %String
{
    try {
        set gw = $system.external.getJavaGateway()
        return $select($isobject(gw):"ok", 1:"no gateway")
    } catch e { return "error: "_e.Name }
}

ClassMethod Vector() As %String
{
    try {
        set v = ##class(Knos.Iris.Py.Embed).Vector("checkout p95 latency")
        &sql(SELECT VECTOR_COSINE(TO_VECTOR(:v, DOUBLE, 384), TO_VECTOR(:v, DOUBLE, 384)) INTO :s)
        return $select(SQLCODE=0 && (s > 0.99):"ok", 1:"SQLCODE "_SQLCODE)
    } catch e { return "error: "_e.Name }
}

ClassMethod Brief() As %Status
{
    set body = {}.%FromJSON(%request.Content)
    set m = ##class(Knos.Iris.Msg.Brief).%New(), m.BriefId = body.id, m.BriefJSON = body.brief.%ToJSON(), m.AmountUSDC = +body."amount_usdc"
    set sc = ##class(Ens.Director).CreateBusinessService("BriefIn", .svc)
    if $$$ISERR(sc) return ..Fail(sc)
    set sc = svc.SendRequestSync("BriefLock", m, .r)
    if $$$ISERR(sc) return ..Fail(sc)
    write {"id": (r.BriefId), "ready": (+r.Ready), "criteria_hash": (r.CriteriaHash), "missing": ({}.%FromJSON($select(r.Missing="":"[]",1:r.Missing)))}.%ToJSON()
    return $$$OK
}

ClassMethod Proof() As %Status
{
    set body = {}.%FromJSON(%request.Content)
    set m = ##class(Knos.Iris.Msg.Proof).%New(), m.BriefId = body.id, m.Kind = body.kind, m.SourceRef = body.ref, m.AmountUSDC = +body."amount_usdc"
    set b = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(body.id)
    set m.BriefJSON = $select($isobject(body.brief):body.brief.%ToJSON(), $isobject(b):b.BriefJSON, 1:"{}")
    set:m.AmountUSDC=0&&$isobject(b) m.AmountUSDC = b.AmountUSDC
    set m.PayloadJSON = $select($isobject(body.payload):body.payload.%ToJSON(), 1:body.payload)
    set sc = ##class(Ens.Director).CreateBusinessService("ProofIn", .svc)
    if $$$ISERR(sc) return ..Fail(sc)
    set sc = svc.ProcessInput(m, .d)
    if $$$ISERR(sc) return ..Fail(sc)
    write {"decision": (d.Decision), "gate": (d.Gate), "outcome": (d.Outcome), "confidence": (+d.Confidence), "session": (d.SessionId),
      "milestones": ({}.%FromJSON($select(d.Reason="":"[]",1:d.Reason))),
      "visual_trace": ("http://localhost:52773/csp/healthshare/knos/EnsPortal.VisualTrace.zen?SESSIONID="_d.SessionId)}.%ToJSON()
    return $$$OK
}

ClassMethod Traces(s As %Integer) As %Status
{
    write ##class(Knos.Iris.Trace).Session(s).%ToJSON()
    return $$$OK
}

ClassMethod Fail(sc As %Status) As %Status
{
    set %response.Status = 500
    write {"error": ($system.Status.GetErrorText(sc))}.%ToJSON()
    return $$$OK
}
}
