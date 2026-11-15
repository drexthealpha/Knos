import sys


def solve(text):
    n, out, p = int(text), [], 2
    while p * p <= n:
        while n % p == 0:
            out.append(p)
            n //= p
        p += 1
    return " ".join(map(str, out))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
