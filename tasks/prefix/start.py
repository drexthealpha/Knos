# Test USDC, no monetary value.
# Print the longest common prefix of the words of a line.
#
# Read one line of words separated by spaces. Print the longest text every word starts with. When they share no
# start, print an empty line.
#
#     input:   flower flow flight           output:   fl
#     input:   dog cat                      output:   
#     input:   same same                    output:   same
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py prefix
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
