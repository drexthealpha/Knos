import sys


def solve(text):
    s, out = text.strip(), ""
    for i, c in enumerate(s):
        if c.isupper() and i and not s[i - 1].isupper():
            out += "_"
        out += c.lower()
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
