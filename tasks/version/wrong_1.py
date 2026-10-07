import sys


def solve(text):
    a, b = text.split()
    return "<" if a < b else ">" if a > b else "="


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
