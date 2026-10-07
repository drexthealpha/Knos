import sys


def solve(text):
    return "yes" if all(text.count(a) == text.count(b) for a, b in ("()", "[]", "{}")) else "no"


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
