import sys


def solve(text):
    n = int(text)
    out = ""
    for value, mark in ((1000, "M"), (500, "D"), (100, "C"), (50, "L"), (10, "X"), (5, "V"), (1, "I")):
        while n >= value:
            out, n = out + mark, n - value
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
