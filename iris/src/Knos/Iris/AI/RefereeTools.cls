/// The referee agent's tools: each reads one thing and moves nothing. GetBrief: the locked brief by its id or hash.
/// GetCheckRun: a check run's name, conclusion and id. GetObservation: an Observation's code, value and unit (an ORU
/// message turned into one). GetVerdict: a referee panel's verdict, read strictly. SearchCriteria: the locked
/// criteria nearest a text, by Vector Search over the brief's criteria (the RAG knowledge base).
Class Knos.Iris.AI.RefereeTools Extends %RegisteredObject
{

ClassMethod GetBrief(id As %String) As %String
{
    set b = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(id)
    return $select($isobject(b):b.BriefJSON, 1:"{""error"":""no brief is locked as "_id_"""}")
}

ClassMethod GetCheckRun(payload As %String) As %String
{
    set p = {}.%FromJSON(payload), cr = p."check_run"
    return:'$isobject(cr) "{}"
    return {"id": (cr.id), "name": (cr.name), "conclusion": (cr.conclusion), "head_sha": (cr."head_sha")}.%ToJSON()
}

ClassMethod GetObservation(kind As %String, payload As %String) As %String
{
    return $select(kind="oru":##class(Knos.Iris.Py.Verdict).ORUToObservation(payload), 1:payload)
}

ClassMethod GetVerdict(payload As %String) As %String
{
    return ##class(Knos.Iris.Py.Verdict).Read(payload)
}

ClassMethod SearchCriteria(briefHash As %String, text As %String) As %String
{
    set q = ##class(Knos.Iris.Py.Embed).Query($extract(text, 1, 4000)), out = []
    set rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT TOP 2 MKey, VECTOR_COSINE(Vec, TO_VECTOR(?, DOUBLE, 384)) AS Score FROM Knos_Iris_Data.Criterion WHERE BriefHash = ? ORDER BY Score DESC", q, briefHash)
    while rs.%Next() { do out.%Push({"key": (rs.MKey), "cosine": (+rs.Score)}) }
    return out.%ToJSON()
}

}
