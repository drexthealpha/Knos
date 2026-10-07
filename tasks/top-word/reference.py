import sys


def solve(text):
    counts = {}
    for w in text.lower().split():
        counts[w] = counts.get(w, 0) + 1
    return min(counts, key=lambda w: (-counts[w], w))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
