/// The decision contract, checked: AI Hub has no structured-output setting, so the reply is validated here.
Class Knos.Iris.AI.Verdict
{
ClassMethod Parse(text As %String, hash As %String) As %String
{
    try {
        // the object itself: a model may wrap it in a code fence or a sentence; everything else is still checked
        set t = $zstrip(text, "<>W"), a = $find(t, "{"), z = $length(t)
        while (z > 0) && ($extract(t, z) '= "}") { set z = z - 1 }
        set:((a > 1) && (z >= a)) t = $extract(t, a - 1, z)
        set j = {}.%FromJSON(t)
        if (j.decision '= "met") && (j.decision '= "not_met") && (j.decision '= "insufficient") return ""
        if j."criteria_hash" '= hash return ""
        if '$isobject(j.milestones) return ""
        return j.%ToJSON()
    } catch {
        return ""
    }
}
}
