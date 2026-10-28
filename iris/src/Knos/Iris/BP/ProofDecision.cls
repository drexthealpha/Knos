/// The decision for one proof: the brief's hash against its lock (no AI), the referee, the payout gate, a person's
/// approval when the gate asks for one (Workflow), then Solana. Every step is a message in the session's Visual Trace.
Class Knos.Iris.BP.ProofDecision Extends Ens.BusinessProcessBPL
{
XData BPL [ XMLNamespace = "http://www.intersystems.com/bpl" ]
{
<process language='objectscript' request='Knos.Iris.Msg.Proof' response='Knos.Iris.Msg.Decision' height='2000' width='2000'>
<context>
<property name='Locked' type='%String' instantiate='0'><parameters><parameter name='MAXLEN' value='64'/></parameters></property>
<property name='Hash' type='%String' instantiate='0'><parameters><parameter name='MAXLEN' value='64'/></parameters></property>
<property name='Verdict' type='Knos.Iris.Msg.Verdict' instantiate='0'/>
<property name='Gate' type='%String' instantiate='0'/>
<property name='Kind' type='%String' instantiate='0'/>
<property name='Threshold' type='%Numeric' instantiate='0'/>
<property name='Slot' type='%String' instantiate='0'><parameters><parameter name='MAXLEN' value=''/></parameters></property>
</context>
<sequence>
<code name='The brief, as locked'><![CDATA[
 set b = ##class(Knos.Iris.Data.Brief).BriefIdIdxOpen(request.BriefId)
 set context.Locked = $select($isobject(b):b.CriteriaHash,1:"")
 set context.Hash = ##class(Knos.Iris.Py.Ready).Hash(request.BriefJSON)
 set context.Kind = $select(request.Kind="checkrun":"machine",1:"human")
 set context.Threshold = +##class(Ens.Util.FunctionSet).Lookup("KnosPayoutThreshold","usdc",50)
 set s = ##class(Knos.Iris.Msg.Span).%New(), s.Kind = "policy", s.Name = "brief hash against its lock"
 set s.InputJSON = "{""locked"":"""_context.Locked_"""}", s.OutputJSON = "{""presented"":"""_context.Hash_""",""equal"":"_$select(context.Hash=context.Locked:"true",1:"false")_"}"
 do ..%Process.SendRequestAsync("TraceSink", s, 0)
]]></code>
<if condition='(context.Hash=context.Locked)&amp;&amp;(context.Locked&apos;="")'>
<true>
<scope>
<call name='Referee' target='Referee' async='0'>
<request type='Knos.Iris.Msg.Proof'><assign property='callrequest' value='request' action='set'/></request>
<response type='Knos.Iris.Msg.Verdict'><assign property='context.Verdict' value='callresponse' action='set'/></response>
</call>
<faulthandlers>
<catchall>
<assign property='context.Verdict' value='##class(Knos.Iris.Msg.Verdict).%New()' action='set'/>
<assign property='context.Verdict.Decision' value='"insufficient"' action='set'/>
</catchall>
</faulthandlers>
</scope>
<code name='Vector guard'><![CDATA[
 set q = ##class(Knos.Iris.Py.Embed).Vector($extract(request.PayloadJSON, 1, 4000))
 set h = context.Locked, key = "", score = 0
 &sql(SELECT TOP 1 MKey, VECTOR_COSINE(Vec, TO_VECTOR(:q, DOUBLE, 384)) INTO :key, :score FROM Knos_Iris_Data.Criterion WHERE BriefHash = :h ORDER BY VECTOR_COSINE(Vec, TO_VECTOR(:q, DOUBLE, 384)) DESC)
 set s = ##class(Knos.Iris.Msg.Span).%New(), s.Kind = "rag", s.Name = "nearest locked criterion", s.Score = +score
 set s.OutputJSON = "{""milestone"":"""_key_""",""cosine"":"_(+score)_"}"
 do ..%Process.SendRequestAsync("TraceSink", s, 0)
]]></code>
<assign property='context.Gate' value='##class(Knos.Iris.Rule.PayoutGate).Decide(context.Verdict.Decision,context.Verdict.Confidence,request.AmountUSDC,context.Threshold,context.Kind,1)' action='set'/>
</true>
<false>
<assign property='context.Gate' value='"REJECT"' action='set'/>
<assign property='context.Verdict' value='##class(Knos.Iris.Msg.Verdict).%New()' action='set'/>
<assign property='context.Verdict.Decision' value='"reject: brief altered"' action='set'/>
</false>
</if>
<code name='The answer'><![CDATA[
 set response.BriefId = request.BriefId, response.Decision = context.Verdict.Decision, response.Gate = context.Gate
 set response.Confidence = context.Verdict.Confidence, response.Reason = context.Verdict.MilestonesJSON, response.SessionId = ..%Process.%SessionId
 set response.Outcome = $case(context.Gate, "PAY":"pay: the relayer may send the signed pay instruction", "HUMAN":"held: waiting for an approver",
   "REFUND_AT_DEADLINE":"not met: refunded to the funder at the deadline", :"rejected: the brief no longer matches its lock")
 set s = ##class(Knos.Iris.Msg.Span).%New(), s.Kind = "rule", s.Name = "PayoutGate", s.OutputJSON = "{""gate"":"""_context.Gate_"""}"
 set s.InputJSON = "{""decision"":"""_context.Verdict.Decision_""",""confidence"":"_(+context.Verdict.Confidence)_",""amount"":"_(+request.AmountUSDC)_",""threshold"":"_context.Threshold_",""kind"":"""_context.Kind_"""}"
 do ..%Process.SendRequestAsync("TraceSink", s, 0)
 set d = ##class(Knos.Iris.Data.Decision).%New(), d.SessionId = response.SessionId, d.BriefId = request.BriefId, d.Kind = request.Kind
 set d.Decision = response.Decision, d.Gate = response.Gate, d.Outcome = response.Outcome, d.Confidence = response.Confidence, d.Reason = $extract(response.Reason, 1, 2000)
 do d.%Save()
]]></code>
<reply/>
<switch>
<case condition='context.Gate="HUMAN"'>
<call name='Approve' target='PayoutApprovers' async='1'>
<request type='EnsLib.Workflow.TaskRequest'>
<assign property='callrequest.%Subject' value='"Pay "_request.BriefId_" ("_request.AmountUSDC_" USDC)?"' action='set'/>
<assign property='callrequest.%Message' value='context.Verdict.MilestonesJSON_" Trace: /csp/healthshare/knos/EnsPortal.VisualTrace.zen?SESSIONID="_..%Process.%SessionId' action='set'/>
<assign property='callrequest.%Actions' value='"Approve,Reject"' action='set'/>
</request>
<response type='EnsLib.Workflow.TaskResponse'>
<assign property='context.Gate' value='$select(callresponse.%Action="Approve":"PAY",1:"HELD")' action='set'/>
</response>
</call>
<sync name='Wait for the approver' calls='Approve' timeout='"P2D"' type='all'/>
</case>
</switch>
<if condition='context.Gate="PAY"'>
<true>
<call name='Devnet slot' target='SolanaRead' async='0'>
<request type='Knos.Iris.Msg.RpcRequest'><assign property='callrequest.Method' value='"getSlot"' action='set'/></request>
<response type='Knos.Iris.Msg.RpcResponse'><assign property='context.Slot' value='callresponse.ResultJSON' action='set'/></response>
</call>
<code name='Chain span'><![CDATA[
 set s = ##class(Knos.Iris.Msg.Span).%New(), s.Kind = "chain", s.Name = "devnet slot before the relay", s.OutputJSON = $extract(context.Slot, 1, 2000)
 do ..%Process.SendRequestAsync("TraceSink", s, 0)
]]></code>
</true>
</if>
</sequence>
</process>
}
}
