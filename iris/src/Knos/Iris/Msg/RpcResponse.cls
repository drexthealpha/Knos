/// A JSON-RPC answer from Solana.
Class Knos.Iris.Msg.RpcResponse Extends (Ens.Response, %JSON.Adaptor)
{
Property ResultJSON As %String(MAXLEN = "");
Property Error As %String(MAXLEN = 2000);
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
