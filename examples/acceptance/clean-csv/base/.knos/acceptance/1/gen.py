"""The messy customer exports of the clean-csv task: a clean table first, then a messy file made from it.

The expected answer is the clean table itself, so there is no cleaner here to copy: a submission has to undo the mess.
The mess is the one TASK.md lists (a buyer's own words); the draw is new on every run."""
import csv
import io
import random
from datetime import date, timedelta

FIRST = ["mary-jane", "john", "aisha", "li", "olga", "jean-luc", "d'arcy", "sofia", "tomas", "nora", "kwame",
         "anna-maria", "ravi", "chloe", "omar", "ines"]
LAST = ["o'neil", "smith", "khan", "wang", "petrov", "picard", "stone", "garcia", "novak", "fox", "mensah", "rossi",
        "patel", "dubois", "haddad", "silva"]
DOMAINS = ["example.com", "mail.example.org", "corp.example.net"]
COUNTRIES = {"US": ["US", "USA", "U.S.", "United States"], "GB": ["GB", "UK", "United Kingdom", "Great Britain"],
             "DE": ["DE", "Germany", "Deutschland"], "FR": ["FR", "France"], "IN": ["IN", "India"],
             "BR": ["BR", "Brazil", "Brasil"]}
HEADERS = {"name": ["Name", "Full Name", "Customer"], "email": ["Email", "E-mail", "Email Address"],
           "signup_date": ["Signup Date", "signup_date", "Date Signed Up"], "amount": ["Amount", "Total", "Amount (USD)"],
           "country": ["Country", "Country Code"]}
OUT_HEADER = ["name", "email", "signup_date", "amount", "country"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]


def clean_table(rng: random.Random, n: int) -> list[list[str]]:
    """n rows in the canonical form, with distinct emails."""
    rows, seen = [], set()
    while len(rows) < n:
        first, last = rng.choice(FIRST), rng.choice(LAST)
        email = f"{first.replace('-', '').replace(chr(39), '')}.{last.replace(chr(39), '')}{rng.randint(1, 99)}@{rng.choice(DOMAINS)}"
        if email in seen:
            continue
        seen.add(email)
        when = date(2019, 1, 1) + timedelta(days=rng.randint(0, 2500))
        rows.append([f"{first.title()} {last.title()}", email, when.isoformat(), f"{rng.randint(1, 250000) / 100:.2f}",
                     rng.choice(list(COUNTRIES))])
    return rows


def _pad(rng: random.Random, s: str) -> str:
    return " " * rng.randint(0, 2) + s + " " * rng.randint(0, 2)


def mess_name(rng: random.Random, name: str) -> str:
    kind = rng.random()
    first, last = name.split(" ", 1)
    s = (name if kind < .2 else name.upper() if kind < .4 else name.lower() if kind < .6
         else f"{last}, {first}" if kind < .8 else name.swapcase())
    return _pad(rng, s.replace(" ", " " * rng.randint(1, 3)))


def mess_email(rng: random.Random, email: str) -> str:
    return _pad(rng, "".join(c.upper() if rng.random() < .3 else c for c in email))


def mess_date(rng: random.Random, iso: str) -> str:
    d = date.fromisoformat(iso)
    forms = [iso, f"{d.year}/{d.month:02d}/{d.day:02d}", f"{d.month:02d}/{d.day:02d}/{d.year}",
             f"{d.day} {MONTHS[d.month - 1][:3]} {d.year}", f"{MONTHS[d.month - 1]} {d.day}, {d.year}", d.strftime("%Y%m%d")]
    return _pad(rng, rng.choice(forms))


def mess_amount(rng: random.Random, amount: str) -> str:
    whole, frac = (int(x) for x in amount.split("."))
    forms = [f"{whole}.{frac:02d}", f"${whole:,}.{frac:02d}", f"USD {whole:,}.{frac:02d}", f"$ {whole}.{frac:02d}",
             f"{whole:,}.{frac:02d}"]
    if frac % 10 == 0:
        forms.append(f"{whole}.{frac // 10}")
    if frac == 0:
        forms.append(str(whole))
    return _pad(rng, rng.choice(forms))


def mess_country(rng: random.Random, code: str) -> str:
    s = rng.choice(COUNTRIES[code])
    return _pad(rng, s.lower() if rng.random() < .3 else s)


def messy_row(rng: random.Random, clean: list[str]) -> dict[str, str]:
    return {"name": mess_name(rng, clean[0]), "email": mess_email(rng, clean[1]), "signup_date": mess_date(rng, clean[2]),
            "amount": mess_amount(rng, clean[3]), "country": mess_country(rng, clean[4])}


def messy_file(rng: random.Random, table: list[list[str]]) -> str:
    """The table as a customer export: shuffled columns, an extra notes column sometimes, each row messed in its own
    way, duplicates of earlier customers later in the file (with another amount: the first one counts), rows with no
    email, blank lines, a byte-order mark and Windows line ends sometimes."""
    cols = list(HEADERS) + (["notes"] if rng.random() < .5 else [])
    rng.shuffle(cols)
    header = [rng.choice(HEADERS[c]) if c in HEADERS else "Notes" for c in cols]
    rows = [(i, messy_row(rng, r)) for i, r in enumerate(table)]
    for _ in range(max(1, len(table) // 6)):
        i = rng.randrange(len(table))
        again = messy_row(rng, [*table[i][:3], f"{rng.randint(1, 250000) / 100:.2f}", table[i][4]])
        at = rng.randrange(next(k for k, (j, _) in enumerate(rows) if j == i) + 1, len(rows) + 1)
        rows.insert(at, (-1, again))
    for _ in range(max(1, len(table) // 10)):
        junk = messy_row(rng, table[rng.randrange(len(table))])
        junk["email"] = rng.choice(["", "  "])
        rows.insert(rng.randrange(len(rows) + 1), (-1, junk))
    eol = rng.choice(["\n", "\r\n"])
    out = io.StringIO()
    w = csv.writer(out, lineterminator=eol)
    w.writerow(header)
    for _, r in rows:
        w.writerow([r.get(c, "") if c in HEADERS else rng.choice(["call back", "vip, repeat", "", "n/a"]) for c in cols])
        if rng.random() < .05:
            out.write(eol)
    return ("﻿" if rng.random() < .3 else "") + out.getvalue()
