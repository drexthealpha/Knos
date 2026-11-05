/// /api/knos: health, lock a brief, send proof, read a decision's trace.
Class Knos.Iris.REST.Api Extends %CSP.REST
{
Parameter CONTENTTYPE = "application/json";
Parameter CHARSET = "utf-8";

/// A user who may only read the KNOS database (the online demo's user, Knos.Iris.Setup.DemoUser) reads every route
/// and is refused on every POST: it cannot lock a brief, send proof or answer a task
ClassMethod OnPreDispatch(pUrl As %String, pMethod As %String, ByRef pContinue As %Boolean) As %Status
{
    if (pMethod = "POST") && '$system.Security.Check("%DB_"_$namespace, "WRITE") {
        set pContinue = 0, %response.Status = 403
        write {"error": "this user may read only: it cannot lock a brief, send proof or answer a task"}.%ToJSON()
    }
    return $$$OK
}

XData UrlMap [ XMLNamespace = "http://www.intersystems.com/urlmap" ]
{
<Routes>
<Route Url="/health" Method="GET" Call="Health"/>
<Route Url="/brief" Method="POST" Call="Brief"/>
<Route Url="/proof" Method="POST" Call="Proof"/>
<Route Url="/webhook" Method="POST" Call="Webhook"/>
<Route Url="/traces/:s" Method="GET" Call="Traces"/>
<Route Url="/decisions" Method="GET" Call="Decisions"/>
<Route Url="/tasks" Method="GET" Call="Tasks"/>
<Route Url="/tasks/:id" Method="POST" Call="Answer"/>
<Route Url="/ui" Method="GET" Call="UI"/>
<Route Url="/aihub/:f" Method="GET" Call="AIHub"/>
</Routes>
}

