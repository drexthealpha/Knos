/// Installs Knos Referee on IRIS in namespace KNOS: the web app /api/knos, the SSL client config for devnet, the
/// payout threshold, the approver role, the Java server, the FHIR R4 endpoint, the production (started, and started
/// again with IRIS).
Class Knos.Iris.Setup
{
ClassMethod Install(fhir As %Boolean = 1) As %Status
{
    set ns = $namespace
    zn "%SYS"
    set props("NameSpace") = ns, props("DispatchClass") = "Knos.Iris.REST.Api", props("AutheEnabled") = 32, props("Enabled") = 1
    if '##class(Security.Applications).Exists("/api/knos") { set sc = ##class(Security.Applications).Create("/api/knos", .props) }
    if '##class(Security.SSLConfigs).Exists("knos") { set ssl("Enabled") = 1 do ##class(Security.SSLConfigs).Create("knos", .ssl) }
    do ##class(%Net.Remote.Service).StartGateway("%Java Server")
    zn ns
    do ##class(Ens.Util.LookupTable).%UpdateValue("KnosPayoutThreshold", "usdc", +$system.Util.GetEnviron("KNOS_PAYOUT_THRESHOLD_USDC") + ($system.Util.GetEnviron("KNOS_PAYOUT_THRESHOLD_USDC") = "" * 50))
    do ##class(EnsLib.Workflow.RoleDefinition).CreateRole("PayoutApprovers")
    do ##class(EnsLib.Workflow.RoleDefinition).AddUserToRole("PayoutApprovers", "_SYSTEM")
    if fhir {
        try {
            do ##class(HS.FHIRServer.Installer).InstallNamespace()
            if '##class(HS.FHIRServer.ServiceAdmin).EndpointExists("/csp/healthshare/knos/fhir/r4") {
                do ##class(HS.FHIRServer.Installer).InstallInstance("/csp/healthshare/knos/fhir/r4", "HS.FHIRServer.Storage.Json.InteractionsStrategy", $lb("hl7.fhir.r4.core@4.0.1"))
            }
        } catch e { write "FHIR: ", e.DisplayString(), ! }
    }
    do ##class(Ens.Director).SetAutoStart("Knos.Iris.Production")
    if ##class(Ens.Director).IsProductionRunning() return $$$OK
    return ##class(Ens.Director).StartProduction("Knos.Iris.Production")
}
}
