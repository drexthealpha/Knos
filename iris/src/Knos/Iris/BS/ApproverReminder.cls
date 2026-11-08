/// Payouts left waiting: every CallInterval seconds, an alert (Ens.Alert) naming how many Workflow tasks have waited
/// for an approver longer than WaitHours, so a held step is not forgotten before its two-day timeout.
Class Knos.Iris.BS.ApproverReminder Extends Ens.BusinessService
{
Parameter ADAPTER = "Ens.InboundAdapter";

/// hours a payout may wait for a person before the reminder names it
Property WaitHours As %Integer [ InitialExpression = 24 ];

Parameter SETTINGS = "WaitHours:Basic";

Method OnProcessInput(pInput As %RegisteredObject, Output pOutput As %RegisteredObject) As %Status
{
    set n = ..Waiting(..WaitHours)
    quit:'n $$$OK
    set text = n_" payout"_$select(n=1:" has", 1:"s have")_" waited for an approver over "_..WaitHours_" hours (Workflow inbox: PayoutApprovers)"
    return ..SendAlert(##class(Ens.AlertRequest).%New($listbuild(..%ConfigName, text)))
}

/// Open PayoutApprovers tasks older than hours
ClassMethod Waiting(hours As %Integer) As %Integer
{
    set since = ##class(Knos.Iris.Util).Ago(hours * 3600)
    &sql(SELECT COUNT(*) INTO :n FROM EnsLib_Workflow.TaskResponse
         WHERE TaskStatus_IsComplete = 0 AND TaskStatus_RoleName = 'PayoutApprovers' AND TaskStatus_TimeCreated < :since)
    return $select(SQLCODE = 0:+n, 1:0)
}
}
