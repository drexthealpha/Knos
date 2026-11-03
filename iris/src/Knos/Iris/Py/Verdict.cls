/// Knos's strict verdict reader (knos.verdict_gate.strict) and the replay-mode referee's decision.
Class Knos.Iris.Py.Verdict
{
ClassMethod Read(text As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.read_verdict(text)
}

/// 1 when a referee verdict's "signature" is the HMAC-SHA256 of its body under KNOS_VERDICT_SECRET; 0 when it is
/// missing, forged, or no secret is set
ClassMethod Signed(payload As %String) As %Boolean
{
    return ..SignedWith($system.Util.GetEnviron("KNOS_VERDICT_SECRET"), payload)
}

ClassMethod SignedWith(secret As %String, payload As %String) As %Boolean [ Language = python ]
{
from knos_iris import bridge
return 1 if bridge.verdict_signed(secret or "", payload or "") else 0
}

/// 1 when a request body carries GitHub's X-Hub-Signature-256 for it under KNOS_WEBHOOK_SECRET
ClassMethod WebhookSigned(body As %String, signature As %String) As %Boolean
{
    return ..SignatureOk($system.Util.GetEnviron("KNOS_WEBHOOK_SECRET"), body, signature)
}

ClassMethod SignatureOk(secret As %String, body As %String, signature As %String) As %Boolean [ Language = python ]
{
from knos_iris import bridge
return 1 if bridge.signature_ok(secret or "", body or "", signature or "") else 0
}

ClassMethod Decide(briefJSON As %String, kind As %String, payload As %String, criteriaHash As %String) As %String [ Language = python ]
{
from knos_iris import referee
return referee.decide(briefJSON, kind, payload, criteriaHash)
}

/// "" when the proof's repository is the locked brief's (or either names none), else why it is refused
ClassMethod RepoMismatch(briefId As %String, briefJSON As %String, proofJSON As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.repo_mismatch(briefId or "", briefJSON or "{}", proofJSON or "{}")
}

ClassMethod ORUToObservation(hl7 As %String) As %String [ Language = python ]
{
import json
from knos_iris import referee
return json.dumps(referee.oru_to_observation(hl7))
}
}
