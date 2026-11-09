# Embedded Python: iris.sql.exec with an int past 64 bits fails with SystemError

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

Build: `IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.3.0AI (Build 154U)`, Python 3.12.3.

```sh
bash iris/bugs/4/run.sh knos-iris
```

`iris.sql.exec("SELECT ? AS x", v)` from a `[ Language = python ]` method:

| `v` | Expected | Actual |
|---|---|---|
| `5` | 5 | 5 |
| `2**63 - 1` | 9223372036854775807 | 9223372036854775807 |
| `2**63` | the value, or an `OverflowError` naming it | `SystemError: <built-in method exec of iris.%SYS.Python.SQL object at 0x...> returned a result with an exception set` |
| `2**64`, `10**20` | the same | the same `SystemError` |
| `-2**63 - 1` | the same | the same `SystemError` |

`SystemError: ... returned a result with an exception set` is CPython saying the C function behind `iris.sql.exec`
returned a value while a Python exception was pending, which is a fault in that function, not in the caller's code.
The message names neither the parameter nor its value, so a caller cannot tell which argument to fix. The same values
returned from a Python method arrive in ObjectScript as -1 ([bug 1](../1/README.md)); this one is the SQL path, where
the binding fails instead.
