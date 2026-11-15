import sys


def solve(text):
    y, m, d = (int(x) for x in text.strip().split("-"))
    def leap(y):
        return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    days = sum(366 if leap(v) else 365 for v in range(1900, y))
    days += sum((31, 29 if leap(y) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[:m - 1]) + d - 1
    return ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[days % 7]


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
