/// Check runs as they land (Knos.Iris.Adapter.CheckRunInbound): each one is proof for the brief its repository
/// and check are locked under (BriefId "github:<owner>/<repo>"), decided like any other.
Class Knos.Iris.BS.CheckRunPoller Extends Ens.BusinessService
{
Parameter ADAPTER = "Knos.Iris.Adapter.CheckRunInbound";

Method OnProcessInput(pInput As Ens.StringContainer, Output pOutput As %RegisteredObject) As %Status
{
    set text = pInput.StringValue, body = {}.%FromJSON(text)
    set id = "github:"_body.repository."full_name"
    set brief = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(id)
    if '$isobject(brief) return $$$ERROR($$$GeneralError, "no brief is locked for "_id)
    set m = ##class(Knos.Iris.Msg.Proof).%New()
    set m.BriefId = id, m.BriefJSON = brief.BriefJSON, m.Kind = "checkrun", m.PayloadJSON = text
    set m.SourceRef = body."check_run"."html_url", m.AmountUSDC = brief.AmountUSDC
    return ..SendRequestAsync("ProofDecision", m)
}
}
