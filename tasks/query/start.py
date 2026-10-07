# Test USDC, no monetary value.
# Group the values of a query string.
#
# Read one query string like b=2&a=1&a=3: pairs joined by &, each key=value; a pair with no = is a key with an
# empty value. Print the keys in alphabetical order, separated by spaces, each as key= followed by its values in
# the order they appeared, joined by commas: a=1,3 b=2.
#
#     input:   b=2&a=1&a=3                  output:   a=1,3 b=2
#     input:   x                            output:   x=
#     input:   k=v=w&k=                     output:   k=v=w,
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py query
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
