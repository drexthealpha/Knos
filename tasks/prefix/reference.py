import sys


def solve(text):
    words = text.split()
    out = ""
    for chars in zip(*words):
        if len(set(chars)) != 1:
            break
        out += chars[0]
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
