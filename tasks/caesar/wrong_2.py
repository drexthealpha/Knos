import sys


def solve(text):
    k, _, s = text.rstrip("\n").partition(" ")
    k = int(k)
    out = ""
    for c in s:
        if c.isascii() and c.isalpha():
            c = chr(ord("a") + (ord(c.lower()) - ord("a") + k) % 26)
        out += c
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
