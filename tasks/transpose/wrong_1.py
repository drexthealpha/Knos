import sys


def solve(text):
    rows = [r.split() for r in text.strip().split(";")]
    return ";".join(" ".join(reversed(r)) for r in rows)


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
