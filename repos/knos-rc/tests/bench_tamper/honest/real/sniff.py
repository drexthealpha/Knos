"""The delimiter (one of , ; tab |) of a CSV sample: read the sample as CSV with each candidate, and keep the one that
gives every line the same number of cells, and the most of them."""
import csv
import io


def _widths(sample: str, d: str) -> set:
    rows = csv.reader(io.StringIO(sample), delimiter=d)
    return {len(row) for row in rows if any(cell.strip() for cell in row)}


def delimiter(sample: str) -> str:
    found, cells = ",", 1
    for candidate in ",;\t|":
        widths = _widths(sample, candidate)
        if len(widths) == 1 and max(widths) > cells:
            found, cells = candidate, max(widths)
    return found
