import sys


def solve(text):
    n, b = (int(x) for x in text.split())
    digits, sign, out = "0123456789abcdefghijklmnopqrstuvwxyz", "-" if n < 0 else "", ""
    n = abs(n)
    while n:
        out, n = digits[n % b] + out, n // b
    return sign + (out or "0")


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
