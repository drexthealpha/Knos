"""The plain alternative of the locked comparison (L15): a spreadsheet formula, as a careful person writes it.

The file is opened as a spreadsheet opens it in the file's own locale: comma, tab or semicolon between columns (a
semicolon file with decimal commas, 1,4, read as 1.4), quotes removed, a leading byte-order mark dropped. A cell is a
number only when it is a plain decimal number (spaces around it allowed, scientific notation allowed); NaN, inf and words
are text and a blank is blank. The person points the formula at the named column, below the header row (the first row is
the header when any of its cells is not a number; with no header the columns are "column 1", "column 2"):

    rule above:  =IF(ISNUMBER(B2), B2<=limit, FALSE) in each row, then =MATCH(TRUE, C2:Cn, 0)
    rule below:  =IF(ISNUMBER(B2), B2>=limit, FALSE) in each row, then =MATCH(TRUE, C2:Cn, 0)

MATCH gives the first data row that breaks the limit, or #N/A when none does (here None). This file evaluates that
formula; it was not run inside a spreadsheet program.
"""
from __future__ import annotations

import csv
import io
import re

NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def isnumber(cell: str, dec_comma: bool) -> float | None:
    s = cell.strip()
    if dec_comma:
        s = s.replace(",", ".")
    return float(s) if NUMBER.match(s) else None


def check(text: str, column: str, rule: str, limit: float) -> int | None:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    first = next((x for x in text.split("\n") if x.strip()), "")
    sep = "\t" if "\t" in first and "," not in first else ";" if ";" in first and "," not in first else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=sep))
    dec = sep == ";"
    if rows and any(isnumber(c, dec) is None for c in rows[0]):
        names, data = [c.strip() for c in rows[0]], rows[1:]
    else:
        names, data = [f"column {i + 1}" for i in range(max((len(r) for r in rows), default=0))], rows
    if column not in names:
        raise KeyError(column)
    col = names.index(column)
    for i, row in enumerate(data, 1):
        v = isnumber(row[col], dec) if col < len(row) else None
        if v is not None and (v <= limit if rule == "above" else v >= limit):
            return i
    return None
