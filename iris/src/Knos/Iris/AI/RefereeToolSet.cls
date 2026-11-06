/// The referee's read tools as one AI Hub tool set, the form the IRIS MCP gateway loads (Knos.Iris.AI.RefereeMCP)
Class Knos.Iris.AI.RefereeToolSet Extends %AI.ToolSet [ DependsOn = Knos.Iris.AI.RefereeTools ]
{

XData Definition [ MimeType = application/xml ]
{
<ToolSet Name="knos_referee">
  <Description>The Knos referee's read tools: a locked brief, a check run, an observation, a verdict, the nearest locked criteria. Each reads one thing and moves nothing.</Description>
  <Include Class="Knos.Iris.AI.RefereeTools"/>
</ToolSet>
}

}
