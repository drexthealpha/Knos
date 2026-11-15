import sys


def solve(text):
    n, out, p = int(text), [], 2
    while p * p <= n:
        if n % p == 0:
            out.append(p)
            while n % p == 0:
                n //= p
        p += 1
    if n > 1:
        out.append(n)
    return " ".join(map(str, out))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
