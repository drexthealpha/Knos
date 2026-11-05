/// The referee's authorization policy (AI Hub %AI.Policy.Authorization): a tool runs only when it is one of the
/// referee's read tools and its arguments stay under 20,000 characters. Every other call is refused before it runs.
Class Knos.Iris.AI.ToolPolicy Extends %AI.Policy.Authorization
{

Parameter ALLOWED = "GetBrief,GetCheckRun,GetObservation,GetVerdict,SearchCriteria";

Parameter MAXARGS = 20000;

Method %CanExecute(toolref As %String, call As %DynamicObject, metadata As %DynamicObject) As %Status
{
    set name = $piece($piece(toolref, ".", *), ":", *)
    return:'$listfind($listfromstring(..#ALLOWED), name) $$$ERROR($$$GeneralError, "the referee may not call "_name)
    set size = $select($isobject(call):$length(call.%ToJSON()), 1:0)
    return:(size > ..#MAXARGS) $$$ERROR($$$GeneralError, name_": arguments of "_size_" characters, over the "_..#MAXARGS_" the referee allows")
    return $$$OK
}

Method %CanList(toolref As %String, metadata As %DynamicObject) As %Boolean
{
    return 1
}

}
