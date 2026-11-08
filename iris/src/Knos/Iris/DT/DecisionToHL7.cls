/// A decision as an HL7 v2.5 ORU^R01, the format a lab's own system already reads: OBR names the brief, OBX 1 to 3
/// carry the gate, the confidence and the outcome in plain words. No patient: the PID segment is empty.
Class Knos.Iris.DT.DecisionToHL7 Extends Ens.DataTransform
{
ClassMethod Transform(source As Knos.Iris.Msg.Decision, ByRef target As EnsLib.HL7.Message, aux = "") As %Status
{
    set ts = $translate($zdatetime($ztimestamp, 8, 1), ": "), cr = $char(13)
    set hl7 = "MSH|^~\&|KNOS|IRIS|LAB|LAB|"_ts_"||ORU^R01^ORU_R01|KNOS"_source.SessionId_"|P|2.5"_cr
    set hl7 = hl7_"PID|1"_cr
    set hl7 = hl7_"OBR|1|"_..Clean(source.BriefId)_"||KNOS^Knos payout decision^L|||"_ts_cr
    set hl7 = hl7_"OBX|1|ST|GATE^Payout gate^L||"_..Clean(source.Gate)_"||||||F"_cr
    set hl7 = hl7_"OBX|2|NM|CONF^Confidence^L||"_(+source.Confidence)_"||||||F"_cr
    set hl7 = hl7_"OBX|3|ST|OUTCOME^Outcome^L||"_..Clean(source.Outcome)_"||||||F"_cr
    set target = ##class(EnsLib.HL7.Message).ImportFromString(hl7, .sc)
    quit:$$$ISERR(sc) sc
    set target.DocType = "2.5:ORU_R01"
    return $$$OK
}

/// HL7's own delimiters taken out of a value
ClassMethod Clean(v As %String) As %String
{
    return $translate(v, "|^~\&"_$char(13,10))
}
}
