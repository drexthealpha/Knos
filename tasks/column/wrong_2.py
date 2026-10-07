import sys


def solve(text):
    n, out = int(text) - 1, ""
    while True:
        n, r = divmod(n, 26)
        out = chr(65 + r) + out
        if not n:
            return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
