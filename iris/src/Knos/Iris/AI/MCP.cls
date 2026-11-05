/// The referee's read tools as an AI Hub MCP service (%AI.MCP.Service): the IRIS MCP gateway lists them at /v1/services
/// and calls them at /v1/tool_call, under the referee's authorization policy (Knos.Iris.AI.ToolPolicy).
Class Knos.Iris.AI.MCP Extends %AI.MCP.Service
{

Parameter SPECIFICATION = "Knos.Iris.AI.RefereeTools";

}
