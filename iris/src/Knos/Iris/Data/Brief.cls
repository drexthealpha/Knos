/// A locked brief: its JSON as locked and the criteria hash Knos computed for it.
Class Knos.Iris.Data.Brief Extends %Persistent
{
Property BriefId As %String(MAXLEN = 128) [ Required ];
Property BriefJSON As %String(MAXLEN = "");
Property CriteriaHash As %String(MAXLEN = 64);
Property AmountUSDC As %Numeric(SCALE = 2);
Property LockedAt As %TimeStamp [ InitialExpression = {$ZDATETIME($ZTIMESTAMP, 3)} ];
Index BriefIdIdx On BriefId [ Unique ];
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
