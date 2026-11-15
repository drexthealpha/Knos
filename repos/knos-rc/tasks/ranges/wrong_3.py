import sys


def solve(text):
    v = sorted(set(text.split()))
    v = [int(x) for x in v]
    out, i = [], 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[j + 1] == v[j] + 1:
            j += 1
        out.append(str(v[i]) if i == j else f"{v[i]}-{v[j]}")
        i = j + 1
    return ",".join(out)


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
