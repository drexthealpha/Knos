/// Every decision, for the trace view and the precedent search.
Class Knos.Iris.Data.Decision Extends %Persistent
{
Property SessionId As %Integer;
Property BriefId As %String(MAXLEN = 128);
Property Kind As %String(MAXLEN = 16);
Property Decision As %String(MAXLEN = 32);
Property Gate As %String(MAXLEN = 32);
Property Outcome As %String(MAXLEN = 256);
Property Confidence As %Numeric(SCALE = 2);
Property Reason As %String(MAXLEN = 2000);
Property At As %TimeStamp [ InitialExpression = {$ZDATETIME($ZTIMESTAMP, 3)} ];
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
