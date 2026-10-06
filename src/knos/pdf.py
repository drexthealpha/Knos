"""A PDF writer small enough to read in one sitting: text and ruled tables, the built-in Helvetica, as many pages as
the content needs. No dependency, no compression, no clock and no random number: the same calls give the same bytes.

    doc = Doc("Statement INV-7", created="2026-09-30")
    doc.text("Statement INV-7", size=14, bold=True)
    doc.table(["line", "state", "amount"], [["1", "agreed", "100.00"]], [40, 80, 80])
    data = doc.render()

What it does not do: other fonts, images, links, right-to-left text. A character outside Windows-1252 (the built-in
font's set here) is drawn as "?"; the JSON beside the PDF is the form that carries every character.

`created` is the day written into the file (the statement's own day), and the file's identifier is the SHA-256 of
its pages, so a file made again years later is the same file. Streams are not compressed, which keeps the writer
short and lets `texts` (and any reader with a text editor) see what a page says.
"""
from __future__ import annotations

import hashlib
import re

A4 = (595.0, 842.0)
A4_WIDE = (842.0, 595.0)
# Helvetica's advance widths for the characters 32 to 126, in thousandths of the font size (Adobe's AFM for the font).
_W = (278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584,
      584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
      667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278,
      556, 500, 722, 500, 500, 500, 334, 260, 334, 584)
_BOLD = 1.08        # the bold face is wider; this much is enough to wrap it safely


def latin(text: str) -> bytes:
    """The bytes the built-in font draws: Windows-1252, with "?" for anything else and for control characters."""
    return bytes(b if b >= 32 else 63 for b in str(text).replace("\t", " ").encode("cp1252", "replace"))


def width(text: str, size: float, bold: bool = False) -> float:
    """How wide `text` is drawn, in points."""
    total = sum(_W[b - 32] if 32 <= b <= 126 else 556 for b in latin(text))
    return total * size / 1000 * (_BOLD if bold else 1)


def wrap(text: str, size: float, room: float, bold: bool = False) -> list[str]:
    """`text` as the lines that fit `room` points: broken at spaces, and inside a word only when the word alone is
    wider than the room. A line break in the text starts a new line. Never an empty list."""
    out: list[str] = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}" if line else word
            if width(trial, size, bold) <= room:
                line = trial
                continue
            if line:
                out.append(line)
            line = word
            while width(line, size, bold) > room and len(line) > 1:
                cut = len(line) - 1
                while cut > 1 and width(line[:cut], size, bold) > room:
                    cut -= 1
                out.append(line[:cut])
                line = line[cut:]
        out.append(line)
    return out


