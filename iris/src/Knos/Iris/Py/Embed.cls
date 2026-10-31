/// The vector search's embedding (knos_iris.bridge.embed) and a cosine, for the test that checks the search.
Class Knos.Iris.Py.Embed
{
ClassMethod Vector(text As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.embed(text)
}

/// A proof as the search asks with it: the open model's query form (knos_iris.bridge.embed with query=True).
ClassMethod Query(text As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.embed(text, True)
}

/// Which embedding answers: the open model's name, or hashed.
ClassMethod Model() As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.embed_model()
}

ClassMethod Criteria(briefJSON As %String) As %String [ Language = python ]
{
from knos_iris import bridge
return bridge.criterion_text(briefJSON)
}

ClassMethod Score(a As %String, b As %String) As %Numeric [ Language = python ]
{
from knos_iris import bridge
x = [float(v) for v in bridge.embed(a, True).split(",")]
y = [float(v) for v in bridge.embed(b).split(",")]
return sum(p * q for p, q in zip(x, y))
}
}
