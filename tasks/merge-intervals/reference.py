import sys


def solve(text):
    spans = sorted(tuple(int(x) for x in s.split("-")) for s in text.split())
    out = []
    for a, b in spans:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return " ".join(f"{a}-{b}" for a, b in out)


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
