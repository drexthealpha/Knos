import sys


def solve(text):
    n, out = int(text), ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
