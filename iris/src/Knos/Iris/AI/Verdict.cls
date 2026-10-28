/// The decision contract, checked: AI Hub has no structured-output setting, so the reply is validated here.
Class Knos.Iris.AI.Verdict
{
ClassMethod Parse(text As %String, hash As %String) As %String
{
    try {
        set j = {}.%FromJSON($zstrip(text, "<>W"))
        if (j.decision '= "met") && (j.decision '= "not_met") && (j.decision '= "insufficient") return ""
        if j."criteria_hash" '= hash return ""
        if '$isobject(j.milestones) return ""
        return j.%ToJSON()
    } catch {
        return ""
    }
}
}
