"""Read a customer export on stdin, write the clean file on stdout (the rules are in TASK.md)."""
import csv
import io
import re
import sys
from datetime import date

COLUMNS = {"name": {"name", "full name", "customer"}, "email": {"email", "e-mail", "email address"},
           "signup_date": {"signup date", "signup_date", "date signed up"}, "amount": {"amount", "total", "amount (usd)"},
           "country": {"country", "country code"}}
COUNTRY = {"us": "US", "usa": "US", "united states": "US", "gb": "GB", "uk": "GB", "united kingdom": "GB",
           "great britain": "GB", "de": "DE", "germany": "DE", "deutschland": "DE", "fr": "FR", "france": "FR",
           "in": "IN", "india": "IN", "br": "BR", "brazil": "BR", "brasil": "BR"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def name(s: str) -> str:
    if "," in s:
        last, first = s.split(",", 1)
        s = f"{first} {last}"
    return " ".join(s.lower().split()).title()


def when(s: str) -> str:
    s = s.strip()
    if m := re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s):
        y, mo, d = m.groups()
    elif m := re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s):
        y, mo, d = m.groups()
    elif m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):
        mo, d, y = m.groups()
    elif m := re.fullmatch(r"(\d{1,2}) ([A-Za-z]+) (\d{4})", s):
        d, mo, y = m.groups()
        mo = MONTHS[next(k for k in MONTHS if k.startswith(mo.lower()[:3]))]
    elif m := re.fullmatch(r"([A-Za-z]+) (\d{1,2}), (\d{4})", s):
        mo, d, y = m.groups()
        mo = MONTHS[mo.lower()]
    else:
        raise ValueError(f"cannot read the date {s!r}")
    return date(int(y), int(mo), int(d)).isoformat()


def amount(s: str) -> str:
    return f"{float(re.sub(r'[^0-9.]', '', s)):.2f}"


def main() -> None:
    text = sys.stdin.buffer.read().decode("utf-8-sig")
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    head = [h.strip().lower() for h in rows[0]]
    at = {key: next(i for i, h in enumerate(head) if h in names) for key, names in COLUMNS.items()}
    out, seen = [], set()
    for r in rows[1:]:
        email = r[at["email"]].strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        out.append([name(r[at["name"]]), email, when(r[at["signup_date"]]), amount(r[at["amount"]]),
                    COUNTRY[r[at["country"]].strip().lower().replace(".", "")]])
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")    # lines end in \n on every system, as in the example
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["name", "email", "signup_date", "amount", "country"])
    w.writerows(out)


main()
