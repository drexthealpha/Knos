/// I3: one method per bonus row of the build spec, each answering JSON with what it saw (iris/tests/test_iris_bonuses.py reads them).
Class Knos.Iris.Test.Bonuses
{
/// Embedded Python: Knos's hash inside IRIS equals the golden one made by Knos outside it; a vague brief lists what is missing
ClassMethod Python() As %String
{
    set dir = ##class(Knos.Iris.Util).Home()_"iris/fixtures/briefs/"
    set golden = {}.%FromJSON(..File(dir_"golden.json"))
    set h = ##class(Knos.Iris.Py.Ready).Hash(..File(dir_"code.json"))
    set v = {}.%FromJSON(##class(Knos.Iris.Py.Ready).Check(..File(dir_"vague.json")))
    return {"hash": (h), "golden": (golden.code."criteria_hash"), "equal": (h = golden.code."criteria_hash"), "vague_missing": (v.missing.%Size())}.%ToJSON()
}

/// Vector Search: three milestones locked, three queries, each one's nearest criterion and its cosine
ClassMethod Vector() As %String
{
    set brief = ..File(##class(Knos.Iris.Util).Home()_"iris/fixtures/briefs/three.json")
    set hash = ##class(Knos.Iris.Py.Ready).Hash(brief)
    set sc = ##class(Knos.Iris.BO.BriefLock).Store("vector-test", brief, hash, 10)
    if $$$ISERR(sc) return {"error": ($system.Status.GetErrorText(sc))}.%ToJSON()
    set out = [], qs = {"m1": "checkout latency p95 test result", "m2": "error rate of the payment api in production", "m3": "accessibility score of the signup page"}
    set it = qs.%GetIterator()
    while it.%GetNext(.want, .q) {
        set v = ##class(Knos.Iris.Py.Embed).Query(q)
        &sql(SELECT TOP 1 MKey, VECTOR_COSINE(Vec, TO_VECTOR(:v, DOUBLE, 384)) INTO :key, :score FROM Knos_Iris_Data.Criterion WHERE BriefHash = :hash ORDER BY VECTOR_COSINE(Vec, TO_VECTOR(:v, DOUBLE, 384)) DESC)
        do out.%Push({"query": (q), "want": (want), "top": ($get(key)), "cosine": (+$get(score)), "sqlcode": (SQLCODE)})
    }
    return out.%ToJSON()
}

/// Custom adapters: SolanaRpcOutbound answers getVersion from devnet
ClassMethod Rpc() As %String
{
    set a = ##class(Knos.Iris.Adapter.SolanaRpcOutbound).%New()
    set sc = a.Call("getVersion", "[]", .out)
    return {"ok": ($$$ISOK(sc)), "answer": ($extract($get(out), 1, 200)), "error": ($select($$$ISERR(sc):$system.Status.GetErrorText(sc), 1:""))}.%ToJSON()
}

/// Java PEX: a transaction built by Knos's code, simulated on devnet through SolanaSubmit (the PEX operation)
ClassMethod PEX() As %String
{
    set tx = ##class(Knos.Iris.Test.Bonuses).Memo()
    set m = ##class(Knos.Iris.Msg.SignedTx).%New(), m.TxB64 = tx, m.Mode = "simulate", m.Kind = "memo"
    set sc = ##class(Ens.Director).CreateBusinessService("ProofIn", .svc)
    if $$$ISERR(sc) return {"error": ($system.Status.GetErrorText(sc))}.%ToJSON()
    if '$isobject($get(svc)) return {"error": "no business service ProofIn"}.%ToJSON()
    set sc = svc.SendRequestSync("SolanaSubmit", m, .r, 120)
    if $$$ISERR(sc) || '$isobject($get(r)) return {"error": ($select($$$ISERR(sc):$system.Status.GetErrorText(sc), 1:"no reply"))}.%ToJSON()
    return {"class": ($classname(r)), "json": ($select(r.%IsA("EnsLib.PEX.Message"):r.%jsonObject.%ToJSON(), 1:""))}.%ToJSON()
}

/// A one-instruction transaction (the memo program, signed by a throwaway key) for the simulation
ClassMethod Memo() As %String [ Language = python ]
{
import base64
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from solders.message import Message
from solders.transaction import Transaction
from solders.hash import Hash
k = Keypair()
memo = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
ix = Instruction(memo, b"knos iris pex", [])
tx = Transaction([k], Message([ix], k.pubkey()), Hash.default())
return base64.b64encode(bytes(tx)).decode()
}

/// Workflow: the approver tasks for PayoutApprovers, and their actions
ClassMethod Workflow() As %String
{
    set out = []
    set rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT TOP 5 ID, %RoleName, %Status, %Subject FROM EnsLib_Workflow.TaskResponse ORDER BY ID DESC")
    while rs.%Next() { do out.%Push({"id": (rs.ID), "role": (rs.%RoleName), "status": (rs.%Status), "subject": (rs.%Subject)}) }
    return out.%ToJSON()
}

/// Community idea 689: the spans of one session, and the Langfuse-style view's tokens and cost
ClassMethod Trace(sid As %Integer) As %String
{
    return ##class(Knos.Iris.Trace).Session(sid).%ToJSON()
}

ClassMethod File(path As %String) As %String
{
    set f = ##class(%Stream.FileCharacter).%New(), f.Filename = path
    return f.Read(1000000)
}
}
