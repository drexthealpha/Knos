import sys


def solve(text):
    a, b = (int(x) for x in text.split())
    x = min(a, b)
    while a % x or b % x:
        x -= 1
        if x < max(a, b) - 100000:
            x = 1
    return f"{x} {a * b // x}"


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
