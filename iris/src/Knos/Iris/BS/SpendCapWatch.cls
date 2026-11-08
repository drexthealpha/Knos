/// The model's spend, watched: every CallInterval seconds, an alert (Ens.Alert) the first time the calls or the dollars
/// reach WarnPercent of the hard cap (Knos.Iris.AI.Budget), and again at 100%, before any call is refused.
Class Knos.Iris.BS.SpendCapWatch Extends Ens.BusinessService
{
Parameter ADAPTER = "Ens.InboundAdapter";

/// the share of the cap that raises the first alert
Property WarnPercent As %Integer [ InitialExpression = 80 ];

Parameter SETTINGS = "WarnPercent:Basic";

Method OnProcessInput(pInput As %RegisteredObject, Output pOutput As %RegisteredObject) As %Status
{
    set calls = +$get(^Knos.LLM("calls")), usd = +$get(^Knos.LLM("usd"))
    set pct = $select(calls*100/##class(Knos.Iris.AI.Budget).MaxCalls() > (usd*100/##class(Knos.Iris.AI.Budget).MaxUSD()):calls*100/##class(Knos.Iris.AI.Budget).MaxCalls(), 1:usd*100/##class(Knos.Iris.AI.Budget).MaxUSD())
    set level = $select(pct >= 100:100, pct >= ..WarnPercent:..WarnPercent, 1:0)
    if level && (level > +$get(^Knos.LLM("warned"))) {
        set ^Knos.LLM("warned") = level
        set text = "Model spend at "_$fnumber(pct, "", 0)_"% of its cap: "_calls_" of "_##class(Knos.Iris.AI.Budget).MaxCalls()_" calls, "_$fnumber(usd, "", 4)_" of "_$fnumber(##class(Knos.Iris.AI.Budget).MaxUSD(), "", 2)_" USD"
        return ..SendAlert(##class(Ens.AlertRequest).%New($listbuild(..%ConfigName, text)))
    }
    return $$$OK
}
}
