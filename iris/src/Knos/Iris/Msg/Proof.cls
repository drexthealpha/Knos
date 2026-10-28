/// Proof for a locked brief: a GitHub check run, a lab result (FHIR Observation or HL7 ORU) or a referee verdict.
/// BriefJSON is the brief as it is presented now; the decision checks its hash against the lock first.
Class Knos.Iris.Msg.Proof Extends (Ens.Request, %JSON.Adaptor)
{
Property BriefId As %String(MAXLEN = 128);
Property BriefJSON As %String(MAXLEN = "");
Property Kind As %String(VALUELIST = ",checkrun,observation,oru,verdict");
Property SourceRef As %String(MAXLEN = 512);
Property PayloadJSON As %String(MAXLEN = "");
Property AmountUSDC As %Numeric(SCALE = 2);
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
