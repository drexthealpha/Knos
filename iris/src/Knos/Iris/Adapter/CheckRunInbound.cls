/// Custom inbound adapter: each JSON file dropped in Dir (a check_run webhook body, as GitHub sends it) becomes one
/// call to the service. Each file is handled on its own: a file the service refuses (no brief locked for its
/// repository, a body that does not parse) is renamed to .err with its reason beside it in .err.txt, an alert is sent,
/// and the next file is read. A bad file is never read twice and never blocks the ones behind it.
Class Knos.Iris.Adapter.CheckRunInbound Extends Ens.InboundAdapter
{
Property Dir As %String(MAXLEN = 512) [ InitialExpression = {##class(Knos.Iris.Util).Home()_"inbox/checkruns"} ];
Parameter SETTINGS = "Dir:Basic,CallInterval:Basic";

Method OnTask() As %Status
{
    try {
        set rs = ##class(%ResultSet).%New("%File:FileSet")
        do rs.Execute(..Dir, "*.json")
        while rs.Next() {
            set path = rs.Get("Name")
            do ..One(path)
        }
    } catch e {
        $$$LOGERROR("the check-run inbox could not be read: "_e.DisplayString())
    }
    set ..BusinessHost.%WaitForNextCallInterval = 1
    return $$$OK
}

/// One file: processed and renamed .done, or renamed .err with its reason and an alert
Method One(path As %String)
{
    set sc = $$$OK
    try {
        set f = ##class(%Stream.FileCharacter).%New()
        set f.Filename = path
        set text = f.Read(1000000)
        set sc = ..BusinessHost.ProcessInput(##class(Ens.StringContainer).%New(text))
    } catch e { set sc = e.AsStatus() }
    if $$$ISOK(sc) { do ##class(%File).Rename(path, path_".done") return }
    set why = $system.Status.GetErrorText(sc)
    do ##class(%File).Rename(path, path_".err")
    set r = ##class(%Stream.FileCharacter).%New(), r.Filename = path_".err.txt"
    do r.WriteLine(why), r.%Save()
    $$$LOGWARNING("check-run file set aside as .err: "_##class(%File).GetFilename(path)_": "_why)
    do ..BusinessHost.SendAlert(##class(Ens.AlertRequest).%New($lb(..BusinessHost.%ConfigName, "check-run file set aside: "_##class(%File).GetFilename(path)_": "_why)))
}
}
