"""A code reader knos brings with it.

universal-ctags is better than this: more languages, more kinds, and it has
been getting them right for twenty years. But it is a second install, and a
cold `pip install knos` on a default Ubuntu or WSL box does not have it — so
every answer that would have named a file and a line quietly did not.

So knos carries a small one. It finds what is defined and on which line, for
the languages people are mostly writing, and it does it by reading each file
once. When ctags is present that is used instead, because it is better.

Nothing here parses. A definition line is recognised by its shape, which is
wrong for pathological code and right for the code people write.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

# name-capturing patterns, per file extension. The kind is what knos calls it
# in an answer, so it has to be a word a person would use.
_RULES: dict[str, list[tuple[str, str]]] = {
    ".py": [
        (r"^\s*class\s+([A-Za-z_]\w*)", "class"),
        (r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", "function"),
    ],
    ".js": [
        (r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", "function"),
        (r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", "class"),
        (r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\(|function)", "function"),
    ],
    ".go": [
        (r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", "function"),
        (r"^\s*type\s+([A-Za-z_]\w*)", "type"),
    ],
    ".rs": [
        (r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)", "function"),
        (r"^\s*(?:pub\s+)?(?:struct|enum|trait|union)\s+([A-Za-z_]\w*)", "type"),
        (r"^\s*impl(?:<[^>]*>)?\s+(?:[\w:<>, ]+\s+for\s+)?([A-Za-z_]\w*)", "impl"),
    ],
    ".rb": [
        (r"^\s*(?:class|module)\s+([A-Z]\w*)", "class"),
        (r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)", "method"),
    ],
    ".java": [
        (r"^\s*(?:public|private|protected|final|abstract|static|\s)*(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", "class"),
        (r"^\s*(?:public|private|protected|static|final|synchronized|\s)+[\w<>\[\],.$ ]+\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{", "method"),
    ],
    ".c": [
        (r"^[A-Za-z_][\w \t*]*\s+\*?([A-Za-z_]\w*)\s*\([^;]*\)\s*\{", "function"),
        (r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)", "struct"),
    ],
    ".sh": [(r"^\s*(?:function\s+)?([A-Za-z_]\w*)\s*\(\s*\)\s*\{", "function")],
}
# Families that share a syntax closely enough to share the rules.
_RULES[".mjs"] = _RULES[".cjs"] = _RULES[".jsx"] = _RULES[".js"]
_RULES[".ts"] = _RULES[".tsx"] = _RULES[".js"] + [
    (r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)", "type"),
]
_RULES[".h"] = _RULES[".cc"] = _RULES[".cpp"] = _RULES[".hpp"] = _RULES[".c"]
_RULES[".pyi"] = _RULES[".py"]
_RULES[".kt"] = [
    (r"^\s*(?:private|internal|public|open|\s)*fun\s+([A-Za-z_]\w*)", "function"),
    (r"^\s*(?:private|internal|public|open|data|sealed|\s)*class\s+([A-Za-z_]\w*)", "class"),
]

_COMPILED = {
    ext: [(re.compile(pat), kind) for pat, kind in rules] for ext, rules in _RULES.items()
}

# A line longer than this is minified or generated. Nobody asks knos where a
# symbol in a bundle is defined, and scanning them is most of the cost.
_MAX_LINE = 400
_MAX_BYTES = 2_000_000

FIELD = "\t"


def languages() -> int:
    """How many file kinds this reader knows. Said in `knos status`."""
    return len(_RULES)


def write_index(repo: Path, files: list[str], out: Path, budget: float | None) -> int:
    """Scan the tracked files and write one line per definition.

    Returns the number found, or -1 if the budget ran out, in which case
    nothing is written: half an index answers some questions and silently
    misses others.
    """
    repo = Path(repo).resolve()
    started = time.perf_counter()
    lines: list[str] = []
    for path in files:
        if budget is not None and time.perf_counter() - started > budget:
            return -1
        rules = _COMPILED.get(Path(path).suffix.lower())
        if not rules:
            continue
        p = Path(path)
        try:
            if p.stat().st_size > _MAX_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = p.resolve().relative_to(repo).as_posix()
        except ValueError:
            rel = p.as_posix()
        for n, raw in enumerate(text.splitlines(), start=1):
            if len(raw) > _MAX_LINE:
                continue
            for pattern, kind in rules:
                found = pattern.match(raw)
                if found:
                    lines.append(f"{found.group(1)}{FIELD}{rel}{FIELD}{n}{FIELD}{kind}")
                    break
    out.write_text("\n".join(lines), encoding="utf-8")
    return len(lines)


def search_index(out: Path, wanted: list[str], limit: int) -> list[tuple[str, str, int, str]]:
    """Definitions whose name contains one of the words, best match first."""
    try:
        text = out.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[tuple[int, tuple[str, str, int, str]]] = []
    seen: set[tuple[str, int]] = set()
    for line in text.splitlines():
        parts = line.split(FIELD)
        if len(parts) != 4:
            continue
        name, rel, number, kind = parts
        low = name.lower()
        for word in wanted:
            if word not in low:
                continue
            key = (rel, int(number))
            if key in seen:
                break
            seen.add(key)
            # An exact name is what was asked for; a longer name that merely
            # contains it is a near miss, and goes after.
            hits.append((0 if low == word else 1, (name, rel, int(number), kind)))
            break
    hits.sort(key=lambda h: h[0])
    return [h[1] for h in hits[:limit]]
