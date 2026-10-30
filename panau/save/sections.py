"""Per-section "take the better of two saves" merges. Each takes (base records, other records) and returns records.

Verified in game (the game's next autosave kept the result): stats, flags59, unlocks, locations (flags + counters),
activities. main (missions) and factions are implemented but were never needed in testing (the base save was ahead
on both), so merge.py only applies them on request.
"""
import struct

from panau.save.format import u32


def stat_max(x, y):
    """The larger of two 4-byte stat values; floats (distance/time records) are compared as floats."""
    ix, iy = u32(x), u32(y)
    looks_float = lambda v: 0x30000000 <= v < 0x4F000000
    if (looks_float(ix) or ix == 0) and (looks_float(iy) or iy == 0) and (ix or iy):
        fx, fy = struct.unpack('<f', x)[0], struct.unpack('<f', y)[0]
        return x if fx >= fy else y
    return x if ix >= iy else y


def merge_stats(a, b):
    """Every counter (idx 313+) and the playtime: the larger. The sorted hash list (idx 163 = count, 164..) is the
    union."""
    db = dict(b)
    merged = []
    for k, d in a:
        if k == 0 and len(d) == 8 and len(db.get(0, b'')) == 8:
            d = struct.pack('<Q', max(struct.unpack('<Q', d)[0], struct.unpack('<Q', db[0])[0]))
        elif k >= 313 and len(d) == 4 and len(db.get(k, b'')) == 4:
            d = stat_max(d, db[k])
        merged.append((k, d))
    da = dict(merged)
    na, nb = u32(da[163]), u32(db[163])
    hashes = {da[164 + i] for i in range(na)} | {db[164 + i] for i in range(nb)}
    ordered = sorted(hashes, key=lambda h: struct.unpack('<i', h)[0])
    before = [r for r in merged if r[0] < 163]
    after = [r for r in merged if r[0] > 163 + na]
    if after and 163 + len(ordered) >= after[0][0]:
        raise ValueError('stats hash list would overflow its slots')
    return before + [(163, struct.pack('<I', len(ordered)))] + [(164 + i, h) for i, h in enumerate(ordered)] + after


def merge_flags59(a, b):
    """59 (hash, flag) pairs: the higher flag."""
    rb = dict(b)
    db = {rb[k]: rb[k + 1] for k in range(1, 119, 2)}
    out = list(a)
    for n, (k, d) in enumerate(out):
        if 1 <= k < 119 and k % 2 == 0:
            h = out[n - 1][1]
            if h in db and db[h][0] > d[0]:
                out[n] = (k, db[h])
    return out


def merge_unlocks(a, b):
    """Black market unlocks: pairs of (count, array) of 8-byte (hash, u16, u16 flags) or 4-byte hashes. Union per
    hash, flags OR'd."""
    da, db = dict(a), dict(b)
    out = []
    for ci, ai, size in [(0, 1, 8), (2, 3, 8), (4, 5, 8), (6, 7, 4), (8, 9, 8)]:
        ea = [da[ai][i:i + size] for i in range(0, len(da[ai]), size)]
        eb = [db[ai][i:i + size] for i in range(0, len(db[ai]), size)]
        if size == 8:
            m = {e[:4]: e for e in ea}
            for e in eb:
                x = m.get(e[:4])
                if x is None:
                    m[e[:4]] = e
                else:
                    f1 = struct.unpack('<H', x[4:6])[0] | struct.unpack('<H', e[4:6])[0]
                    f2 = struct.unpack('<H', x[6:8])[0] | struct.unpack('<H', e[6:8])[0]
                    m[e[:4]] = e[:4] + struct.pack('<HH', f1, f2)
            seen_a = {x[:4] for x in ea}
            merged = [m[h] for h in [e[:4] for e in ea] + [e[:4] for e in eb if e[:4] not in seen_a]]
        else:
            seen = set(ea)
            merged = ea + [e for e in eb if e not in seen]
        out += [(ci, struct.pack('<I', len(merged))), (ai, b''.join(merged))]
    return out


def merge_location_flags(a, b):
    """360 x (id, counter, discovered, done) at idx 1+4i: the two flags OR'd. Counters are handled in merge.py
    (they must match the objects actually credited, not just a max)."""
    rb = dict(b)
    bmap = {rb[1 + 4 * i]: (rb[3 + 4 * i], rb[4 + 4 * i]) for i in range(360)}
    out = list(a)
    pos = {k: n for n, (k, _) in enumerate(out)}
    for i in range(360):
        lid = out[pos[1 + 4 * i]][1]
        if lid in bmap:
            for j, k in enumerate((3 + 4 * i, 4 + 4 * i)):
                n = pos[k]
                out[n] = (k, bytes([out[n][1][0] | bmap[lid][j][0]]))
    return out