ClassMethod Health() As %Status
{
    set prod = "", state = 0
    do ##class(Ens.Director).GetProductionStatus(.prod, .state)
    set mode = $select($system.Util.GetEnviron("KNOS_AI_MODE")="live" && ($system.Util.GetEnviron("ANTHROPIC_API_KEY")'=""):"live", $system.Util.GetEnviron("KNOS_AI_MODE")="local":"local", 1:"replay")
    set out = {"production": ($case(state, 1:"Running", 2:"Stopped", 3:"Suspended", 4:"Troubled", :"Not running")), "name": (prod),
      "agent": (mode), "provider": ($select(mode="local":"openai (ollama)", 1:$system.Util.GetEnviron("KNOS_LLM_PROVIDER"))), "model": ($select(mode="local":##class(Knos.Iris.AI.Referee).LocalModel(), 1:"")), "fhir": (..Fhir()), "java": (..Java()), "vector": (..Vector()), "embedding": (##class(Knos.Iris.Py.Embed).Model())}
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

/// The request body exactly as sent, for its signature
ClassMethod Raw() As %String
{
    if '$isobject(%request.Content) return ""
    do %request.Content.Rewind()
    return %request.Content.Read(3641144)   // the longest string IRIS holds
}

/// GitHub's own check_run webhook: signed with X-Hub-Signature-256 under KNOS_WEBHOOK_SECRET, else 401. The brief is
/// the one locked for the event's repository (github:<owner>/<repo>).
ClassMethod Webhook() As %Status
{
    set raw = ..Raw()
    if '##class(Knos.Iris.Py.Verdict).WebhookSigned(raw, $get(%request.CgiEnvs("HTTP_X_HUB_SIGNATURE_256"))) return ..Unsigned()
    set event = {}.%FromJSON(raw)
    if '$isobject(event."check_run") { set %response.Status = 422  write {"error": "only check_run events are proof"}.%ToJSON()  return $$$OK }
    set proof = {"id": ("github:"_$zconvert(event.repository."full_name", "L")), "kind": "checkrun", "ref": (event."check_run"."html_url"), "payload": (event)}
    return ..Run(proof)
}

/// 401 for a check run that does not carry a valid signature
ClassMethod Unsigned() As %Status
{
    set %response.Status = 401
    write {"error": "a check run is proof only with a valid X-Hub-Signature-256 (HMAC-SHA256 of the body under KNOS_WEBHOOK_SECRET)"}.%ToJSON()
    return $$$OK
}

/// POST /proof: a check run must be signed like a GitHub webhook (X-Hub-Signature-256 over this exact body); a lab
/// result or a referee verdict is checked in the decision itself
ClassMethod Proof() As %Status
{
    set raw = ..Raw()
    set body = {}.%FromJSON(raw)
    if body.kind = "checkrun", '##class(Knos.Iris.Py.Verdict).WebhookSigned(raw, $get(%request.CgiEnvs("HTTP_X_HUB_SIGNATURE_256"))) return ..Unsigned()
    return ..Run(body)
}

ClassMethod Run(body As %DynamicObject) As %Status
{
    set m = ##class(Knos.Iris.Msg.Proof).%New(), m.BriefId = body.id, m.Kind = body.kind, m.SourceRef = body.ref
    set b = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(body.id)
    set m.BriefJSON = $select($isobject(body.brief):body.brief.%ToJSON(), $isobject(b):b.BriefJSON, 1:"{}")
    // the amount is the one locked with the brief; an amount_usdc in the request is ignored
    set m.AmountUSDC = $select($isobject(b):b.AmountUSDC, 1:0)
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

/// The 50 latest decisions, newest first
/// One AI Hub feature, run live: skill, policy, mcp, rag, stats or workflow (Knos.Iris.AI.Hub)
ClassMethod AIHub(f As %String) As %Status
{
    set out = ##class(Knos.Iris.AI.Hub).Demo(f)
    set:'out.ok %response.Status = $select(out.error [ "one of skill":404, 1:500)
    write out.%ToJSON()
    return $$$OK
}

ClassMethod Decisions() As %Status
{
    set out = []
    // "At" is quoted: AT is an SQL reserved word
    set rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT TOP 50 SessionId, BriefId, Kind, Decision, Gate, Outcome, Confidence, ""At"" AS DecidedAt FROM Knos_Iris_Data.Decision ORDER BY ID DESC")
    if rs.%SQLCODE < 0 return ..Fail($$$ERROR($$$SQLError, rs.%SQLCODE, rs.%Message))
    while rs.%Next() {
        do out.%Push({"session": (+rs.SessionId), "brief": (rs.BriefId), "kind": (rs.Kind), "decision": (rs.Decision), "gate": (rs.Gate),
          "outcome": (rs.Outcome), "confidence": (+rs.Confidence), "at": (rs.DecidedAt)})
    }
    write out.%ToJSON()
    return $$$OK
}

/// Workflow tasks for the PayoutApprovers role, open ones first, each with the session it belongs to
ClassMethod Tasks() As %Status
{
    set out = []
    set rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT TOP 20 ID FROM EnsLib_Workflow.TaskResponse WHERE %RoleName = 'PayoutApprovers' ORDER BY ID DESC")
    while rs.%Next() {
        set t = ##class(EnsLib.Workflow.TaskResponse).%OpenId(rs.ID)
        continue:'$isobject(t)
        set req = t.%TaskStatus.Request, sid = ""
        if $isobject(req) &sql(SELECT TOP 1 SessionId INTO :sid FROM Ens.MessageHeader WHERE MessageBodyClassName = 'EnsLib.Workflow.TaskRequest' AND MessageBodyId = :req.%Id())
        do out.%Push({"id": (+rs.ID), "subject": (t.%Subject), "message": ($select($isobject(req):req.%Message, 1:"")), "actions": (t.%Actions),
          "open": (t.%Status '= "Completed"), "status": (t.%Status), "action": (t.%Action), "user": (t.%UserName), "session": (+sid)})
    }
    write out.%ToJSON()
    return $$$OK
}

/// Approve or reject one open task: {"action": "Approve"} or {"action": "Reject"}. JSON only, so a form on another site
/// cannot send it with the browser's saved login
ClassMethod Answer(id As %Integer) As %Status
{
    if $piece(%request.ContentType, ";") '= "application/json" { set %response.Status = 415  write {"error": "send application/json"}.%ToJSON()  return $$$OK }
    set body = {}.%FromJSON(%request.Content), action = body.action
    if '$listfind($listbuild("Approve", "Reject"), action) { set %response.Status = 400  write {"error": "action is Approve or Reject"}.%ToJSON()  return $$$OK }
    set t = ##class(EnsLib.Workflow.TaskResponse).%OpenId(id)
    if '$isobject(t) { set %response.Status = 404  write {"error": "no such task"}.%ToJSON()  return $$$OK }
    if t.%Status = "Completed" { set %response.Status = 409  write {"error": "already answered", "action": (t.%Action)}.%ToJSON()  return $$$OK }
    set sc = t.CompleteTask(action)
    if $$$ISERR(sc) return ..Fail(sc)
    write {"id": (+id), "action": (action)}.%ToJSON()
    return $$$OK
}

/// The dashboard page: decisions, each one's trace, and the approver's inbox, here and without a login at /knos/ (no data in it);
/// every call it makes needs the user and password, which it asks for once and sends as Basic authorization
ClassMethod UI() As %Status
{
    set f = ##class(%Stream.FileCharacter).%New(), f.TranslateTable = "UTF8"
    set sc = f.LinkToFile($system.Util.GetEnviron("KNOS_IRIS_HOME")_"/iris/web/dashboard.html")
    if $$$ISERR(sc) || 'f.Size return ..Fail($$$ERROR($$$GeneralError, "iris/web/dashboard.html not found"))
    set %response.ContentType = "text/html"
    do %response.SetHeader("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
    do f.OutputToDevice()
    return $$$OK
}

ClassMethod Fail(sc As %Status) As %Status
{
    set %response.Status = 500
    write {"error": ($system.Status.GetErrorText(sc))}.%ToJSON()
    return $$$OK
}
}
