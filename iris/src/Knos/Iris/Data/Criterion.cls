/// One milestone of a locked brief with its embedding (VECTOR(FLOAT,384)), for the vector search.
Class Knos.Iris.Data.Criterion Extends %Persistent
{
Property BriefHash As %String(MAXLEN = 64);
Property MKey As %String(MAXLEN = 64);
Property Txt As %String(MAXLEN = 2000);
Property Vec As %Vector(DATATYPE = "DOUBLE", LEN = 384);
Index BriefHashIdx On BriefHash;
Storage Default
{
<Type>%Storage.Persistent</Type>
}
}
