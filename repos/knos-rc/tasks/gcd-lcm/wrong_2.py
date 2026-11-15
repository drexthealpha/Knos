import sys


def solve(text):
    a, b = (int(x) for x in text.split())
    x, y = a, b
    while y:
        x, y = y, x % y
    return f"{x} {int(a * b / x)}"


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
