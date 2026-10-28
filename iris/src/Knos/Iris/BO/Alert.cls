/// Alerts (an LLM failure, a hash mismatch, a payout error, a Workflow timeout): written to the event log.
Class Knos.Iris.BO.Alert Extends Ens.BusinessOperation
{
Method Note(pRequest As Ens.AlertRequest, Output pResponse As Ens.Response) As %Status
{
    $$$LOGWARNING("Knos alert: "_pRequest.AlertText)
    return $$$OK
}

XData MessageMap
{
<MapItems>
<MapItem MessageType="Ens.AlertRequest"><Method>Note</Method></MapItem>
</MapItems>
}
}
