/// The lock's answer: Ready or not, the criteria hash, and what is missing.
Class Knos.Iris.Msg.Locked Extends (Ens.Response, %JSON.Adaptor)
{
Property BriefId As %String(MAXLEN = 128);
Property Ready As %Boolean;
Property CriteriaHash As %String(MAXLEN = 64);
Property Missing As %String(MAXLEN = "");
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
