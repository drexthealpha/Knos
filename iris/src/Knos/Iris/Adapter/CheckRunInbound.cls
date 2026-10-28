/// Custom inbound adapter: polls for GitHub check runs. Each JSON file dropped in Dir (a check_run webhook body, as
/// GitHub sends it) becomes one call to the service; with Repos and a token it reads GitHub's check-runs API too.
Class Knos.Iris.Adapter.CheckRunInbound Extends Ens.InboundAdapter
{
Property Dir As %String(MAXLEN = 512) [ InitialExpression = "/home/irisowner/knos/inbox/checkruns" ];
Property Repos As %String(MAXLEN = 1000);
Parameter SETTINGS = "Dir:Basic,Repos:Basic,Credentials:Basic,CallInterval:Basic";

Method OnTask() As %Status
{
    set sc = $$$OK
    try {
        set rs = ##class(%ResultSet).%New("%File:FileSet")
        do rs.Execute(..Dir, "*.json")
        while rs.Next() {
            set path = rs.Get("Name")
            set f = ##class(%Stream.FileCharacter).%New()
            set f.Filename = path
            set text = f.Read(1000000)
            set sc = ..BusinessHost.ProcessInput(##class(Ens.StringContainer).%New(text))
            quit:$$$ISERR(sc)
            do ##class(%File).Rename(path, path_".done")
        }
    } catch e { set sc = e.AsStatus() }
    set ..BusinessHost.%WaitForNextCallInterval = 1
    return sc
}
}
