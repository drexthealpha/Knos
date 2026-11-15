"""Match a name against a shell pattern (* ? [abc] [a-c] [!abc]) with a table instead of a regular expression:
reach[i][j] says whether the first i pattern items can match the first j characters of the name."""


def _items(pattern: str) -> list:
    """The pattern as a list: "*", "?", a literal character, or (negated, set of characters) for a bracket."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "[":
            j = i + 1
            if j < len(pattern) and pattern[j] == "!":
                j += 1
            if j < len(pattern) and pattern[j] == "]":
                j += 1
            end = pattern.find("]", j)
            if end != -1:
                body = pattern[i + 1:end]
                negated = body.startswith("!")
                body = body[1:] if negated else body
                chars, k = set(), 0
                while k < len(body):
                    if k + 2 < len(body) and body[k + 1] == "-":
                        chars.update(chr(x) for x in range(ord(body[k]), ord(body[k + 2]) + 1))
                        k += 3
                    else:
                        chars.add(body[k])
                        k += 1
                out.append((negated, chars))
                i = end + 1
                continue
        out.append(c if c in "*?" else ("lit", c))
        i += 1
    return out


def _one(item, ch: str) -> bool:
    if item == "?":
        return True
    if item[0] == "lit":
        return item[1] == ch
    negated, chars = item
    return (ch in chars) != negated


def match(name: str, pattern: str) -> bool:
    items = _items(pattern)
    reach = [[False] * (len(name) + 1) for _ in range(len(items) + 1)]
    reach[0][0] = True
    for i, item in enumerate(items, 1):
        for j in range(len(name) + 1):
            if item == "*":
                reach[i][j] = reach[i - 1][j] or (j > 0 and reach[i][j - 1])
            else:
                reach[i][j] = j > 0 and reach[i - 1][j - 1] and _one(item, name[j - 1])
    return reach[len(items)][len(name)]
