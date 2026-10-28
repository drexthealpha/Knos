/// Custom outbound adapter: Solana JSON-RPC (Call, Simulate, Status), with retries on 429.
Class Knos.Iris.Adapter.SolanaRpcOutbound Extends Ens.OutboundAdapter
{
Property RpcURL As %String(MAXLEN = 256) [ InitialExpression = "https://api.devnet.solana.com" ];
Property Commitment As %String [ InitialExpression = "confirmed" ];
Property TimeoutS As %Integer [ InitialExpression = 30 ];
Property SSLConfig As %String [ InitialExpression = "knos" ];
Parameter SETTINGS = "RpcURL:Basic,Commitment:Basic,TimeoutS:Basic,SSLConfig:Basic,Credentials:Basic";

Method Call(method As %String, paramsJSON As %String, Output result As %String) As %Status
{
    set result = ""
    try {
        do ##class(%Net.URLParser).Parse(..RpcURL, .p)
        for try = 1:1:3 {
            set req = ##class(%Net.HttpRequest).%New()
            set req.Server = p("host"), req.Timeout = ..TimeoutS
            if $get(p("port")) '= "" { set req.Port = p("port") }
            if p("scheme") = "https" { set req.Https = 1, req.SSLConfiguration = ..SSLConfig }
            set req.ContentType = "application/json"
            do req.EntityBody.Write("{""jsonrpc"":""2.0"",""id"":1,""method"":"""_method_""",""params"":"_$select(paramsJSON="":"[]",1:paramsJSON)_"}")
            set sc = req.Post($select($get(p("path"))="":"/",1:p("path")))
            if $$$ISERR(sc) return sc
            if req.HttpResponse.StatusCode = 429 { hang try quit:try=3  continue }
            set result = req.HttpResponse.Data.Read(1000000)
            quit
        }
    } catch e { return e.AsStatus() }
    return $$$OK
}

Method Simulate(txB64 As %String, Output result As %String) As %Status
{
    return ..Call("simulateTransaction", "["""_txB64_""",{""encoding"":""base64"",""sigVerify"":false,""replaceRecentBlockhash"":true}]", .result)
}

Method Status(sig As %String, Output result As %String) As %Status
{
    return ..Call("getSignatureStatuses", "[["""_sig_"""],{""searchTransactionHistory"":true}]", .result)
}
}
