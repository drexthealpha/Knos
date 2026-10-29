/// The hard spend cap of live mode, checked before any model call so a key the operator adds cannot be burned:
/// at most KNOS_LLM_MAX_CALLS calls (default 30) and KNOS_LLM_MAX_USD dollars (default 2.00), counted in
/// ^Knos.LLM("calls") and ^Knos.LLM("usd"). Once either is reached every further call is refused.
Class Knos.Iris.AI.Budget Extends %RegisteredObject
{

ClassMethod MaxCalls() As %Integer
{
    set n = $system.Util.GetEnviron("KNOS_LLM_MAX_CALLS")
    return $select(n?1.N:+n, 1:30)
}

ClassMethod MaxUSD() As %Numeric
{
    set n = $system.Util.GetEnviron("KNOS_LLM_MAX_USD")
    return $select(n?1.N.1(1"."1.N):+n, 1:2.00)
}

/// "" when one more call is allowed, else the one plain sentence that refuses it
ClassMethod Refusal() As %String
{
    set calls = +$get(^Knos.LLM("calls")), usd = +$get(^Knos.LLM("usd"))
    if calls >= ..MaxCalls() return "The model's spend cap is reached: "_calls_" of "_..MaxCalls()_" calls made, so no more are sent."
    if usd >= ..MaxUSD() return "The model's spend cap is reached: "_$fnumber(usd, "", 4)_" of "_$fnumber(..MaxUSD(), "", 2)_" USD spent, so no more calls are sent."
    return ""
}

/// Takes one call's place before it is sent; false (with the refusal in why) when the cap is reached
ClassMethod Take(Output why As %String) As %Boolean
{
    lock +^Knos.LLM:5
    set why = ..Refusal()
    if why = "" { set ^Knos.LLM("calls") = $get(^Knos.LLM("calls")) + 1 }
    lock -^Knos.LLM
    return why = ""
}

/// What a call cost, from the provider's own usage
ClassMethod Spend(usd As %Numeric)
{
    lock +^Knos.LLM:5
    set ^Knos.LLM("usd") = $get(^Knos.LLM("usd")) + usd
    lock -^Knos.LLM
}

}
