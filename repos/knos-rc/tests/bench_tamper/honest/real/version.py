"""Order two PEP 440 version numbers (-1, 0 or 1) by reading both from left to right, one part at a time."""

_STAGE = {"dev": 0, "a": 1, "b": 2, "rc": 3, "": 4, "post": 5}


def _number(text: str, at: int):
    end = at
    while end < len(text) and text[end].isdigit():
        end += 1
    return int(text[at:end]), end


def _read(v: str) -> dict:
    out = {"epoch": 0, "release": [], "pre": None, "post": None, "dev": None, "local": None}
    if "+" in v:
        v, local = v.split("+", 1)
        out["local"] = local.split(".")
    if "!" in v:
        epoch, v = v.split("!", 1)
        out["epoch"] = int(epoch)
    at = 0
    while True:
        n, at = _number(v, at)
        out["release"].append(n)
        if at < len(v) and v[at] == "." and at + 1 < len(v) and v[at + 1].isdigit():
            at += 1
        else:
            break
    while at < len(v):
        if v[at] == ".":
            at += 1
        for word in ("post", "dev", "rc", "a", "b"):
            if v.startswith(word, at):
                n, at = _number(v, at + len(word))
                if word in ("post", "dev"):
                    out[word] = n
                else:
                    out["pre"] = (word, n)
                break
        else:
            raise ValueError(f"not a version: {v!r}")
    while len(out["release"]) > 1 and out["release"][-1] == 0:
        out["release"].pop()
    return out


def _sign(x, y) -> int:
    return (x > y) - (x < y)


def _pre_rank(p: dict):
    """Where the version stands before its final release: a bare dev release is before every pre-release."""
    if p["pre"] is not None:
        return _STAGE[p["pre"][0]], p["pre"][1]
    if p["post"] is None and p["dev"] is not None:
        return _STAGE["dev"], 0
    return _STAGE[""], 0


def _local_sign(x, y) -> int:
    if x is None or y is None:
        return _sign(x is not None, y is not None)
    for p, q in zip(x, y):
        if p.isdigit() != q.isdigit():
            return 1 if p.isdigit() else -1
        s = _sign(int(p), int(q)) if p.isdigit() else _sign(p, q)
        if s:
            return s
    return _sign(len(x), len(y))


def compare(a: str, b: str) -> int:
    x, y = _read(a), _read(b)
    for s in (_sign(x["epoch"], y["epoch"]),
              _sign(x["release"] if x["release"] != [0] else [], y["release"] if y["release"] != [0] else []),
              _sign(_pre_rank(x), _pre_rank(y)),
              _sign(-1 if x["post"] is None else x["post"], -1 if y["post"] is None else y["post"]),
              _sign(x["dev"] is None, y["dev"] is None) or (0 if x["dev"] is None else _sign(x["dev"], y["dev"])),
              _local_sign(x["local"], y["local"])):
        if s:
            return s
    return 0
