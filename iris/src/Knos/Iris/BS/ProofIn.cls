/// The proof door: the REST API, the check-run poller and the file services all hand proof to ProofDecision here.
Class Knos.Iris.BS.ProofIn Extends Ens.BusinessService
{
Method OnProcessInput(pInput As Knos.Iris.Msg.Proof, Output pOutput As Knos.Iris.Msg.Decision) As %Status
{
    return ..SendRequestSync("ProofDecision", pInput, .pOutput, 300)
}
}
