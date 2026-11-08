/// The deadline: every CallInterval seconds, a brief whose last milestone deadline (its lock time plus the largest
/// deadline_days) has passed with no step paid is decided once as REFUND_AT_DEADLINE, and that decision goes to the
/// DecisionRouter like any other (receipt, FHIR Task, HL7). It moves no money: the refund itself is the chain's rule.
Class Knos.Iris.BS.DeadlineWatch Extends Ens.BusinessService
{
Parameter ADAPTER = "Ens.InboundAdapter";

Method OnProcessInput(pInput As %RegisteredObject, Output pOutput As %RegisteredObject) As %Status
{
    set now = $zdatetime($ztimestamp, 3)
    set rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT BriefId, BriefJSON, LockedAt FROM Knos_Iris_Data.Brief")
    while rs.%Next() {
        set id = rs.BriefId, due = ..Due(rs.BriefJSON, rs.LockedAt)
        continue:(due = "")||(due ] now)
        &sql(SELECT COUNT(*) INTO :done FROM Knos_Iris_Data.Decision WHERE BriefId = :id AND Gate IN ('PAY', 'REFUND_AT_DEADLINE'))
        continue:done
        set d = ##class(Knos.Iris.Data.Decision).%New(), d.SessionId = ..%SessionId, d.BriefId = id, d.Kind = "deadline"
        set d.Decision = "not_met", d.Gate = "REFUND_AT_DEADLINE", d.Outcome = "not met by the deadline ("_$piece(due, " ")_"): refunded to the funder"
        set sc = d.%Save() quit:$$$ISERR(sc)
        set m = ##class(Knos.Iris.Msg.Decision).%New(), m.BriefId = id, m.Decision = d.Decision, m.Gate = d.Gate
        set m.Outcome = d.Outcome, m.SessionId = ..%SessionId, m.Referee = "the deadline (no referee asked)"
        set sc = ..SendRequestAsync("DecisionRouter", m) quit:$$$ISERR(sc)
        set ..%SessionId = ""
    }
    return $get(sc, $$$OK)
}

/// The brief's last deadline as an ODBC timestamp, or "" when it names none
ClassMethod Due(json As %String, locked As %String) As %String
{
    set days = 0, ms = {}.%FromJSON(json).milestones
    quit:'$isobject(ms) ""
    set it = ms.%GetIterator()
    while it.%GetNext(, .m) { set:+m."deadline_days">days days = +m."deadline_days" }
    quit:'days ""
    set h = $zdatetimeh(locked, 3)
    return $zdatetime(($piece(h, ",") + days)_","_$piece(h, ",", 2), 3)
}
}
