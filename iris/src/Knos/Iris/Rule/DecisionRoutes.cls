/// Where a decision goes once it is made (the DecisionRouter item): every decision to the lab's receipt file and as a
/// FHIR Task; a final decision back to the lab's own system as HL7 (Knos.Iris.DT.DecisionToHL7). The money path is not
/// here: ProofDecision pays or asks a person before it sends the decision on.
Class Knos.Iris.Rule.DecisionRoutes Extends Ens.Rule.Definition
{
Parameter RuleAssistClass = "EnsLib.MsgRouter.RuleAssist";

XData RuleDefinition [ XMLNamespace = "http://www.intersystems.com/rule" ]
{
<ruleDefinition alias="" context="EnsLib.MsgRouter.RoutingEngine" production="Knos.Iris.Production">
<ruleSet name="Decision routes" effectiveBegin="" effectiveEnd="">
<rule name="Every decision: a receipt and a FHIR Task" disabled="false">
<constraint name="msgClass" value="Knos.Iris.Msg.Decision"></constraint>
<when condition="1">
<send transform="" target="ReceiptFile"></send>
<send transform="" target="DecisionFHIR"></send>
</when>
</rule>
<rule name="A final decision: back to the lab in HL7" disabled="false">
<constraint name="msgClass" value="Knos.Iris.Msg.Decision"></constraint>
<when condition="Document.Gate!=&quot;HUMAN&quot;">
<send transform="Knos.Iris.DT.DecisionToHL7" target="ResultHL7Out"></send>
</when>
</rule>
</ruleSet>
</ruleDefinition>
}
}
