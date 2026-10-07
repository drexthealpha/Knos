import sys


def solve(text):
    a, b = (int(t[:2]) * 60 + int(t[3:]) for t in text.split())
    return str((b - a) % 1440)


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
