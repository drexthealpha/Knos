"""The daily reminder a person asks for after their first result (L23): one calendar file (iCalendar, RFC 5545) with
one event that repeats every day at the time the person chose, opening straight to the check. Knos sends nothing: the
person's own calendar reminds them, and only because they asked for the file.

    GET /api/remind.ics?at=08:00&cue=coffee     at: the time, 24-hour HH:MM (08:00 when not given, the morning slot
                                                 suggested); cue: "coffee" adds "after my coffee" to the event
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re

CUES = {"": "", "coffee": "after my coffee"}
DEFAULT_AT = "08:00"     # the suggested morning slot (DISTRIBUTION/D2.md:40); the person picks any other time


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 section 3.1: lines longer than 75 octets go on in a line that starts with one space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 75:
            out.append(cur.decode("utf-8"))
            cur = b" " + b
        else:
            cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def ics(at: str, cue: str, link: str, today: dt.date | None = None) -> str:
    """The reminder file: a daily event at `at` (the person's own local time: a floating time, so it follows their
    clock), from tomorrow, with the check's link in it and a reminder at the event's start."""
    at = (at or DEFAULT_AT).strip()
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", at)
    if not m:
        raise ValueError("I need the time as hours and minutes, such as 08:00, to make the reminder.")
    if cue not in CUES:
        raise ValueError("I know one cue, after my coffee, so I made no reminder.")
    hh, mm = int(m.group(1)), int(m.group(2))
    start = (today or dt.date.today()) + dt.timedelta(days=1)
    when = f"{start:%Y%m%d}T{hh:02d}{mm:02d}00"
    title = "Knos: your daily check" + (f", {CUES[cue]}" if CUES[cue] else "")
    uid = hashlib.sha256(f"{at}|{cue}|{link}".encode()).hexdigest()[:24] + "@knos"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Knos//Daily check//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"DTSTART:{when}", "DURATION:PT5M", "RRULE:FREQ=DAILY",
             f"SUMMARY:{_esc(title)}", f"DESCRIPTION:{_esc('Check one file against its limit: ' + link)}", f"URL:{link}",
             "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(title)}", "TRIGGER:PT0M", "END:VALARM",
             "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"
