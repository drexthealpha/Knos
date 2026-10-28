/// Knos's strict verdict reader (knos.verdict_gate.strict) and the replay-mode referee's decision.
Class Knos.Iris.Py.Verdict
{
ClassMethod Read(text As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.read_verdict(text)
}

ClassMethod Decide(briefJSON As %String, kind As %String, payload As %String, criteriaHash As %String) As %String [ Language = python ]
{
from knos_iris import referee
return referee.decide(briefJSON, kind, payload, criteriaHash)
}

ClassMethod ORUToObservation(hl7 As %String) As %String [ Language = python ]
{
import json
from knos_iris import referee
return json.dumps(referee.oru_to_observation(hl7))
}
}
