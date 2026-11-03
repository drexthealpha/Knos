#!/bin/sh
# Run by iris-main right after IRIS starts (docker-compose.yml: --after): the predefined accounts take the password in
# IRIS_PASSWORD, so the image's SYS is refused on 52773 and 1972. Without IRIS_PASSWORD the container does not start
# (docker-compose.yml requires it). The value is read from the environment inside IRIS and never printed.
[ -n "$IRIS_PASSWORD" ] || { echo "IRIS_PASSWORD is empty: refusing to keep the image's default password" >&2; exit 1; }
printf '%s\n' 'zn "%SYS"' \
  'set p("Password") = $system.Util.GetEnviron("IRIS_PASSWORD"), p("ChangePassword") = 0' \
  'for u = "_SYSTEM", "SuperUser", "Admin" { set sc = ##class(Security.Users).Modify(u, .p) write u, " ", $select(sc:"set", 1:$system.Status.GetErrorText(sc)), ! }' \
  'halt' | iris session IRIS -U %SYS
