/// The AI Hub features the referee uses, each run live and answered as JSON (GET /api/knos/aihub/<feature>):
/// skill (a skill folder, %AI.Agent.Skill, attached with UseSkill), policy (%AI.Policy.Authorization on the referee's
/// tools: one call allowed, one refused), mcp (the tools as %AI.MCP.Service lists and routes them), rag
/// (%AI.RAG.KnowledgeBase over the brief's criteria, searched), stats (%AI.Agent.Session GetStats after one local
/// model turn) and workflow (the Workflow tasks waiting for a person, answered on /knos/). With ?brief=<id>, each one
/// runs on that decision's brief: the /knos/ page shows the six for the decision chosen there.
Class Knos.Iris.AI.Hub
{

ClassMethod Demo(feature As %String, brief As %String = "") As %DynamicObject
{
    set out = {"feature": (feature)}
    set:brief'="" out.brief = brief
    try {
        if feature = "skill" { do ..Skill(out) }
        elseif feature = "policy" { do ..Policy(out, brief) }
        elseif feature = "mcp" { do ..Mcp(out, brief) }
        elseif feature = "rag" { do ..Rag(out, brief) }
        elseif feature = "stats" { do ..Stats(out, brief) }
        elseif feature = "workflow" { do ..Workflow(out, brief) }
        else { set out.error = "one of skill, policy, mcp, rag, stats, workflow" }
    } catch e {
        set out.error = e.DisplayString()
    }
    set out.ok = (out.error = "")
    return out
}

ClassMethod Agent() As Knos.Iris.AI.LocalReferee
{
    set a = ##class(Knos.Iris.AI.LocalReferee).%New()
    set base = $system.Util.GetEnviron("KNOS_LOCAL_LLM_URL")
    set:base="" base = "http://ollama:11434/v1"
    set a.Provider = ##class(%AI.Provider).Create("openai", {"base_url": (base), "api_key": "none"})
    set a.Model = ##class(Knos.Iris.AI.Referee).LocalModel(), a.Temperature = 0
    return a
}

ClassMethod SkillPath() As %String
{
    set home = $system.Util.GetEnviron("KNOS_IRIS_HOME")
    set:home="" home = "/home/irisowner/knos"
    return home_"/iris/skills/knos-proof"
}

ClassMethod Skill(out As %DynamicObject)
{
    set out.class = "%AI.Agent.Skill, %AI.Agent.UseSkill"
    set sk = ##class(%AI.Agent.Skill).GetSkillFromURI(..SkillPath())
    set a = ..Agent()
    set sc = a.UseSkill(sk)
    set out.useskill = $select($$$ISOK(sc):"ok", 1:$system.Status.GetErrorText(sc))
    set s = a.CreateSession({"max_iterations": 1, "max_tokens": 40})
    set out.skill = {"name": (sk.Name), "description": (sk.Description), "path": (sk.Path)}
    set out."session_available_skills" = s.AvailableSkillsGet()
}

/// The brief's first milestone as one line ("" when the brief is not locked here)
ClassMethod FirstMilestone(brief As %String) As %String
{
    return:brief="" ""
    set b = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(brief)
    return:'$isobject(b) ""
    set m = {}.%FromJSON(b.BriefJSON).milestones
    return:'$isobject(m) ""
    set m = m.%Get(0)
    return $select($isobject(m):m.key_": "_m.name_". "_m.target, 1:"")
}

ClassMethod Policy(out As %DynamicObject, brief As %String = "")
{
    set out.class = "%AI.Policy.Authorization (Knos.Iris.AI.ToolPolicy), %AI.ToolMgr"
    set mgr = ##class(%AI.ToolMgr).%New()
    $$$ThrowOnError(mgr.RegisterToolSet("Knos.Iris.AI.RefereeTools"))
    $$$ThrowOnError(mgr.AuthPolicySet(##class(Knos.Iris.AI.ToolPolicy).%New()))
    set names = [], it = mgr.%Discover().%GetIterator()
    while it.%GetNext(, .t) { do names.%Push(t.name) }
    set out.tools = names
    set cr = ..Named(names, "GetCheckRun"), vd = ..Named(names, "GetVerdict"), gb = ..Named(names, "GetBrief")
    if brief '= "" { set out.allowed = {"tool": (gb), "arguments": {"id": (brief)}, "answer": (..Run(mgr, gb, {"id": (brief)}))} }
    else {
        set payload = {"check_run": {"id": 4242004, "name": "unit", "conclusion": "success"}}.%ToJSON()
        set out.allowed = {"tool": (cr), "answer": (..Run(mgr, cr, {"payload": (payload)}))}
    }
    set big = "", $piece(big, "x", 30001) = ""
    set out.refused = {"tool": (vd), "arguments_characters": ($length(big)), "answer": (..Run(mgr, vd, {"payload": (big)}))}
}

ClassMethod Mcp(out As %DynamicObject, brief As %String = "")
{
    set out.class = "%AI.MCP.Service (Knos.Iris.AI.MCP)"
    set spec = ##class(Knos.Iris.AI.MCP).#SPECIFICATION
    set out.specification = spec
    set mgr = ##class(%AI.ToolMgr).%New()
    set sc = ##class(Knos.Iris.AI.MCP).LoadToolSetsToManager(mgr, spec)
    set out.load = $select($$$ISOK(sc):"ok", 1:$system.Status.GetErrorText(sc))
    do mgr.AuthPolicySet(##class(Knos.Iris.AI.ToolPolicy).%New())
    set names = [], it = mgr.%Discover().%GetIterator()
    while it.%GetNext(, .t) { do names.%Push(t.name) }
    set out.tools = names
    set out.served = "/mcp/knos/v1/services (the list) and /mcp/knos/v1/tool_call (a call), for the IRIS MCP gateway"
    set out.app = ##class(Knos.Iris.AI.Hub).App("/mcp/knos")
    // one call of a tool the service serves, through its own tool manager (the gateway calls the same tool)
    set gb = ..Named(names, "GetBrief")
    set:brief'="" out.call = {"tool": (gb), "arguments": {"id": (brief)}, "answer": (..Run(mgr, gb, {"id": (brief)}))}
}

ClassMethod Rag(out As %DynamicObject, brief As %String = "")
{
    set out.class = "%AI.RAG.KnowledgeBase, %AI.RAG.Embedding.FastEmbed, %AI.RAG.VectorStore.IRIS"
    set emb = ##class(%AI.RAG.Embedding.FastEmbed).Create()
    // built afresh on every call: the knowledge base holds exactly the briefs locked now
    do ##class(%SQL.Statement).%ExecDirect(, "DROP TABLE IF EXISTS SQLUser.KnosCriteria")
    set vs = ##class(%AI.RAG.VectorStore.IRIS).%New()
    set vs.Schema = "SQLUser", vs.TableName = "KnosCriteria", vs.Dimensions = emb.Dimensions, vs.ModelName = emb.ModelName
    $$$ThrowOnError(vs.Build())
    set kb = ##class(%AI.RAG.KnowledgeBase).%New("knos_criteria", "The criteria of the briefs locked in this IRIS")
    $$$ThrowOnError(kb.Build(emb, vs))
    // every locked brief's milestones, one document each
    set docs = [], briefs = 0, rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT TOP 50 BriefId, BriefJSON FROM Knos_Iris_Data.Brief")
    set:rs.%SQLCODE<0 out.sql = rs.%Message
    while rs.%Next() {
        set briefs = briefs + 1, b = {}.%FromJSON(rs.BriefJSON), ms = $select($isobject(b.milestones):b.milestones, 1:[]), it = ms.%GetIterator()
        while it.%GetNext(, .m) { do docs.%Push([(m.key_": "_m.name_". "_m.target), {"brief": (rs.BriefId), "key": (m.key)}]) }
    }
    set out.briefs = briefs
    set out.documents = $select(docs.%Size():kb.AddDocuments(docs), 1:0)
    set mgr = ##class(%AI.ToolMgr).%New()
    $$$ThrowOnError(kb.AddToManager(mgr))
    set names = [], it = mgr.%Discover().%GetIterator()
    while it.%GetNext(, .t) { do names.%Push(t.name) }
    set out.tools = names
    set q = ..FirstMilestone(brief)
    set:q="" q = "does a passing unit test meet the milestone"
    set out.query = q
    set out.answer = ..Run(mgr, names.%Get(0), {"query": (q)})
}

ClassMethod Stats(out As %DynamicObject, brief As %String = "")
{
    set out.class = "%AI.Agent.Session.GetStats"
    set a = ..Agent(), s = a.CreateSession({"max_iterations": 1, "max_tokens": 40})
    set m = ..FirstMilestone(brief)
    set r = a.Chat(s, $select(m'="":"In ten words: what proof meets this milestone? "_m, 1:"In five words: what does a referee check?"))
    set out.model = a.Model
    set out.reply = $select($isobject(r):r.Content, 1:r)
    set out.stats = s.GetStats()
}

ClassMethod Workflow(out As %DynamicObject, brief As %String = "")
{
    set out.class = "EnsLib.Workflow (role PayoutApprovers)"
    set tasks = [], rs = ##class(%SQL.Statement).%ExecDirect(, "SELECT TOP 50 ID, TaskStatus_Request->%Subject AS Subject, TaskStatus_IsComplete AS Done, %Action AS Action FROM EnsLib_Workflow.TaskResponse ORDER BY ID DESC")
    while rs.%Next() { do:(brief=""||(rs.Subject[(brief_" ("))) tasks.%Push({"task": (rs.ID), "subject": (rs.Subject), "done": (+rs.Done), "action": (rs.Action)}) }
    set out.tasks = tasks
    set out.answer = "Approve or Reject on /knos/ (the inbox) or in Interoperability > Workflow Inbox"
}

/// A web application's dispatch class and whether it is enabled, read in %SYS
ClassMethod App(name As %String) As %DynamicObject
{
    set ns = $namespace, out = {}
    try {
        zn "%SYS"
        if ##class(Security.Applications).Exists(name, .app) { set out.dispatch = app.DispatchClass, out.enabled = +app.Enabled }
        else { set out.missing = 1 }
    } catch e { set out.error = e.DisplayString() }
    zn ns
    return out
}

ClassMethod Named(names As %DynamicArray, short As %String) As %String
{
    set it = names.%GetIterator()
    while it.%GetNext(, .n) { return:($piece($piece(n, ".", *), ":", *) = short) n }
    return short
}

ClassMethod Run(mgr As %AI.ToolMgr, name As %String, args As %DynamicObject) As %DynamicObject
{
    try {
        set r = mgr.ExecuteTool(name, args)
        return $select($isobject(r):r, 1:{"result": (r)})
    } catch e {
        return {"refused": (e.DisplayString())}
    }
}

}
