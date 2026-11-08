/// The digest: every CallInterval seconds (a day by default), the last day's decisions by outcome and the model's
/// calls, tokens and dollars, as one plain text file written by DigestFile (outbox/digest).
Class Knos.Iris.BS.DailyDigest Extends Ens.BusinessService
{
Parameter ADAPTER = "Ens.InboundAdapter";

Method OnProcessInput(pInput As %RegisteredObject, Output pOutput As %RegisteredObject) As %Status
{
    set text = ..Text(##class(Knos.Iris.Util).Ago(86400), $zdatetime($ztimestamp, 3))
    set s = ##class(%Stream.GlobalCharacter).%New()
    do s.Write(text)
    set box = ##class(Ens.StreamContainer).%New(s), box.OriginalFilename = "knos-digest"
    return ..SendRequestAsync("DigestFile", box)
}

/// The digest of the decisions made from since to until (ODBC timestamps)
ClassMethod Text(since As %String, until As %String) As %String
{
    set n = 0, gates = ""
    set rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT Gate, COUNT(*) AS N FROM Knos_Iris_Data.Decision WHERE ""At"" >= ? GROUP BY Gate", since)
    while rs.%Next() { set n = n + rs.N, gates(rs.Gate) = rs.N }
    &sql(SELECT COUNT(*), SUM(Tokens), SUM(CostUSD) INTO :calls, :tokens, :usd FROM Knos_Iris_Data.Span
         WHERE Kind = 'llm' AND SessionId IN (SELECT SessionId FROM Knos_Iris_Data.Decision WHERE "At" >= :since))
    set nl = $char(10)
    set t = "Knos digest, "_since_" to "_until_" UTC"_nl
    set t = t_"Decisions: "_n_nl
    set t = t_"  paid: "_+$get(gates("PAY"))_nl
    set t = t_"  waiting for a person: "_+$get(gates("HUMAN"))_nl
    set t = t_"  not paid (test not met or deadline passed): "_+$get(gates("REFUND_AT_DEADLINE"))_nl
    set t = t_"  rejected (brief altered or bad signature): "_+$get(gates("REJECT"))_nl
    set t = t_"  stopped by a person: "_+$get(gates("HELD"))_nl
    set t = t_"Model calls: "_+$get(calls)_", tokens: "_+$get(tokens)_", cost: "_$fnumber(+$get(usd), "", 4)_" USD"_nl
    return t
}
}
