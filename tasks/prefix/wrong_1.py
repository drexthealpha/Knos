import sys


def solve(text):
    words = text.split()
    a, b = words[0], words[1] if len(words) > 1 else words[0]
    out = ""
    for x, y in zip(a, b):
        if x != y:
            break
        out += x
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
