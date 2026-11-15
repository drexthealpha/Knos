import sys


def solve(text):
    a, b = ([int(p) for p in v.split(".")] for v in text.split())
    return "<" if a < b else ">" if a > b else "="


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
