/// The referee's read tools as an AI Hub MCP service (%AI.MCP.Service), served at /mcp/knos for IRIS's own MCP
/// gateway (iris-mcp-server), which lists them at /v1/services and calls them at /v1/tool_call. The tools come from
/// one tool set (Knos.Iris.AI.RefereeToolSet); the web app is made by Knos.Iris.Setup as the MCP editor makes one.
Class Knos.Iris.AI.MCP Extends %AI.MCP.Service
{

Parameter SPECIFICATION = "Knos.Iris.AI.RefereeToolSet";

}
