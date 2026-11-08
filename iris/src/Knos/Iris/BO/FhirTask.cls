/// Each decision as a FHIR R4 Task, in outbox/fhir: the step is the Task, its status follows the gate (paid: completed,
/// waiting for a person: on-hold, not met: failed, brief altered: rejected, an approver said no: cancelled).
/// A hospital's FHIR server can load the file as it is; no FHIR server runs here.
Class Knos.Iris.BO.FhirTask Extends Ens.BusinessOperation
{
Parameter ADAPTER = "EnsLib.File.OutboundAdapter";

Parameter INVOCATION = "Queue";

Method Write(pRequest As Knos.Iris.Msg.Decision, Output pResponse As Ens.Response) As %Status
{
    set task = ..Task(pRequest)
    do ##class(%File).CreateDirectoryChain(..Adapter.FilePath)
    return ..Adapter.PutString("task-"_pRequest.SessionId_"-"_$zconvert(pRequest.Gate, "L")_".json", task.%ToJSON())
}

ClassMethod Task(d As Knos.Iris.Msg.Decision) As %DynamicObject
{
    set status = $case(d.Gate, "PAY":"completed", "HUMAN":"on-hold", "REFUND_AT_DEADLINE":"failed", "HELD":"cancelled", :"rejected")
    set t = {"resourceType": "Task", "id": ("knos-"_d.SessionId), "status": (status), "intent": "order"}
    set t.businessStatus = {"text": (d.Outcome)}
    set t.description = "Pay one research step when its test proves it is done: "_d.BriefId
    set t.focus = {"identifier": {"system": "https://github.com/drexthealpha/Knos", "value": (d.BriefId)}}
    set t.lastModified = $zdatetime($ztimestamp, 3, 7)
    set t.output = [{"type": {"text": "payout gate"}, "valueString": (d.Gate)}, {"type": {"text": "confidence"}, "valueDecimal": (+d.Confidence)}]
    return t
}

XData MessageMap
{
<MapItems>
<MapItem MessageType="Knos.Iris.Msg.Decision"><Method>Write</Method></MapItem>
</MapItems>
}
}
