/// A JSON-RPC call to Solana (SolanaRead, through the custom outbound adapter).
Class Knos.Iris.Msg.RpcRequest Extends (Ens.Request, %JSON.Adaptor)
{
Property Method As %String(MAXLEN = 64);
Property ParamsJSON As %String(MAXLEN = "");
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
