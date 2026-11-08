/// Small helpers.
Class Knos.Iris.Util
{
/// Where Knos's files are on this instance, with a trailing slash: KNOS_IRIS_HOME, else the knos folder beside the
/// manager directory (where module.xml copies iris/ for an IPM install)
ClassMethod Home() As %String
{
    set h = $system.Util.GetEnviron("KNOS_IRIS_HOME")
    set:h="" h = ##class(%File).NormalizeDirectory($system.Util.ManagerDirectory()_"../knos")
    return ##class(%File).NormalizeDirectory(h)
}

/// The UTC time secs seconds ago, as an ODBC timestamp
ClassMethod Ago(secs As %Integer) As %String
{
    set h = $ztimestamp, d = +h, s = $piece(h, ",", 2) - secs
    while s < 0 { set s = s + 86400, d = d - 1 }
    return $zdatetime(d_","_s, 3)
}

ClassMethod Sha(text As %String) As %String
{
    return $zconvert(##class(%xsd.hexBinary).LogicalToXSD($system.Encryption.SHAHash(256, $zconvert(text, "O", "UTF8"))), "L")
}
}
