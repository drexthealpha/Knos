/// Installs Knos Referee on IRIS in namespace KNOS: the web app /api/knos, the SSL client config for devnet, the
/// payout threshold, the approver role, the Java server's memory cap (it starts on first use, with the production),
/// the FHIR R4 endpoint only when asked (KNOS_FHIR=1: about 2 GB more at build), the production (started, and started
/// again with IRIS).
Class Knos.Iris.Setup
{
ClassMethod Install(fhir As %Boolean = 0) As %Status
{
    set ns = $namespace
    zn "%SYS"
    set props("NameSpace") = ns, props("DispatchClass") = "Knos.Iris.REST.Api", props("AutheEnabled") = 32, props("Enabled") = 1
    if '##class(Security.Applications).Exists("/api/knos") { set sc = ##class(Security.Applications).Create("/api/knos", .props) }
    // /knos serves the dashboard page alone, with no login: the page holds no data and asks for the user and password
    // before it calls /api/knos. The only role it adds is the KNOS database's, so the page class can run
    set page("NameSpace") = ns, page("DispatchClass") = "Knos.Iris.REST.Page", page("AutheEnabled") = 64, page("Enabled") = 1, page("MatchRoles") = ":%DB_"_ns
    if '##class(Security.Applications).Exists("/knos") { do ##class(Security.Applications).Create("/knos", .page) }
    // the referee's read tools as an AI Hub MCP service (Knos.Iris.AI.MCP), password login like /api/knos
    set mcp("NameSpace") = ns, mcp("DispatchClass") = "Knos.Iris.AI.MCP", mcp("AutheEnabled") = 32, mcp("Enabled") = 1
    if '##class(Security.Applications).Exists("/api/knos/mcp") { do ##class(Security.Applications).Create("/api/knos/mcp", .mcp) }
    if '##class(Security.SSLConfigs).Exists("knos") { set ssl("Enabled") = 1 do ##class(Security.SSLConfigs).Create("knos", .ssl) }
    // the Java gateway: capped at 192 MB, never started here (the production's PEX operation starts it on first use)
    if ##class(Config.Gateways).Get("%Java Server", .gw) { set gw("JVMArgs") = "-Xmx192m" do ##class(Config.Gateways).Modify("%Java Server", .gw) }
    zn ns
    do ##class(Ens.Util.LookupTable).%UpdateValue("KnosPayoutThreshold", "usdc", +$system.Util.GetEnviron("KNOS_PAYOUT_THRESHOLD_USDC") + ($system.Util.GetEnviron("KNOS_PAYOUT_THRESHOLD_USDC") = "" * 50))
    do ##class(EnsLib.Workflow.RoleDefinition).CreateRole("PayoutApprovers")
    // the approver must be a Workflow user first: without it AddUserToRole adds nobody and every task fails with
    // ErrNoUsersFound (a fresh container, 5 Nov 2026)
    if '##class(EnsLib.Workflow.UserDefinition).%ExistsId("_SYSTEM") { do ##class(EnsLib.Workflow.UserDefinition).CreateUser("_SYSTEM") }
    do ##class(EnsLib.Workflow.RoleDefinition).AddUserToRole("PayoutApprovers", "_SYSTEM")
    if fhir {
        try {
            do ##class(HS.FHIRServer.Installer).InstallNamespace()
            if '##class(HS.FHIRServer.ServiceAdmin).EndpointExists("/csp/healthshare/knos/fhir/r4") {
                do ##class(HS.FHIRServer.Installer).InstallInstance("/csp/healthshare/knos/fhir/r4", "HS.FHIRServer.Storage.Json.InteractionsStrategy", $lb("hl7.fhir.r4.core@4.0.1"))
            }
        } catch e { write "FHIR: ", e.DisplayString(), ! }
    }
    do ..Paths()
    do ##class(Ens.Director).SetAutoStart("Knos.Iris.Production")
    if ##class(Ens.Director).IsProductionRunning() return $$$OK
    set sc = ##class(Ens.Director).StartProduction("Knos.Iris.Production")
    // in an IPM load the production's runtime lock can stay taken until the load ends (KNOSZPM: ErrCanNotAcquireRuntimeLock
    // after 30 s), so a background job starts it once the lock is free
    if 'sc && ($system.Status.GetErrorText(sc) [ "runtime global lock") { job ##class(Knos.Iris.Setup).StartWhenFree() return $$$OK }
    return sc
}

