import sys


def solve(text):
    small, out = {"a", "an", "the", "of", "and", "in", "on", "to"}, []
    for i, w in enumerate(text.strip().split(" ")):
        w = w.lower()
        out.append(w if i and w in small else w[:1].upper() + w[1:])
    return " ".join(out)


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