def merge_factions(a, b):
    da, rb = dict(a), dict(b)
    bmap = {rb[1 + 5 * i]: [rb[2 + 5 * i + j] for j in range(4)] for i in range(9)}
    res = [a[0]]
    for i in range(9):
        h = da[1 + 5 * i]
        vals = [da[2 + 5 * i + j] for j in range(4)]
        if h in bmap:
            bv = bmap[h]
            vals[0] = struct.pack('<I', max(u32(vals[0]), u32(bv[0])))
            for j in range(1, 4):
                vals[j] = bytes([vals[j][0] | bv[j][0]])
        res += [(1 + 5 * i, h)] + [(2 + 5 * i + j, vals[j]) for j in range(4)]
    return res


def merge_main(a, b):
    """Missions: the base's story state; any mission the other save got further in takes its higher status. Money:
    the larger."""
    out, rb = list(a), dict(b)
    bm = {rb[k]: (rb[k + 1], rb[k + 2], rb[k + 3]) for k in range(7, 175, 4)}
    for k in range(7, 175, 4):
        h = out[k][1]
        if h in bm:
            for j in range(3):
                if bm[h][j][0] > out[k + 1 + j][1][0]:
                    out[k + 1 + j] = (k + 1 + j, bm[h][j])
    out[4] = (4, struct.pack('<I', max(u32(out[4][1]), u32(rb[4]))))
    return out


def merge_activities(a, b):
    """Header idx 0-16 (6-8 are counters: max), then from idx 100 a fixed list of activities in the same order in
    every save: (u32 id, u8 status, [u32 value]); status 0x04 = completed. Then the race list: u32 count + (8-byte
    race id, float best time) pairs. A completed activity wins; race times: the best (lowest)."""
    db = dict(b)
    head = []
    for k, d in a:
        if k >= 100:
            break
        if k in (6, 7, 8) and len(d) == 4 and len(db.get(k, b'')) == 4:
            d = struct.pack('<I', max(u32(d), u32(db[k])))
        head.append((k, d))
    ra = [r for r in a if r[0] >= 100]
    rb = [r for r in b if r[0] >= 100]

    def race_start(rows):
        for p in range(len(rows) - 1, -1, -1):
            if len(rows[p][1]) == 4 and u32(rows[p][1]) * 2 == len(rows) - p - 1 and \
                    all(len(rows[q][1]) == (8 if (q - p) % 2 else 4) for q in range(p + 1, len(rows))):
                return p
        raise ValueError('activity list: race records not found')
    pa, pb = race_start(ra), race_start(rb)
    if pa != pb or [(k, len(d)) for k, d in ra[:pa]] != [(k, len(d)) for k, d in rb[:pb]]:
        raise ValueError('the two saves\' activity lists do not line up')
    act = [list(r) for r in ra[:pa]]
    for j in range(pa):
        if len(ra[j][1]) == 1:                     # status row; ra[j-1] is the id
            if ra[j - 1][1] != rb[j - 1][1]:
                raise ValueError('activity ids differ between the saves')
            has_val = j + 1 < pa and len(ra[j + 1][1]) == 4 and (j + 2 >= pa or len(ra[j + 2][1]) == 4)
            sa, sb = ra[j][1][0], rb[j][1][0]
            if sb & 4 and not sa & 4:
                act[j][1] = rb[j][1]
                if has_val:
                    act[j + 1][1] = rb[j + 1][1]
            else:
                act[j][1] = bytes([sa | (sb & 0x07)])
                if has_val:
                    act[j + 1][1] = struct.pack('<I', max(u32(ra[j + 1][1]), u32(rb[j + 1][1])))
    races = {}
    for rows, p in ((ra, pa), (rb, pb)):
        for q in range(p + 1, len(rows), 2):
            key, t = rows[q][1], rows[q + 1][1]
            if key not in races or struct.unpack('<f', t)[0] < struct.unpack('<f', races[key])[0]:
                races[key] = t
    order = [ra[q][1] for q in range(pa + 1, len(ra), 2)] + [rb[q][1] for q in range(pb + 1, len(rb), 2)]
    seen, tail = set(), []
    for key in order:
        if key not in seen:
            seen.add(key); tail += [key, races[key]]
    k0 = ra[pa][0]
    return head + [tuple(r) for r in act] + [(k0, struct.pack('<I', len(tail) // 2))] + \
        [(k0 + 1 + i, d) for i, d in enumerate(tail)]
