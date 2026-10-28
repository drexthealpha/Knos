/// The gate after the referee, deterministic: PAY, HUMAN, REFUND_AT_DEADLINE or REJECT.
/// PAY when met, confidence at least 0.80, the amount at most the threshold and the milestone machine-checked; HUMAN when
/// met above the threshold, under 0.80, human-verified or insufficient; REFUND_AT_DEADLINE when not met; REJECT when the
/// brief's hash no longer matches its lock. The agent can only say no or ask a person: money still needs the chain's rules.
Class Knos.Iris.Rule.PayoutGate
{
ClassMethod Decide(decision As %String, confidence As %Numeric, amount As %Numeric, threshold As %Numeric, kind As %String, hashOk As %Boolean) As %String
{
    if 'hashOk return "REJECT"
    if decision = "not_met" return "REFUND_AT_DEADLINE"
    if decision = "met", confidence >= 0.80, amount <= threshold, kind = "machine" return "PAY"
    return "HUMAN"
}
}
