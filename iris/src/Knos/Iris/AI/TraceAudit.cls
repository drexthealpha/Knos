/// AI Hub's audit hook (DPI-I-689): each tool call the agent makes becomes a Span in the decision's own session.
Class Knos.Iris.AI.TraceAudit Extends %AI.Policy.Audit
{
Method %LogExecution(call As %DynamicObject, metadata As %DynamicObject, result As %DynamicObject, duration As %Integer, status As %Status) As %Status
{
    set s = ##class(Knos.Iris.Data.Span).%New()
    set s.Kind = "tool", s.Name = $select($isobject(call):call.name, 1:"tool"), s.Ms = duration
    set s.InputJSON = $select($isobject(call):call.%ToJSON(), 1:""), s.OutputJSON = $select($isobject(result):result.%ToJSON(), 1:"")
    return s.%Save()
}

/// The same span for a tool call made outside AI Hub's own loop (the stub provider of the tests)
ClassMethod Tool(name As %String, in As %String, out As %String, ms As %Integer = 0) As %Status
{
    set s = ##class(Knos.Iris.Data.Span).%New()
    set s.Kind = "tool", s.Name = name, s.Ms = ms, s.InputJSON = $extract(in, 1, 20000), s.OutputJSON = $extract(out, 1, 20000)
    return s.%Save()
}
}
