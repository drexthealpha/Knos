import sys


def solve(text):
    rows = [r.split() for r in text.strip().split(";")]
    return ";".join(" ".join(col) for col in zip(*reversed(rows)))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
