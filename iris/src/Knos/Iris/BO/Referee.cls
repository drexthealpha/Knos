/// The referee: does the proof meet each milestone of the locked brief? In live mode the AI Hub agent
/// (Knos.Iris.AI.Referee) answers in the decision contract; in replay mode a recorded live answer, else the rules
/// referee (knos_iris.referee), which reads only structured fields. It has no tool that moves money.
Class Knos.Iris.BO.Referee Extends Ens.BusinessOperation
{
Property Mode As %String [ InitialExpression = {$system.Util.GetEnviron("KNOS_AI_MODE")} ];
Parameter SETTINGS = "Mode:Basic";

Method Decide(pRequest As Knos.Iris.Msg.Proof, Output pResponse As Knos.Iris.Msg.Verdict) As %Status
{
    set t0 = $zhorolog
    set hash = ##class(Knos.Iris.Py.Ready).Hash(pRequest.BriefJSON)
    set mode = $select($get(^Knos.LLM("mode"), ..Mode)="live":"live", 1:"replay")   // ^Knos.LLM("mode"): the tests' override
    set out = ""
    set refused = ""
    if mode = "live" { set out = ##class(Knos.Iris.AI.Referee).Ask(pRequest, hash, .refused) set:out="" mode = "replay" }
    if refused '= "" {
        // live mode was asked for and cannot ask a model: said in one plain sentence, decided by nobody, sent to a person
        set out = {"criteria_hash": (hash), "decision": "insufficient", "milestones": [], "confidence": 0, "model": ("refused: "_refused), "referee": "nobody (live mode refused)"}.%ToJSON()
        set mode = "live refused"
    }
    if out = "" {
        set file = ##class(Knos.Iris.Util).Home()_"iris/fixtures/replay/"_hash_"-"_##class(Knos.Iris.Util).Sha(pRequest.PayloadJSON)_".json"
        if ##class(%File).Exists(file) {
            set f = ##class(%Stream.FileCharacter).%New(), f.Filename = file, out = f.Read(1000000)
        } else {
            set out = ##class(Knos.Iris.Py.Verdict).Decide(pRequest.BriefJSON, pRequest.Kind, pRequest.PayloadJSON, hash)
        }
    }
    set v = {}.%FromJSON(out)
    set pResponse = ##class(Knos.Iris.Msg.Verdict).%New()
    set pResponse.Decision = v.decision, pResponse.Confidence = v.confidence, pResponse.CriteriaHash = v."criteria_hash"
    set pResponse.MilestonesJSON = v.milestones.%ToJSON(), pResponse.Model = v.model, pResponse.Mode = mode
    set pResponse.InTok = +v."input_tokens", pResponse.OutTok = +v."output_tokens", pResponse.CostUSD = +v."cost_usd"
    do ..Span("llm", "referee", pRequest.PayloadJSON, out, v.confidence, $zhorolog - t0, pResponse.InTok + pResponse.OutTok, pResponse.CostUSD, v.model)
    return $$$OK
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
