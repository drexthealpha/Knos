# Test USDC, no monetary value.
# Print the median of a list of numbers.
#
# Read one line of whole numbers separated by spaces. Print their median. With an even count it is the mean of
# the two middle numbers: print it as a whole number when it is one, else with .5 (2.5, -0.5).
#
#     input:   3 1 2                        output:   2
#     input:   4 1 3 2                      output:   2.5
#     input:   -1 0                         output:   -0.5
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py median
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
