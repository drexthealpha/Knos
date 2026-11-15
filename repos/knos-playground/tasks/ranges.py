# Test USDC, no monetary value.
# Compress a list of numbers into ranges.
#
# Read one line of whole numbers from 0 up, separated by spaces, in any order, perhaps with repeats. Print the
# distinct numbers in rising order, separated by commas, writing every run of two or more consecutive numbers as
# first-last: 1 2 3 5 7 8 gives 1-3,5,7-8.
#
#     input:   1 2 3 5 7 8                  output:   1-3,5,7-8
#     input:   9 4                          output:   4,9
#     input:   5 3 4 4                      output:   3-5
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py ranges
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
