/// One step of a decision as an interoperability message (DPI-I-689): every prompt, tool call, rule and approval
/// shows in Visual Trace in the decision's own session.
Class Knos.Iris.Msg.Span Extends (Ens.Request, %JSON.Adaptor)
{
Property TraceId As %String(MAXLEN = 64);
Property SpanId As %String(MAXLEN = 64);
Property ParentId As %String(MAXLEN = 64);
Property Kind As %String(VALUELIST = ",llm,tool,rag,policy,rule,workflow,chain");
Property Name As %String(MAXLEN = 128);
Property InputJSON As %String(MAXLEN = "");
Property OutputJSON As %String(MAXLEN = "");
Property Score As %Numeric(SCALE = 4);
Property Ms As %Integer;
Property Tokens As %Integer;
Property CostUSD As %Numeric(SCALE = 6);
Property Model As %String(MAXLEN = 128);
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
