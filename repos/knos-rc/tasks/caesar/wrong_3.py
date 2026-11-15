import sys


def solve(text):
    k, _, s = text.rstrip("\n").partition(" ")
    k = int(k)
    out = ""
    for c in s:
        if c.isascii() and c.isalnum():
            base = ord("a") if c.islower() else ord("A") if c.isupper() else ord("0")
            c = chr(base + (ord(c) - base + k) % (10 if c.isdigit() else 26))
        out += c
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
