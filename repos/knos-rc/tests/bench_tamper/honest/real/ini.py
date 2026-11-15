"""Read an INI file as configparser does (interpolation off), in two steps: first the lines are gathered into entries
(a section header, or a key with the lines that continue it), then the entries are put into sections."""


def _entries(text: str):
    """("section", name) and ("key", [first line, continuation, ...]) in the order of the file."""
    out = []
    for raw in text.split("\n"):
        raw = raw.rstrip("\r")
        line = raw.strip()
        if line == "" or line.startswith("#") or line.startswith(";"):
            continue
        indented = raw[:1] in (" ", "\t")
        if indented and out and out[-1][0] == "key":
            out[-1][1].append(line)
        elif line.startswith("[") and line.endswith("]") and len(line) > 2:
            out.append(("section", line[1:-1]))
        else:
            out.append(("key", [line]))
    return out


def _split(line: str):
    cut = min((i for i in (line.find("="), line.find(":")) if i != -1), default=-1)
    if cut == -1:
        raise ValueError(f"no delimiter in {line!r}")
    return line[:cut].strip().lower(), line[cut + 1:].strip()


def parse(text: str) -> dict:
    defaults: dict = {}
    sections: dict = {}
    current = None
    for kind, what in _entries(text):
        if kind == "section":
            if what in sections or (what == "DEFAULT" and current is defaults):
                raise ValueError(f"section {what} twice")
            current = defaults if what == "DEFAULT" else sections.setdefault(what, {})
            mine: set = set()
            continue
        if current is None:
            raise ValueError("a key before any section")
        key, value = _split(what[0])
        if key in mine:
            raise ValueError(f"key {key} twice")
        mine.add(key)
        current[key] = "\n".join([value, *what[1:]])
    return {name: dict(defaults, **keys) for name, keys in sections.items()}
