"""Read YYYY-MM-DD[(T| )HH:MM[:SS[.fff[fff]]][+HH:MM]] by position, with no regular expression and no date library,
and answer as ISO 8601 with seconds; ValueError for anything else."""

_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _digits(s: str, at: int, n: int, low: int, high: int) -> int:
    part = s[at:at + n]
    if len(part) != n or not all("0" <= c <= "9" for c in part):
        raise ValueError(f"not an ISO 8601 date: {s!r}")
    value = int(part)
    if not low <= value <= high:
        raise ValueError(f"out of range in {s!r}")
    return value


def _expect(s: str, at: int, chars: str) -> str:
    if at >= len(s) or s[at] not in chars:
        raise ValueError(f"not an ISO 8601 date: {s!r}")
    return s[at]


def parse(s: str) -> str:
    year = _digits(s, 0, 4, 1, 9999)
    _expect(s, 4, "-")
    month = _digits(s, 5, 2, 1, 12)
    _expect(s, 7, "-")
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    day = _digits(s, 8, 2, 1, _DAYS[month - 1] + (1 if leap and month == 2 else 0))
    out = f"{year:04d}-{month:02d}-{day:02d}T"
    if len(s) == 10:
        return out + "00:00:00"
    _expect(s, 10, "T ")
    hour = _digits(s, 11, 2, 0, 23)
    _expect(s, 13, ":")
    minute = _digits(s, 14, 2, 0, 59)
    at, second, micro = 16, 0, 0
    if s[at:at + 1] == ":":
        second = _digits(s, at + 1, 2, 0, 59)
        at += 3
        if s[at:at + 1] == ".":
            n = 0
            while s[at + 1 + n:at + 2 + n].isdigit():
                n += 1
            if n not in (3, 6):
                raise ValueError(f"not an ISO 8601 date: {s!r}")
            micro = _digits(s, at + 1, n, 0, 999999) * (1000 if n == 3 else 1)
            at += 1 + n
    out += f"{hour:02d}:{minute:02d}:{second:02d}" + (f".{micro:06d}" if micro else "")
    if at == len(s):
        return out
    sign = _expect(s, at, "+-")
    off_h = _digits(s, at + 1, 2, 0, 23)
    _expect(s, at + 3, ":")
    off_m = _digits(s, at + 4, 2, 0, 59)
    if at + 6 != len(s):
        raise ValueError(f"not an ISO 8601 date: {s!r}")
    if off_h == 0 and off_m == 0:
        sign = "+"
    return out + f"{sign}{off_h:02d}:{off_m:02d}"