def _num(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _string(text: str) -> str:
    """A PDF literal string, in ASCII: brackets and the backslash escaped, bytes above 126 as octal."""
    return "(" + "".join(f"\\{chr(b)}" if b in (40, 41, 92) else chr(b) if b <= 126 else f"\\{b:03o}" for b in latin(text)) + ")"


class Doc:
    """One document. Content flows down the page and on to the next one; `render` gives the bytes."""

    def __init__(self, title: str, created: str, size: tuple[float, float] = A4_WIDE, margin: float = 36.0, footer: str = "") -> None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", created):
            raise ValueError("created is a day: YYYY-MM-DD")
        self.title, self.created, self.size, self.margin, self.footer = title, created, size, margin, footer
        self.pages: list[list[str]] = [[]]
        self.y = size[1] - margin

    @property
    def room(self) -> float:
        return self.size[0] - 2 * self.margin

    def _need(self, height: float) -> bool:
        """Start a new page when `height` does not fit above the footer. True when it did."""
        if self.y - height >= self.margin + 14:
            return False
        self.pages.append([])
        self.y = self.size[1] - self.margin
        return True

    def _put(self, x: float, y: float, text: str, size: float, bold: bool = False) -> None:
        if text:
            self.pages[-1].append(f"BT /F{2 if bold else 1} {_num(size)} Tf {_num(x)} {_num(y)} Td {_string(text)} Tj ET")

    def _line(self, x1: float, y1: float, x2: float, y2: float, weight: float = 0.5) -> None:
        self.pages[-1].append(f"{_num(weight)} w {_num(x1)} {_num(y1)} m {_num(x2)} {_num(y2)} l S")

    def space(self, height: float = 8.0) -> None:
        self.y -= height

    def text(self, text: str, size: float = 9.0, bold: bool = False) -> None:
        """A paragraph, wrapped to the page."""
        for line in wrap(text, size, self.room, bold):
            self._need(size * 1.35)
            self.y -= size * 1.35
            self._put(self.margin, self.y + size * 0.3, line, size, bold)

    def rule(self) -> None:
        self._need(4)
        self.y -= 4
        self._line(self.margin, self.y, self.margin + self.room, self.y)

    def table(self, head: list[str], rows: list[list[str]], widths: list[float], size: float = 7.0) -> None:
        """A ruled table. Cells wrap; a row is never split across pages; the head is drawn again on every page."""
        if len(head) != len(widths) or any(len(r) != len(head) for r in rows):
            raise ValueError("every row has as many cells as the table has widths")
        scale = self.room / sum(widths)
        cols = [w * scale for w in widths]
        pad, lead = 3.0, size * 1.3

        def draw(cells: list[str], bold: bool) -> None:
            lines = [wrap(c, size, w - 2 * pad, bold) for c, w in zip(cells, cols)]
            height = max(len(part) for part in lines) * lead + 2 * pad
            if self._need(height) and not bold:
                draw(head, True)
            top, x = self.y, self.margin
            if bold:
                self._line(self.margin, top, self.margin + self.room, top)
            for part, w in zip(lines, cols):
                for i, line in enumerate(part):
                    self._put(x + pad, top - pad - (i + 1) * lead + size * 0.3, line, size, bold)
                self._line(x, top, x, top - height)
                x += w
            self._line(x, top, x, top - height)
            self.y = top - height
            self._line(self.margin, self.y, self.margin + self.room, self.y)

        draw(head, True)
        for row in rows:
            draw([str(c) for c in row], False)

    def render(self) -> bytes:
        """The file: a header, the objects, the table of their offsets, the trailer. ASCII throughout."""
        count = len(self.pages)
        streams = []
        for n, ops in enumerate(self.pages, 1):
            foot = f"{self.footer}   " if self.footer else ""
            mark = f"BT /F1 6.5 Tf {_num(self.margin)} {_num(self.margin)} Td {_string(f'{foot}page {n} of {count}')} Tj ET"
            streams.append("\n".join([*ops, mark]) + "\n")
        day = self.created.replace("-", "")
        objects = ["<< /Type /Catalog /Pages 2 0 R >>",
                   f"<< /Type /Pages /Count {count} /Kids [{' '.join(f'{6 + 2 * i} 0 R' for i in range(count))}] >>",
                   "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                   "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
                   f"<< /Title {_string(self.title)} /Producer (Knos) /CreationDate (D:{day}000000Z) /ModDate (D:{day}000000Z) >>"]
        for i, stream in enumerate(streams):
            objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_num(self.size[0])} {_num(self.size[1])}] "
                           f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {7 + 2 * i} 0 R >>")
            objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}endstream")
        out = "%PDF-1.4\n"
        offsets = []
        for n, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += f"{n} 0 obj\n{body}\nendobj\n"
        ident = hashlib.sha256("".join(streams).encode("ascii") + self.title.encode("utf-8") + day.encode()).hexdigest()[:32]
        start = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
        out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 5 0 R /ID [<{ident}> <{ident}>] >>\nstartxref\n{start}\n%%EOF\n"
        return out.encode("ascii")


def texts(data: bytes) -> list[str]:
    """Every piece of text a file from `Doc` draws, in drawing order: for a check that the PDF says what the other
    forms say. It reads this writer's files, not PDFs in general."""
    found = []
    for raw in re.findall(rb"\((?:[^()\\]|\\.)*\) Tj", data, flags=re.S):
        body, out, i = raw[1:-4], bytearray(), 0
        while i < len(body):
            if body[i] == 92 and body[i + 1:i + 4].isdigit():
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
            elif body[i] == 92:
                out.append(body[i + 1])
                i += 2
            else:
                out.append(body[i])
                i += 1
        found.append(out.decode("cp1252", "replace"))
    return found
