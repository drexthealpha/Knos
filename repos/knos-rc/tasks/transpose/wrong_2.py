import sys


def solve(text):
    rows = [r.split() for r in text.strip().split(";")]
    n = len(rows)
    return ";".join(" ".join(rows[j][i] for j in range(n)) for i in range(n))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
