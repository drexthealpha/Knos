# Test USDC, no monetary value.
# Turn a camelCase name into snake_case.
#
# Read one name written in camelCase or PascalCase, made of letters and digits. Print it in snake_case, all
# lower case. A run of capitals is one word, except that its last capital starts the next word when a lower-case
# letter follows: parseHTTPResponse gives parse_http_response.
#
#     input:   parseHTTPResponse            output:   parse_http_response
#     input:   userId                       output:   user_id
#     input:   HTMLParser                   output:   html_parser
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py snake-case
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
