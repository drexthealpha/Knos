import sys


def solve(text):
    a, b = ([int(p) for p in v.split(".")] for v in text.split())
    n = max(len(a), len(b))
    a, b = a + [0] * (n - len(a)), b + [0] * (n - len(b))
    return "<" if a < b else ">" if a > b else "="


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
