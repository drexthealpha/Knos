import sys


def solve(text):
    words = sorted(text.split(), key=len)
    out = words[0]
    while out and not words[-1].startswith(out):
        out = out[:-1]
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
