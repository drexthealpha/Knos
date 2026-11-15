import sys


def solve(text):
    a, b = (int(x) for x in text.split())
    return str(abs(bin(a).count("1") - bin(b).count("1")))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
