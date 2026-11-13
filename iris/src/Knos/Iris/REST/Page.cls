/// /knos: the dashboard page only, served without a login because it holds no data. Every decision, trace and approval
/// it shows comes from /api/knos, which needs the IRIS user and password (the page asks for them once).
Class Knos.Iris.REST.Page Extends %CSP.REST
{
Parameter CHARSET = "utf-8";

XData UrlMap [ XMLNamespace = "http://www.intersystems.com/urlmap" ]
{
<Routes>
<Route Url="/" Method="GET" Call="Show"/>
<Route Url="/brand/tokens.css" Method="GET" Call="Tokens"/>
<Route Url="/brand/mark.svg" Method="GET" Call="Mark"/>
<Route Url="/fonts/:f" Method="GET" Call="Font"/>
</Routes>
}

ClassMethod Show() As %Status
{
    return ##class(Knos.Iris.REST.Api).UI()
}

/// The site's one tokens file (web/brand/tokens.css), the same bytes the site and the NEAR app load
ClassMethod Tokens() As %Status
{
    return ..File("web/brand/tokens.css", "text/css")
}

/// The crow, the mark the bar and the tab show (web/brand/mark.svg)
ClassMethod Mark() As %Status
{
    return ..File("web/brand/mark.svg", "image/svg+xml")
}

/// The four fonts the tokens file names (web/fonts/*.woff2); any other name is not here
ClassMethod Font(f As %String) As %Status
{
    if '$listfind($listbuild("bricolage-grotesque.woff2", "geist.woff2", "jetbrains-mono.woff2", "instrument-serif.woff2"), f) { set %response.Status = 404 return $$$OK }
    return ..File("web/fonts/"_f, "font/woff2")
}

ClassMethod File(path As %String, type As %String) As %Status
{
    set s = ##class(%Stream.FileBinary).%New()
    set sc = s.LinkToFile($system.Util.GetEnviron("KNOS_IRIS_HOME")_"/"_path)
    if $$$ISERR(sc) || 's.Size { set %response.Status = 404 return $$$OK }
    set %response.ContentType = type
    // fonts and images are bytes: no character set, no conversion (a font sent through UTF-8 grew from 18,736 to 28,223 bytes)
    if (type '[ "text") && (type '[ "javascript") && (type '[ "json") && (type '[ "svg") { set %response.CharSet = "", %response.NoCharSetConvert = 1 }
    do %response.SetHeader("Cache-Control", "public, max-age=3600")
    do s.OutputToDevice()
    return $$$OK
}
}
