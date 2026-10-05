"""One line for an incident report read on stdin: which service, how long, why, and what the team did.

Written without regular expressions: the report is cut into sentences, and each sentence is tried against the shapes
TASK.md lists (what comes before the fact, and what comes after it)."""
import sys

SERVICE_AND_MINUTES = [("The ", " outage lasted ", " minutes"),
                       (" and the fix, ", " was unavailable (", " minutes in total)"),
                       ("Customers could not reach ", " for ", " minutes")]
CAUSE = [("The root cause was ", ""), ("Investigation showed that ", " had triggered the failure"),
         ("The failure was traced to ", "")]
FIX = [("Engineers ", " and traffic recovered"), ("Service returned after the team ", ""), ("The fix: the team ", "")]


def sentences(text: str) -> list:
    """The report's sentences without their full stop. A stop inside a time or a number (03.31) does not end one."""
    out, start = [], 0
    flat = " ".join(text.split())
    for i, ch in enumerate(flat):
        if ch == "." and (i + 1 == len(flat) or flat[i + 1] == " "):
            out.append(flat[start:i].strip())
            start = i + 1
    if flat[start:].strip():
        out.append(flat[start:].strip())
    return out


def between(sentence: str, before: str, after: str):
    at = sentence.find(before) if before[0] == " " else (0 if sentence.startswith(before) else -1)
    if at == -1:
        return None
    rest = sentence[at + len(before):]
    if after == "":
        return rest
    return rest[:rest.rfind(after)] if after in rest and rest.endswith(after) else None


def main() -> None:
    service = minutes = cause = fix = None
    for s in sentences(sys.stdin.read()):
        for before, middle, after in SERVICE_AND_MINUTES:
            whole = between(s, before, after)
            if service is None and whole is not None and middle in whole:
                name, _, number = whole.rpartition(middle)
                if number.isdigit() and " " not in name:
                    service, minutes = name, number
        for before, after in CAUSE:
            if cause is None and between(s, before, after) is not None:
                cause = between(s, before, after)
        for before, after in FIX:
            if fix is None and between(s, before, after) is not None:
                fix = between(s, before, after)
    if None in (service, minutes, cause, fix):
        raise SystemExit("this report does not say the four things TASK.md says every report says")
    sys.stdout.buffer.write(f"{service} was down for {minutes} minutes because of {cause}. The team {fix}.\n".encode("utf-8"))


main()
