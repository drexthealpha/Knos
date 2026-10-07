import sys


def solve(text):
    s = text.strip()
    out, run = "", 1
    for a, b in zip(s, s[1:]):
        if a == b:
            run += 1
        else:
            out += a + str(run)
            run = 1
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
