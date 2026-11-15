import sys


def solve(text):
    v = sorted(int(x) for x in text.split())
    n = len(v)
    if n % 2:
        return str(v[n // 2])
    return str((v[n // 2 - 1] + v[n // 2]) // 2)


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
