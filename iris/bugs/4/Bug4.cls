/// Embedded Python repro: iris.sql.exec with an int parameter past 64 bits fails with SystemError
Class Bug4.Probe
{

ClassMethod Try(n As %String) As %String [ Language = python ]
{
import iris
v = int(n)
try:
    rs = iris.sql.exec("SELECT ? AS x", v)
    return n + " -> " + repr(next(iter(rs))[0])
except Exception as e:
    return n + " -> " + type(e).__name__ + ": " + str(e)[:140]
}

}
