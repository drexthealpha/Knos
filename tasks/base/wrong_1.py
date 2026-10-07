import sys


def solve(text):
    n, b = (int(x) for x in text.split())
    digits, out = "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while n > 0:
        out, n = digits[n % b] + out, n // b
    return out or "0"


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
