import sys


def solve(text):
    depth = 0
    for c in text:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                return "no"
    return "yes" if depth == 0 else "no"


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
