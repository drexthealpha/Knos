import sys


def solve(text):
    k, _, s = text.rstrip("\n").partition(" ")
    k = int(k)
    out = ""
    for c in s:
        if c.isascii() and c.isalpha():
            base = ord("a") if c.islower() else ord("A")
            c = chr(base + (ord(c) - base + k) % 26)
        out += c
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
