/// What the production decided for one proof: the referee's decision, the gate, the outcome and its session.
Class Knos.Iris.Msg.Decision Extends (Ens.Response, %JSON.Adaptor)
{
Property BriefId As %String(MAXLEN = 128);
Property Decision As %String(MAXLEN = 32);
Property Gate As %String(MAXLEN = 32);
Property Outcome As %String(MAXLEN = 256);
Property Confidence As %Numeric(SCALE = 2);
Property Reason As %String(MAXLEN = 2000);
Property SessionId As %Integer;
Property Simulation As %String(MAXLEN = 2000);
/// which referee decided: the AI Hub agent and its provider, the rules referee (no model key set), or a refusal
Property Referee As %String(MAXLEN = 512);
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
