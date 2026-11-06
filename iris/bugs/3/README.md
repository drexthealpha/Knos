# AI Hub: %AI.RAG.VectorStore.IRIS makes its table in SQLUser whatever its Schema says

Build: `IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.3.0AI (Build 154U)`.

```sh
bash iris/bugs/3/run.sh knos-iris
```

The store is given `Schema = "BugThree"` and `TableName = "VecThree"`, then `Build()`.

| | Expected | Actual |
|---|---|---|
| `Build()` | 1 | 1 |
| the object's `Schema` after `Build()` | `BugThree` | `BugThree` |
| the table made | `BugThree.VecThree` (and its config table) | `SQLUser.VecThree` and `SQLUser.VecThree_Config` |

The object still says `BugThree`, so nothing tells the caller where the vectors went. Two knowledge bases that use the
same table name in different schemas write into one table, and a `DROP TABLE BugThree.VecThree` (what the property
says) removes nothing. Seen first in Knos's own knowledge base (`Knos.Iris.AI.Hub`, `Rag`), which now names
`SQLUser` itself.
