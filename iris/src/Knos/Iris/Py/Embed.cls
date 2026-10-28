/// The vector search's embedding (knos_iris.bridge.embed) and a cosine, for the test that checks the search.
Class Knos.Iris.Py.Embed
{
ClassMethod Vector(text As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.embed(text)
}

ClassMethod Criteria(briefJSON As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.criterion_text(briefJSON)
}

ClassMethod Score(a As %String, b As %String) As %Numeric [ Language = python ]
{
from knos_iris import bridge
x = [float(v) for v in bridge.embed(a).split(",")]
y = [float(v) for v in bridge.embed(b).split(",")]
return sum(p * q for p, q in zip(x, y))
}
}
