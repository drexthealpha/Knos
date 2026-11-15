import sys


def solve(text):
    a, b = text.split()
    width = max(len(a), len(b))
    return bin(int(a, 2) + int(b, 2))[2:][-width:]


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
