"""Turn a customer export read on stdin into the clean file TASK.md describes.

Written as one small function per column, each trying the shapes TASK.md lists in turn, with the standard library's
date and decimal types instead of regular expressions."""
import csv
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

HEADERS = {
    "name": ("name", "full name", "customer"),
    "email": ("email", "e-mail", "email address"),
    "signup_date": ("signup date", "signup_date", "date signed up"),
    "amount": ("amount", "total", "amount (usd)"),
    "country": ("country", "country code"),
}
DATE_SHAPES = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y", "%Y%m%d")
COUNTRIES = {
    "US": ("us", "usa", "united states"),
    "GB": ("gb", "uk", "united kingdom", "great britain"),
    "DE": ("de", "germany", "deutschland"),
    "FR": ("fr", "france"),
    "IN": ("in", "india"),
    "BR": ("br", "brazil", "brasil"),
}


def clean_name(raw: str) -> str:
    if "," in raw:
        family, given = raw.split(",", 1)
        raw = given + " " + family
    out, start_of_word = [], True
    for ch in " ".join(raw.split()):
        out.append(ch.upper() if start_of_word else ch.lower())
        start_of_word = ch in " -'"
    return "".join(out)


def clean_email(raw: str) -> str:
    return "".join(raw.split()).lower()


def clean_date(raw: str) -> str:
    text = " ".join(raw.split())
    for shape in DATE_SHAPES:
        try:
            return datetime.strptime(text, shape).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"cannot read the date {raw!r}")


def clean_amount(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == ".")
    return str(Decimal(digits).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def clean_country(raw: str) -> str:
    key = " ".join(raw.replace(".", "").lower().split())
    for code, spellings in COUNTRIES.items():
        if key in spellings:
            return code
    raise ValueError(f"unknown country {raw!r}")


def main() -> None:
    text = sys.stdin.buffer.read().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    rows = [row for row in csv.reader(text.split("\n")) if any(cell.strip() for cell in row)]
    header = [cell.strip().lower() for cell in rows[0]]
    column = {field: next(header.index(h) for h in spellings if h in header) for field, spellings in HEADERS.items()}
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(list(HEADERS))
    emails = set()
    for row in rows[1:]:
        row = row + [""] * (len(header) - len(row))
        email = clean_email(row[column["email"]])
        if email == "" or email in emails:
            continue
        emails.add(email)
        writer.writerow([clean_name(row[column["name"]]), email, clean_date(row[column["signup_date"]]),
                         clean_amount(row[column["amount"]]), clean_country(row[column["country"]])])


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
main()
