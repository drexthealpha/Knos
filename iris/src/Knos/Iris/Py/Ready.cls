/// Knos's Ready checks, imported (knos.ready), not copied: Check, Hash and Require.
Class Knos.Iris.Py.Ready
{
ClassMethod Check(briefJSON As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.check(briefJSON)
}

ClassMethod Hash(briefJSON As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.criteria_hash(briefJSON)
}

/// knos.ready.require: the check when Ready; a NotReady error becomes a %Status
ClassMethod Require(briefJSON As %String, Output result As %String) As %Status
{
    try {
        set result = ..RequirePy(briefJSON)
        return $$$OK
    } catch e {
        return $$$ERROR($$$GeneralError, "Not ready: "_e.DisplayString())
    }
}

ClassMethod RequirePy(briefJSON As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.require(briefJSON)
}
}
