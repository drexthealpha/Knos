/// Lab results as FHIR Observation files: each <briefId>.json dropped in inbox/fhir is proof for that brief, decided
/// like any other (the HL7 inbox's twin for labs that export FHIR).
Class Knos.Iris.BS.FhirFile Extends Ens.BusinessService
{
Parameter ADAPTER = "EnsLib.File.InboundAdapter";

Method OnProcessInput(pInput As %Stream.Object, Output pOutput As %RegisteredObject) As %Status
{
    set text = pInput.Read(1000000)
    set id = $piece(##class(%File).GetFilename(pInput.Attributes("Filename")), ".", 1)
    set brief = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(id)
    if '$isobject(brief) return $$$ERROR($$$GeneralError, "no brief is locked as "_id)
    set obs = {}.%FromJSON(text)
    if obs.resourceType '= "Observation" return $$$ERROR($$$GeneralError, "not a FHIR Observation: "_obs.resourceType)
    set m = ##class(Knos.Iris.Msg.Proof).%New()
    set m.BriefId = id, m.BriefJSON = brief.BriefJSON, m.Kind = "observation", m.PayloadJSON = text, m.AmountUSDC = brief.AmountUSDC
    set m.SourceRef = "file:"_pInput.Attributes("Filename")
    return ..SendRequestAsync("ProofDecision", m)
}
}
