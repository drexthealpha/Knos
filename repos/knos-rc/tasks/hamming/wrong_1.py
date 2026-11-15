import sys


def solve(text):
    a, b = (int(x) for x in text.split())
    return str(sum(x != y for x, y in zip(bin(a)[2:], bin(b)[2:])))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
