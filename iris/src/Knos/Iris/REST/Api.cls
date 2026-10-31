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
      "agent": (mode), "provider": ($system.Util.GetEnviron("KNOS_LLM_PROVIDER")), "fhir": (..Fhir()), "java": (..Java()), "vector": (..Vector()), "embedding": (##class(Knos.Iris.Py.Embed).Model())}
    write out.%ToJSON()
    return $$$OK
}

ClassMethod Fhir() As %String
{
    if '$system.Util.GetEnviron("KNOS_FHIR") return "off"
    try {
        set strategy = ##class(HS.FHIRServer.API.InteractionsStrategy).GetStrategyForEndpoint("/csp/healthshare/knos/fhir/r4")
        return $select($isobject(strategy):"ok", 1:"no endpoint")
    } catch e { return "error: "_e.Name }
}

ClassMethod Java() As %String
{
    try {
        set gw = $system.external.getJavaGateway()
        return:$isobject(gw) "ok"
    } catch e { set err = "error: "_e.Name }
    // a JVM the production started while IRIS was still busy starting (build 154, a slow disk) can keep port 53272
    // open and never answer, and stopServer leaves it running: end it, then start %Java Server once more. One caller
    // at a time and at most once in 5 minutes, so the health check's own polls never end a JVM another just started.
    lock +^Knos.Iris.JavaRestart:0
    else  return err
    try {
        if $zdatetime($ztimestamp, -2) - $get(^Knos.Iris.JavaRestart) < 300 { lock -^Knos.Iris.JavaRestart  return err }
        set ^Knos.Iris.JavaRestart = $zdatetime($ztimestamp, -2)
        do $zf(-100, "", "pkill", "-KILL", "-f", "com.intersystems.gateway.JavaGateway")
        do $system.external.stopServer("%Java Server")
        do $system.external.startServer("%Java Server")
        set gw = $system.external.getJavaGateway(), err = $select($isobject(gw):"ok", 1:"no gateway")
    } catch e { set err = "error: "_e.Name }
    lock -^Knos.Iris.JavaRestart
    return err
}

ClassMethod Vector() As %String
{
    try {
        set v = ##class(Knos.Iris.Py.Embed).Query("checkout p95 latency")
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
    // proof from another repository than the locked brief's is refused before anything decides on it
    set why = ##class(Knos.Iris.Py.Verdict).RepoMismatch(body.id, $select($isobject(b):b.BriefJSON, 1:"{}"), body.%ToJSON())
    if why '= "" { set %response.Status = 409  write {"error": (why)}.%ToJSON()  return $$$OK }
    set m.PayloadJSON = $select($isobject(body.payload):body.payload.%ToJSON(), 1:body.payload)
    set sc = ##class(Ens.Director).CreateBusinessService("ProofIn", .svc)
    if $$$ISERR(sc) return ..Fail(sc)
    set sc = svc.ProcessInput(m, .d)
    if $$$ISERR(sc) return ..Fail(sc)
    write {"decision": (d.Decision), "gate": (d.Gate), "outcome": (d.Outcome), "confidence": (+d.Confidence), "session": (d.SessionId), "referee": (d.Referee),
      "milestones": ({}.%FromJSON($select(d.Reason="":"[]",1:d.Reason))),
      "visual_trace": (..Portal()_"/csp/healthshare/knos/EnsPortal.VisualTrace.zen?SESSIONID="_d.SessionId)}.%ToJSON()
    return $$$OK
}

/// The Management Portal's base URL for links: KNOS_IRIS_PORTAL when set (a gateway or a host in front of IRIS), else
/// the scheme and Host header this request came in on, so the link works from wherever the caller reached IRIS
ClassMethod Portal() As %String
{
    set p = $system.Util.GetEnviron("KNOS_IRIS_PORTAL")
    if p = "" {
        // only a host name or address and a port: any other character is dropped
        set h = $get(%request.CgiEnvs("HTTP_HOST"))
        set h = $translate(h, $translate(h, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:-[]"))
        set:h="" h = "localhost:52773"
        set p = $select(%request.Secure:"https", 1:"http")_"://"_h
    }
    return $zstrip(p, ">", "/")
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
