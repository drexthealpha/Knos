/// Locks a brief: Knos's Ready check (knos.ready) in Embedded Python, the criteria hash, one vector row per milestone.
Class Knos.Iris.BO.BriefLock Extends Ens.BusinessOperation
{
Method Lock(pRequest As Knos.Iris.Msg.Brief, Output pResponse As Knos.Iris.Msg.Locked) As %Status
{
    set pResponse = ##class(Knos.Iris.Msg.Locked).%New()
    set pResponse.BriefId = pRequest.BriefId
    set r = {}.%FromJSON(##class(Knos.Iris.Py.Ready).Check(pRequest.BriefJSON))
    set pResponse.Ready = r.ready, pResponse.Missing = r.missing.%ToJSON()
    if 'r.ready return $$$OK
    set pResponse.CriteriaHash = r."criteria_hash"
    return ##class(Knos.Iris.BO.BriefLock).Store(pRequest.BriefId, pRequest.BriefJSON, r."criteria_hash", pRequest.AmountUSDC)
}

/// The brief and its criteria (with their embeddings): a re-lock replaces both
ClassMethod Store(id As %String, json As %String, hash As %String, amount As %Numeric) As %Status
{
    set b = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(id)
    set:'$isobject(b) b = ##class(Knos.Iris.Data.Brief).%New()
    set b.BriefId = id, b.BriefJSON = json, b.CriteriaHash = hash, b.AmountUSDC = amount
    set sc = b.%Save() quit:$$$ISERR(sc) sc
    &sql(DELETE FROM Knos_Iris_Data.Criterion WHERE BriefHash = :hash)
    set lines = ##class(Knos.Iris.Py.Embed).Criteria(json)
    for i = 1:1:$length(lines, $char(10)) {
        set line = $piece(lines, $char(10), i) continue:line=""
        set key = $piece(line, "|", 1), txt = $piece(line, "|", 2, *), vec = ##class(Knos.Iris.Py.Embed).Vector(txt)
        &sql(INSERT INTO Knos_Iris_Data.Criterion (BriefHash, MKey, Txt, Vec) VALUES (:hash, :key, :txt, TO_VECTOR(:vec, DOUBLE, 384)))
        if SQLCODE < 0 return $$$ERROR($$$SQLError, SQLCODE, $get(%msg))
    }
    return $$$OK
}

XData MessageMap
{
<MapItems>
<MapItem MessageType="Knos.Iris.Msg.Brief"><Method>Lock</Method></MapItem>
</MapItems>
}
}
