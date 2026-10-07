import sys


def solve(text):
    v = sorted(set(int(x) for x in text.split()))
    out, i = [], 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[j + 1] == v[j] + 1:
            j += 1
        out.append(f"{v[i]}-{v[j]}" if j - i >= 2 else ",".join(str(x) for x in v[i:j + 1]))
        i = j + 1
    return ",".join(out)


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
