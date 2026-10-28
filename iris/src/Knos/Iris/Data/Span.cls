/// The trace: one row per Span message (Knos.Iris.BO.TraceSink), read by the SQL view and /api/knos/traces.
Class Knos.Iris.Data.Span Extends %Persistent
{
Property SessionId As %Integer;
Property TraceId As %String(MAXLEN = 64);
Property SpanId As %String(MAXLEN = 64);
Property ParentId As %String(MAXLEN = 64);
Property Kind As %String(MAXLEN = 16);
Property Name As %String(MAXLEN = 128);
Property InputJSON As %String(MAXLEN = "");
Property OutputJSON As %String(MAXLEN = "");
Property Score As %Numeric(SCALE = 4);
Property Ms As %Integer;
Property Tokens As %Integer;
Property CostUSD As %Numeric(SCALE = 6);
Property Model As %String(MAXLEN = 128);
Property StartedAt As %TimeStamp [ InitialExpression = {$ZDATETIME($ZTIMESTAMP, 3)} ];
Index SessionIdx On SessionId;
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
