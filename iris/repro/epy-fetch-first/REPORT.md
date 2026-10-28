**Embedded Python, build 154: iris.sql.exec with FETCH FIRST n ROWS ONLY (lead from the build spec, not reproduced)**

The lead: `iris.sql.exec("SELECT ... FETCH FIRST n ROWS ONLY")` ends the process with SIGSEGV. Tried on a clean
`irishealth-community:2026.3.0AI.154.0` container (`2026.3.0AI (Build 154U)`) through `%SYS.Python.Run` in an IRIS
session: the query returned its 3 rows, as `SELECT TOP 3` did, and the session lived. Not filed.
