/// The referee: does the proof meet each milestone of the locked brief? In live mode the AI Hub agent
/// (Knos.Iris.AI.Referee) answers in the decision contract; in replay mode the rules referee, with no model
/// (knos_iris.referee), which reads only structured fields. It has no tool that moves money.
Class Knos.Iris.BO.Referee Extends Ens.BusinessOperation
{
Property Mode As %String [ InitialExpression = {$system.Util.GetEnviron("KNOS_AI_MODE")} ];
Parameter SETTINGS = "Mode:Basic";

Method Decide(pRequest As Knos.Iris.Msg.Proof, Output pResponse As Knos.Iris.Msg.Verdict) As %Status
{
    set t0 = $zhorolog
    // every tool span written while this decision is being refereed carries its session (Knos.Iris.AI.TraceAudit)
    set ^||Knos.TraceSession = ..%SessionId
    set hash = ##class(Knos.Iris.Py.Ready).Hash(pRequest.BriefJSON)
    set mode = $case($get(^Knos.LLM("mode"), ..Mode), "live":"live", "local":"local", :"replay")   // ^Knos.LLM("mode"): the tests' override
    set out = ""
    set refused = ""
    // the online demo's limit for this sample (Knos.Iris.REST.Demo.Sample): the fixed rule decides, and says why
    set fixed = $get(^Knos.Demo("fixed", pRequest.BriefId))
    if fixed '= "" { set mode = "replay" }
    kill %knosAskWhy
    set asked = mode
    if (mode = "live") || (mode = "local") { set out = ##class(Knos.Iris.AI.Referee).Ask(pRequest, hash, .refused) set:out="" mode = "replay" }
    // replay mode only: a sample of the one-command edition replays the AI Hub agent's answer recorded in the online
    // demo; a live or local run that got no answer never does, so a recorded answer never stands in for a live one
    if (out = "") && (asked = "replay") && (fixed = "") { set out = ..Recorded($get(^Knos.Demo("recorded", pRequest.BriefId)), hash, pRequest.PayloadJSON) }
    // the model was asked and did not answer: the fixed rule decides, and the label says why (not "no model key set")
    if (out = "") && (refused = "") && (fixed = "") && ($get(%knosAskWhy) '= "") { set fixed = %knosAskWhy }
    // a model's verdict can only be made stricter: the rules referee reads the same proof's structured fields, and
    // when it says not met or insufficient where the model says more, its answer stands (met < insufficient < not met)
    if (out '= "") && (refused = "") { set out = ..Stricter(out, ##class(Knos.Iris.Py.Verdict).Decide(pRequest.BriefJSON, pRequest.Kind, pRequest.PayloadJSON, hash)) }
    if refused '= "" {
        // live mode was asked for and cannot ask a model: said in one plain sentence, decided by nobody, sent to a person
        set out = {"criteria_hash": (hash), "decision": "insufficient", "milestones": [], "confidence": 0, "model": ("refused: "_refused), "referee": "nobody (live mode refused)"}.%ToJSON()
        set mode = "live refused"
    }
    if out = "" {
        // replay mode: the rules referee decides, with no model
        $$$LOGINFO("replay: the rules referee decides, with no model")
        set out = ##class(Knos.Iris.Py.Verdict).Decide(pRequest.BriefJSON, pRequest.Kind, pRequest.PayloadJSON, hash)
    }
    set v = {}.%FromJSON(out)
    if fixed '= "" { set v.model = "rules referee: "_fixed_", so the fixed rule decided this sample", v.referee = v.model, out = v.%ToJSON() }
    set pResponse = ##class(Knos.Iris.Msg.Verdict).%New()
    set pResponse.Decision = v.decision, pResponse.Confidence = v.confidence, pResponse.CriteriaHash = v."criteria_hash"
    set pResponse.MilestonesJSON = v.milestones.%ToJSON(), pResponse.Model = v.model, pResponse.Mode = mode
    set pResponse.InTok = +v."input_tokens", pResponse.OutTok = +v."output_tokens", pResponse.CostUSD = +v."cost_usd"
    do ..Span("llm", "referee", pRequest.PayloadJSON, out, v.confidence, $zhorolog - t0, pResponse.InTok + pResponse.OutTok, pResponse.CostUSD, v.model)
    kill ^||Knos.TraceSession
    return $$$OK
}

/// The model's answer, or the rules referee's where that one is stricter; the model's name and tokens are kept
ClassMethod Stricter(model As %String, rules As %String) As %String
{
    set m = {}.%FromJSON(model), r = {}.%FromJSON(rules)
    set rank = $listbuild("met", "insufficient", "not_met")
    return:($listfind(rank, r.decision) <= $listfind(rank, m.decision)) model
    set m.decision = r.decision, m.milestones = r.milestones
    set:+r.confidence<+m.confidence m.confidence = r.confidence
    set m.model = m.model_" (made stricter by the rules referee)"
    return m.%ToJSON()
}

/// The AI Hub agent's answer to sample k (pass, fail or big), recorded unchanged in the online demo
/// (iris/fixtures/recorded/k.json), for this run: "" unless it answers this very brief (the same criteria hash). Each
/// sample run has its own check run id, so the answer cites this run's; no tokens or cost, since no model is asked.
ClassMethod Recorded(k As %String, hash As %String, payload As %String) As %String
{
    return:'$listfind($listbuild("pass", "fail", "big"), k) ""
    set path = ##class(Knos.Iris.Util).Home()_"iris/fixtures/recorded/"_k_".json"
    return:'##class(%File).Exists(path) ""
    try {
        set f = ##class(%Stream.FileCharacter).%New(), f.TranslateTable = "UTF8"
        $$$ThrowOnError(f.LinkToFile(path))
        set rec = {}.%FromJSON(f), v = rec.answer
        return:v."criteria_hash"'=hash ""
        set id = {}.%FromJSON(payload).%Get("check_run").%Get("id", "", "string")
        set it = v.milestones.%GetIterator()
        while it.%GetNext(, .m) { set m.evidence = [("checkrun:"_id)] }
        set v.model = rec.model_" via AI Hub, its answer to this sample recorded "_rec."recorded_at"_" in the online demo, replayed: no model asked"
        set v."input_tokens" = 0, v."output_tokens" = 0, v."cost_usd" = 0
        return v.%ToJSON()
    } catch e {
        $$$LOGWARNING("the recorded answer for "_k_" was not read: "_e.DisplayString())
    }
    return ""
}

/// One step of the decision as a Span message in this session (DPI-I-689)
Method Span(kind, name, in, out, score, secs, tokens, cost, model) As %Status
{
    set s = ##class(Knos.Iris.Msg.Span).%New()
    set s.Kind = kind, s.Name = name, s.InputJSON = $extract(in, 1, 20000), s.OutputJSON = $extract(out, 1, 20000)
    set s.Score = score, s.Ms = secs * 1000, s.Tokens = tokens, s.CostUSD = cost, s.Model = model
    set s.SpanId = ##class(Knos.Iris.Util).Sha($zhorolog_name_$random(1E9)), s.TraceId = ..%SessionId
    return ..SendRequestAsync("TraceSink", s)
}

XData MessageMap
{
<MapItems>
<MapItem MessageType="Knos.Iris.Msg.Proof"><Method>Decide</Method></MapItem>
</MapItems>
}
}
