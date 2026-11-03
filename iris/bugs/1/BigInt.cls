/// Build 2026.3.0AI.154.0: a Python int outside the signed 64-bit range reaches ObjectScript as -1, with no error.
Class Knos.Bugs.BigInt
{

/// 2**63, one past the largest signed 64-bit integer
ClassMethod Past64() As %String [ Language = python ]
{
return 2**63
}

/// Prints each value through Embedded Python next to what Python itself holds, and BUG when they differ
ClassMethod Run()
{
    set b = ##class(%SYS.Python).Import("builtins"), bugs = 0
    for v = "9223372036854775807", "9223372036854775808", "18446744073709551616", "-9223372036854775809" {
        set got = b.int(v)
        set ok = (got = v)
        set bugs = bugs + 'ok
        write $select(ok:"ok  ", 1:"BUG "), "builtins.int(""", v, """) returned to ObjectScript as ", got, !
    }
    set got = ..Past64()
    set bugs = bugs + (got '= "9223372036854775808")
    write $select(got = "9223372036854775808":"ok  ", 1:"BUG "), "a [ Language = python ] method returning 2**63 gives ", got, !
    write "RESULT=", $select(bugs:"REPRODUCED "_bugs, 1:"NOT REPRODUCED"), !
}

}
