/// A brief to lock: its JSON, and what IRIS stores for it (the criteria hash Knos computes, the amount, the order).
Class Knos.Iris.Msg.Brief Extends (Ens.Request, %JSON.Adaptor)
{
Property BriefId As %String(MAXLEN = 128);
Property BriefJSON As %String(MAXLEN = "");
Property AmountUSDC As %Numeric(SCALE = 2);
Property Order As %String(MAXLEN = 64);
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
