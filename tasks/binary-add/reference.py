import sys


def solve(text):
    a, b = text.split()
    return bin(int(a, 2) + int(b, 2))[2:]


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
