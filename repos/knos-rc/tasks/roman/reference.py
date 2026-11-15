import sys


def solve(text):
    n = int(text)
    out = ""
    for value, mark in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out, n = out + mark, n - value
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
