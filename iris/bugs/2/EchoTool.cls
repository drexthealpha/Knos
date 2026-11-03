/// Build 2026.3.0AI.154.0: %AI.ToolMgr.ExecuteTool runs a tool with arguments its own advertised schema refuses.
Class Knos.Bugs.EchoTool Extends %AI.Tool
{

/// Echoes the text it was given
ClassMethod Echo(text As %String) As %String
{
    return "text=["_text_"]"
}

/// What the tool manager advertises for Echo, then what ExecuteTool does with arguments that schema refuses
ClassMethod Run()
{
    set m = ##class(%AI.ToolMgr).%New(), sc = m.RegisterToolSet("Knos.Bugs.EchoTool"), bugs = 0
    if 'sc { write "RESULT=SETUP FAILED ", $system.Status.GetErrorText(sc), ! return }
    set st = m.GetToolStatuses().%Get(0)
    write "schema of ", st.name, ": ", st.parameters.%ToJSON(), !
    for args = "{}", "{""other"":1}", "{""text"":[1,2]}", "{""text"":{""a"":1}}", "{""text"":18446744073709551616}" {
        try {
            set r = m.ExecuteTool("Echo", {}.%FromJSON(args))
            set bugs = bugs + 1
            write "BUG  ExecuteTool(""Echo"", ", args, ") ran the tool: ", r.value, !
        } catch e {
            write "ok   ExecuteTool(""Echo"", ", args, ") refused: ", $extract(e.DisplayString(), 1, 120), !
        }
    }
    write "RESULT=", $select(bugs:"REPRODUCED "_bugs, 1:"NOT REPRODUCED"), !
}

}
