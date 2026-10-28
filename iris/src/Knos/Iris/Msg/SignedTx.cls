/// A transaction Knos's code built (Knos.Iris.Py.Tx) for the Java PEX operation to send or simulate.
Class Knos.Iris.Msg.SignedTx Extends (Ens.Request, %JSON.Adaptor)
{
Property TxB64 As %String(MAXLEN = "");
Property Mode As %String(VALUELIST = ",simulate,send") [ InitialExpression = "simulate" ];
Property Kind As %String(MAXLEN = 32);
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
