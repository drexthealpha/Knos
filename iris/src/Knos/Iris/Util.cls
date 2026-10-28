/// Small helpers.
Class Knos.Iris.Util
{
ClassMethod Sha(text As %String) As %String
{
    return $zconvert(##class(%xsd.hexBinary).LogicalToXSD($system.Encryption.SHAHash(256, $zconvert(text, "O", "UTF8"))), "L")
}
}
