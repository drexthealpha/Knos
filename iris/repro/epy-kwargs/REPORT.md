**Embedded Python, build 154: iris.sql.exec with keyword arguments (lead from the build spec, not reproduced)**

The lead: `iris.sql.exec` with keyword arguments crashes "on some builds". Tried on a clean
`irishealth-community:2026.3.0AI.154.0` container (`2026.3.0AI (Build 154U)`): `iris.sql.exec(query, name='%AI')` raised
`TypeError: exec() takes no keyword arguments` and the process lived; positional arguments work. Not filed: a clear
TypeError is the documented behaviour.
