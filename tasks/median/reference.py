import sys


def solve(text):
    v = sorted(int(x) for x in text.split())
    n = len(v)
    if n % 2:
        return str(v[n // 2])
    total = v[n // 2 - 1] + v[n // 2]
    if total % 2 == 0:
        return str(total // 2)
    return ("-" if total < 0 else "") + str(abs(total) // 2) + ".5"


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
