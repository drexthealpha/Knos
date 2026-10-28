/// Lab results from labs that do not speak FHIR: each HL7 ORU^R01 file in the inbox becomes proof for the brief named
/// in its file name (<briefId>.hl7), turned into an Observation on the way (OBX-3, OBX-5/6, OBX-14, OBX-16).
Class Knos.Iris.BS.LabFile Extends Ens.BusinessService
{
Parameter ADAPTER = "EnsLib.File.InboundAdapter";

Method OnProcessInput(pInput As %Stream.Object, Output pOutput As %RegisteredObject) As %Status
{
    set text = pInput.Read(1000000)
    set id = $piece(##class(%File).GetFilename(pInput.Attributes("Filename")), ".", 1)
    set brief = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(id)
    if '$isobject(brief) return $$$ERROR($$$GeneralError, "no brief is locked as "_id)
    set m = ##class(Knos.Iris.Msg.Proof).%New()
    set m.BriefId = id, m.BriefJSON = brief.BriefJSON, m.Kind = "oru", m.PayloadJSON = text, m.AmountUSDC = brief.AmountUSDC
    set m.SourceRef = "file:"_pInput.Attributes("Filename")
    return ..SendRequestAsync("ProofDecision", m)
}
}
