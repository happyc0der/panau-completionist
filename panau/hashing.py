"""Bob Jenkins' lookup3 hashlittle, which Avalanche's engine uses for every name hash (file names in the archive
tables, property names in placement files, mission ids in saves)."""


def _rot(x, k):
    return ((x << k) | (x >> (32 - k))) & 0xFFFFFFFF


def hashlittle(data: bytes, initval: int = 0) -> int:
    length = len(data)
    a = b = c = (0xDEADBEEF + length + initval) & 0xFFFFFFFF
    i = 0
    while length > 12:
        a = (a + int.from_bytes(data[i:i + 4], 'little')) & 0xFFFFFFFF
        b = (b + int.from_bytes(data[i + 4:i + 8], 'little')) & 0xFFFFFFFF
        c = (c + int.from_bytes(data[i + 8:i + 12], 'little')) & 0xFFFFFFFF
        a = (a - c) & 0xFFFFFFFF; a ^= _rot(c, 4); c = (c + b) & 0xFFFFFFFF
        b = (b - a) & 0xFFFFFFFF; b ^= _rot(a, 6); a = (a + c) & 0xFFFFFFFF
        c = (c - b) & 0xFFFFFFFF; c ^= _rot(b, 8); b = (b + a) & 0xFFFFFFFF
        a = (a - c) & 0xFFFFFFFF; a ^= _rot(c, 16); c = (c + b) & 0xFFFFFFFF
        b = (b - a) & 0xFFFFFFFF; b ^= _rot(a, 19); a = (a + c) & 0xFFFFFFFF
        c = (c - b) & 0xFFFFFFFF; c ^= _rot(b, 4); b = (b + a) & 0xFFFFFFFF
        length -= 12
        i += 12
    if length == 0:
        return c
    tail = data[i:] + bytes(12 - length)
    a = (a + int.from_bytes(tail[0:4], 'little')) & 0xFFFFFFFF
    b = (b + int.from_bytes(tail[4:8], 'little')) & 0xFFFFFFFF
    c = (c + int.from_bytes(tail[8:12], 'little')) & 0xFFFFFFFF
    c ^= b; c = (c - _rot(b, 14)) & 0xFFFFFFFF
    a ^= c; a = (a - _rot(c, 11)) & 0xFFFFFFFF
    b ^= a; b = (b - _rot(a, 25)) & 0xFFFFFFFF
    c ^= b; c = (c - _rot(b, 16)) & 0xFFFFFFFF
    a ^= c; a = (a - _rot(c, 4)) & 0xFFFFFFFF
    b ^= a; b = (b - _rot(a, 14)) & 0xFFFFFFFF
    c ^= b; c = (c - _rot(b, 24)) & 0xFFFFFFFF
    return c
