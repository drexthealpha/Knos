/// /knos: the dashboard page only, served without a login because it holds no data. Every decision, trace and approval
/// it shows comes from /api/knos, which needs the IRIS user and password (the page asks for them once).
Class Knos.Iris.REST.Page Extends %CSP.REST
{
Parameter CHARSET = "utf-8";

XData UrlMap [ XMLNamespace = "http://www.intersystems.com/urlmap" ]
{
<Routes>
<Route Url="/" Method="GET" Call="Show"/>
</Routes>
}

ClassMethod Show() As %Status
{
    return ##class(Knos.Iris.REST.Api).UI()
}
}
