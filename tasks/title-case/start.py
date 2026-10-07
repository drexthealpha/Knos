# Test USDC, no monetary value.
# Write a headline in title case.
#
# Read one line of words separated by single spaces. Print it with the first letter of every word in upper case
# and the rest of the word in lower case, except the small words a, an, the, of, and, in, on, to, which stay in
# lower case unless they are the first word. Characters that are not letters stay as they are.
#
#     input:   the lord of the rings        output:   The Lord of the Rings
#     input:   a tale OF two cities         output:   A Tale of Two Cities
#     input:   don't look back              output:   Don't Look Back
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py title-case
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
