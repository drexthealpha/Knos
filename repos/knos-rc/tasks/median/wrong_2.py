import sys


def solve(text):
    v = sorted(int(x) for x in text.split())
    return str(v[len(v) // 2])


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
