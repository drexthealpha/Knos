def bucket(key, n):
    """Jump consistent hash, as Lamping and Veach (2014) give it: no storage, a few lines."""
    b, j = -1, 0
    while j < n:
        b = j
        key = (key * 2862933555777941757 + 1) & 0xFFFFFFFFFFFFFFFF
        j = int((b + 1) * (float(1 << 31) / float((key >> 33) + 1)))
    return b