/// Starts the production, every 10 s for at most 10 minutes, until it runs
/// The online demo's read-only user: role KnosDemo reads the KNOS database and the four tables the page shows, and
/// nothing else; /api/knos refuses its POSTs (Knos.Iris.REST.Api.OnPreDispatch). Run from namespace KNOS.
///   do ##class(Knos.Iris.Setup).DemoUser("demo", "<password>")
ClassMethod DemoUser(user As %String, password As %String) As %Status
{
    set ns = $namespace, sc = $$$OK
    try {
        zn "%SYS"
        if '##class(Security.Roles).Exists("KnosDemo") {
            set sc = ##class(Security.Roles).Create("KnosDemo", "Reads the Knos decisions, traces and tasks; writes nothing", "%DB_"_ns_":R")
            quit:$$$ISERR(sc)
        }
        if ##class(Security.Users).Exists(user) { set p("Roles") = "KnosDemo", p("Password") = password set sc = ##class(Security.Users).Modify(user, .p) }
        else { set sc = ##class(Security.Users).Create(user, "KnosDemo", password, "Knos demo (read only)", ns) }
        quit:$$$ISERR(sc)
        zn ns
        for t = "Knos_Iris_Data.Decision", "Knos_Iris_Data.Span", "Ens.MessageHeader", "EnsLib_Workflow.TaskResponse" {
            set rs = ##class(%SQL.Statement).%ExecDirect(, "GRANT SELECT ON "_t_" TO KnosDemo")
            if rs.%SQLCODE < 0 { set sc = $$$ERROR($$$SQLError, rs.%SQLCODE, rs.%Message) quit }
        }
    } catch e { set sc = e.AsStatus() }
    zn ns
    return sc
}

ClassMethod StartWhenFree()
{
    for i = 1:1:60 {
        hang 10
        if ##class(Ens.Director).IsProductionRunning() quit
        if $$$ISOK(##class(Ens.Director).StartProduction("Knos.Iris.Production")) quit
    }
}

/// The production's folders and the PEX jar, from Knos.Iris.Util.Home(): the same code runs in this image and in an
/// IPM install anywhere else
ClassMethod Paths() As %Status
{
    set h = ##class(Knos.Iris.Util).Home()
    for d = "inbox/checkruns", "inbox/oru", "inbox/verdicts", "java" { do ##class(%File).CreateDirectoryChain(h_d) }
    do ..Jar(h)
    set s("GitHubCheckRunPoller", "Adapter", "Dir") = h_"inbox/checkruns"
    set s("HL7LabIn", "Adapter", "FilePath") = h_"inbox/oru/"
    set s("SolanaSubmit", "Host", "%gatewayExtraClasspaths") = h_"java/knos-iris-pex.jar"
    return ##class(Ens.Production).ApplySettings("Knos.Iris.Production", .s)
}

/// The Java PEX jar, when it is not there yet (an IPM install; iris/Dockerfile builds it in its jar stage): javac with
/// the instance's own JDK against its own PEX jar, the same commands as the Dockerfile
ClassMethod Jar(h As %String) As %Status
{
    set jar = h_"java/knos-iris-pex.jar"
    if ##class(%File).Exists(jar) return $$$OK
    set lib = $system.Util.InstallDirectory()_"dev/java/lib/1.8/", tmp = h_"java/build/"
    set src = h_"iris/java/src/main/java/knos/iris/pex/SolanaSubmitOperation.java"
    set cmd = "rm -rf '"_tmp_"' && mkdir -p '"_tmp_"' && javac -d '"_tmp_"' -cp '"_lib_"*' '"_src_"'"
    set cmd = cmd_" && cd '"_tmp_"' && jar xf '"_lib_"intersystems-pex-1.0.0-shaded.jar' && jar cf '"_jar_"' -C '"_tmp_"' . && rm -rf '"_tmp_"'"
    set rc = $zf(-100, "/SHELL", cmd)
    if rc { write "Java PEX jar not built (exit ", rc, "): the SolanaSubmit item needs a JDK", ! }
    return $$$OK
}
}
