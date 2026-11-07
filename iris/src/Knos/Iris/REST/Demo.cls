/// /api/knosdemo: the built-in demo, with no sign-in, and only in replay mode (KNOS_AI_MODE unset or replay: no key and
/// no model). The page at /knos/ uses it when it answers: it reads the decisions, the tasks and a trace, answers a task,
/// and sends one of three sample test results (a passing one for $20, a failing one for $20, a passing one for $120
/// that waits for a person). In local or live mode every route answers 403, so a model or a key is never reached
/// without the IRIS user and password.
Class Knos.Iris.REST.Demo Extends Knos.Iris.REST.Api
{

XData UrlMap [ XMLNamespace = "http://www.intersystems.com/urlmap" ]
{
<Routes>
<Route Url="/health" Method="GET" Call="Health"/>
<Route Url="/decisions" Method="GET" Call="Decisions"/>
<Route Url="/tasks" Method="GET" Call="Tasks"/>
<Route Url="/tasks/:id" Method="POST" Call="Answer"/>
<Route Url="/traces/:s" Method="GET" Call="Traces"/>
<Route Url="/aihub/:f" Method="GET" Call="AIHub"/>
<Route Url="/sample/:k" Method="POST" Call="Sample"/>
</Routes>
}

/// Replay mode only: the same rule /api/knos/health uses to name the mode
ClassMethod OnPreDispatch(pUrl As %String, pMethod As %String, ByRef pContinue As %Boolean) As %Status
{
    set mode = $system.Util.GetEnviron("KNOS_AI_MODE")
    if (mode = "local") || (mode = "live") {
        set pContinue = 0, %response.Status = 403
        write {"error": "the built-in demo runs only in replay mode (KNOS_AI_MODE=replay); sign in at /knos/"}.%ToJSON()
    }
    return $$$OK
}

/// One sample test result, end to end: a brief of its own (the code brief, from the fixtures), then its check run.
/// k = pass ($20), fail ($20) or big (a passing one for $120, above the payout threshold: it waits for a person).
ClassMethod Sample(k As %String) As %Status
{
    if '$listfind($listbuild("pass", "fail", "big"), k) { set %response.Status = 404  write {"error": "a sample is pass, fail or big"}.%ToJSON()  return $$$OK }
    set home = ##class(Knos.Iris.Util).Home()_"iris/fixtures/"
    set run = $zdatetime($ztimestamp, -2)_$piece($ztimestamp, ".", 2)
    set id = "github:example/shop-"_k_"-"_run
    // the brief keeps the repository the check run comes from, so the repository check still holds
    set brief = {}.%FromJSON(..Read(home_"briefs/code.json")), brief.repository = "example/shop"
    set m = ##class(Knos.Iris.Msg.Brief).%New(), m.BriefId = id, m.BriefJSON = brief.%ToJSON(), m.AmountUSDC = $select(k = "big":120, 1:20)
    set sc = ##class(Ens.Director).CreateBusinessService("BriefIn", .svc)
    if $$$ISERR(sc) return ..Fail(sc)
    set sc = svc.SendRequestSync("BriefLock", m, .r)
    if $$$ISERR(sc) return ..Fail(sc)
    // a check run is proof once: each sample gets its own run id
    set payload = $replace(..Read(home_"checkruns/"_$select(k = "fail":"fail", 1:"pass")_".json"), "4242004", run)
    return ..Run({"id": (id), "kind": "checkrun", "payload": ({}.%FromJSON(payload))})
}

ClassMethod Read(path As %String) As %String
{
    set f = ##class(%Stream.FileCharacter).%New(), f.TranslateTable = "UTF8"
    $$$ThrowOnError(f.LinkToFile(path))
    return f.Read(3641144)
}

}
