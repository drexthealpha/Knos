import sys


def solve(text):
    first, *words = text.split()
    width, lines, line = int(first), [], ""
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            lines.append(line)
            line = w
        else:
            line = line + " " + w if line else w
    if line:
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
