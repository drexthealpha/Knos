import sys


def solve(text):
    s = text.strip()
    out, i = "", 0
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        out += s[i] + str(j - i)
        i = j
    return out


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
