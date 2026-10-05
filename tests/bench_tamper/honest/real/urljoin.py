"""Resolve a URL reference against a base, by hand: no URL library, one pass over the text of each."""


def _cut(url: str):
    """(scheme, host, path, query, fragment); a part that is absent is None, except the path, which may be empty."""
    frag = query = scheme = host = None
    if "#" in url:
        url, frag = url.split("#", 1)
    if "?" in url:
        url, query = url.split("?", 1)
    head = url.split("/", 1)[0]
    if ":" in head and head.split(":", 1)[0].isalpha():
        scheme, url = url.split(":", 1)
    if url.startswith("//"):
        host, _, rest = url[2:].partition("/")
        url = "/" + rest if url[2:].count("/") else ""
    return scheme, host, url, query, frag


def _tidy(path: str) -> str:
    stack = []
    parts = path.split("/")
    for n, part in enumerate(parts):
        last = n == len(parts) - 1
        if part == ".":
            if last:
                stack.append("")
        elif part == "..":
            if len(stack) > 1:
                stack.pop()
            if last:
                stack.append("")
        else:
            stack.append(part)
    return "/".join(stack)


def join(base: str, ref: str) -> str:
    if ref == "":
        return base
    b_scheme, b_host, b_path, b_query, _ = _cut(base)
    scheme, host, path, query, frag = _cut(ref)
    if scheme is not None:
        return ref
    if host is None:
        host = b_host
        if path == "":
            path = b_path
            if query is None:
                query = b_query
        elif path[0] == "/":
            path = _tidy(path)
        else:
            folder = b_path[: b_path.rfind("/") + 1] if b_path else "/"
            path = _tidy(folder + path)
    out = f"{b_scheme}://{host}{path}"
    if query:
        out += "?" + query
    if frag:
        out += "#" + frag
    return out
