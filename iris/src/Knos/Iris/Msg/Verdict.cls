/// The referee's answer, as the decision contract holds it, with what it cost.
Class Knos.Iris.Msg.Verdict Extends (Ens.Response, %JSON.Adaptor)
{
Property Decision As %String(VALUELIST = ",met,not_met,insufficient");
Property MilestonesJSON As %String(MAXLEN = "");
Property Confidence As %Numeric(SCALE = 2);
Property CriteriaHash As %String(MAXLEN = 64);
Property Model As %String(MAXLEN = 128);
Property InTok As %Integer;
Property OutTok As %Integer;
Property CostUSD As %Numeric(SCALE = 6);
Property Mode As %String(MAXLEN = 32);
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
