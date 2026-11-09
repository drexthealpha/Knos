# AI Hub: ExecuteTool runs a tool with arguments its own schema refuses

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

Build: `IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.3.0AI (Build 154U)`.

```sh
bash iris/bugs/2/run.sh knos-iris
```

`%AI.ToolMgr` advertises the tool `Echo(text As %String)` as `{"properties":{"text":{"type":"string"}},"required":["text"]}`.

| Arguments to `ExecuteTool("Echo", ...)` | Expected | Actual |
|---|---|---|
| `{}` | refused: `text` is required | runs with `text=""` |
| `{"other":1}` | refused: `text` is required | runs with `text=""` |
| `{"text":[1,2]}` | refused: not a string | runs with `text="9@%Library.DynamicArray"` |
| `{"text":{"a":1}}` | refused: not a string | runs with `text="7@%Library.DynamicObject"` |
| `{"text":18446744073709551616}` | refused, or the exact digits | runs with `text="18446744073709552000"` |

A model that leaves out an argument, or sends the wrong type, gets an answer computed from an empty string or an object
reference instead of an error it could correct.
