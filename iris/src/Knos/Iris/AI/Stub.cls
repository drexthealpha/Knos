/// The stub provider (KNOS_LLM_PROVIDER=stub): what a model does in live mode, with no model and no key, so the live
/// path can be tested anywhere. It calls the agent's own tools in order (the brief, the evidence for the proof's
/// kind, the nearest criteria), each call written as a tool span by the audit class, then answers in the decision
/// contract with the rules referee's decision and the usage it would bill (KNOS_LLM_STUB_USD per call, default 0).
Class Knos.Iris.AI.Stub Extends %RegisteredObject
{

ClassMethod Decide(briefJSON As %String, kind As %String, payload As %String, hash As %String) As %String
{
    set t = $zhorolog
    set b = {}.%FromJSON(briefJSON)
    set brief = ##class(Knos.Iris.AI.RefereeTools).GetBrief($select(b.id'="":b.id, 1:hash))
    do ##class(Knos.Iris.AI.TraceAudit).Tool("GetBrief", "{""hash"":"""_hash_"""}", brief, ($zhorolog - t) * 1000)
    if kind = "checkrun" { set ev = ##class(Knos.Iris.AI.RefereeTools).GetCheckRun(payload), tool = "GetCheckRun" }
    elseif kind = "verdict" { set ev = ##class(Knos.Iris.AI.RefereeTools).GetVerdict(payload), tool = "GetVerdict" }
    else { set ev = ##class(Knos.Iris.AI.RefereeTools).GetObservation(kind, payload), tool = "GetObservation" }
    do ##class(Knos.Iris.AI.TraceAudit).Tool(tool, "{""kind"":"""_kind_"""}", ev, ($zhorolog - t) * 1000)
    set near = ##class(Knos.Iris.AI.RefereeTools).SearchCriteria(hash, ev)
    do ##class(Knos.Iris.AI.TraceAudit).Tool("SearchCriteria", "{""hash"":"""_hash_"""}", near, ($zhorolog - t) * 1000)
    set out = {}.%FromJSON(##class(Knos.Iris.Py.Verdict).Decide(briefJSON, kind, payload, hash))
    set usd = $system.Util.GetEnviron("KNOS_LLM_STUB_USD")
    set out.model = "stub provider", out.referee = "AI Hub agent (stub provider)", out."input_tokens" = $length(briefJSON) + $length(payload) \ 4
    set out."output_tokens" = $length(out.%ToJSON()) \ 4, out."cost_usd" = $select(usd?1.N.1(1"."1.N):+usd, 1:0), out.tools = 3
    return out.%ToJSON()
}

}
