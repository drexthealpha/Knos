/// The lab's receipt: each decision, and each change to it (an approver's answer), as one JSON file in outbox/receipts.
Class Knos.Iris.BO.ReceiptFile Extends Ens.BusinessOperation
{
Parameter ADAPTER = "EnsLib.File.OutboundAdapter";

Parameter INVOCATION = "Queue";

Method Write(pRequest As Knos.Iris.Msg.Decision, Output pResponse As Ens.Response) As %Status
{
    set sc = pRequest.%JSONExportToString(.json)
    quit:$$$ISERR(sc) sc
    do ##class(%File).CreateDirectoryChain(..Adapter.FilePath)
    return ..Adapter.PutString("decision-"_pRequest.SessionId_"-"_$zconvert(pRequest.Gate, "L")_".json", json)
}

XData MessageMap
{
<MapItems>
<MapItem MessageType="Knos.Iris.Msg.Decision"><Method>Write</Method></MapItem>
</MapItems>
}
}
