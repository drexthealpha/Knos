/// Reads Solana devnet through the custom outbound adapter: slots, accounts, simulations, signature statuses.
Class Knos.Iris.BO.SolanaRead Extends Ens.BusinessOperation
{
Parameter ADAPTER = "Knos.Iris.Adapter.SolanaRpcOutbound";
Property Adapter As Knos.Iris.Adapter.SolanaRpcOutbound;

Method Rpc(pRequest As Knos.Iris.Msg.RpcRequest, Output pResponse As Knos.Iris.Msg.RpcResponse) As %Status
{
    set pResponse = ##class(Knos.Iris.Msg.RpcResponse).%New()
    set sc = ..Adapter.Call(pRequest.Method, pRequest.ParamsJSON, .out)
    if $$$ISERR(sc) { set pResponse.Error = $system.Status.GetErrorText(sc) return $$$OK }
    set pResponse.ResultJSON = out
    return $$$OK
}

XData MessageMap
{
<MapItems>
<MapItem MessageType="Knos.Iris.Msg.RpcRequest"><Method>Rpc</Method></MapItem>
</MapItems>
}
}
