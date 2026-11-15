import sys


def solve(text):
    total = 0
    for i, c in enumerate(reversed(text.strip())):
        d = int(c)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return "valid" if total % 10 == 0 else "invalid"


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
