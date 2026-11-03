# Embedded Python: an int past 64 bits arrives in ObjectScript as -1

Build: `IRIS for UNIX (Ubuntu Server LTS for x86-64 Containers) 2026.3.0AI (Build 154U)`, Python 3.12.3.

```sh
bash iris/bugs/1/run.sh knos-iris
```

| Python value | Expected in ObjectScript | Actual |
|---|---|---|
| `2**63 - 1` | 9223372036854775807 | 9223372036854775807 |
| `2**63` | 9223372036854775808 (or an error) | -1 |
| `2**64` | 18446744073709551616 (or an error) | -1 |
| `-2**63 - 1` | -9223372036854775809 (or an error) | -1 |
| a `[ Language = python ]` method returning `2**63` | 9223372036854775808 (or an error) | -1 |

No error is raised, so code that reads a large id, an amount in base units or a hash as an integer carries on with -1.
