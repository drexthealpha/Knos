# Test USDC, no monetary value.
# Transpose a table of numbers.
#
# Read one line holding a table: rows separated by ;, the numbers of a row by spaces; every row has the same
# count. Print the table with rows and columns swapped, in the same form.
#
#     input:   1 2 3;4 5 6                  output:   1 4;2 5;3 6
#     input:   7                            output:   7
#     input:   1 2;3 4                      output:   1 3;2 4
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py transpose
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
