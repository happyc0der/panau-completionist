"""The world progress table and what "done" means.

The 'world' section is a hash table: idx 0 = slot count (23,833), 1 = used slots, 9 = 8-byte keys (u32 type key +
u32 group id), 10 = one bit per slot. slot = key as u64 mod 23,833, linear probing +1, empty = FF..FF.
A group id is the placement-file property ce458d96 shared by all parts of one object (a fuel depot, a collectible).

The bit is per-type state, not "done": each type key has its own polarity, and destroying something often adds new
keys to its group. data/done_flags.json lists, per type key, the bit value that means destroyed/collected; a group is
done when any of its keys has that value. The flags were derived per objective kind (the game's own act_* marker
texts) from save patterns and from live destruction in game.

SAM sites are not in this table: item list 3 holds {172ca9f7, group} with flag 2 = 1 once destroyed (and list 2
{bb2e8319, group} flag 1 = 1 for recent ones).
"""
import collections
import struct

from panau import data
from panau.save.format import EMPTY_KEY, ITEM_LISTS, WORLD_SLOTS, build_item_lists, item_lists, u32

SAM_LIST2 = bytes.fromhex('bb2e8319')
SAM_LIST3 = bytes.fromhex('172ca9f7')


def table(world_records):
    """(keys bytearray, bits bytearray) of a world section."""
    d = dict(world_records)
    return bytearray(d[9]), bytearray(d[10])


def states(world_records):
    """{group: {type key (4 bytes): bit}}"""
    t, mk = table(world_records)
    out = collections.defaultdict(dict)
    for i in range(WORLD_SLOTS):
        k = t[i * 8:i * 8 + 8]
        if k != EMPTY_KEY:
            out[struct.unpack('<I', k[4:])[0]][bytes(k[:4])] = (mk[i >> 3] >> (i & 7)) & 1
    return out


def is_done(state, flags=None):
    flags = flags or data.done_flags()
    return any(flags.get(t) == b for t, b in state.items())


def sam_done(items_records):
    l2, l3 = item_lists(items_records)[2:4]
    done = {struct.unpack('<I', k[4:])[0] for k, v in l2.items() if k[:4] == SAM_LIST2 and v[0][0] == 1}
    done |= {struct.unpack('<I', k[4:])[0] for k, v in l3.items() if k[:4] == SAM_LIST3 and v[1][0] == 1}
    return done


def copy_groups(world_records, source_states, groups):
    """World section with every type key of each group set to source_states' values (proper hash-table insertion for
    keys the table lacks)."""
    t, mk = table(world_records)
    pos = {bytes(t[i * 8:i * 8 + 8]): i for i in range(WORLD_SLOTS) if t[i * 8:i * 8 + 8] != EMPTY_KEY}
    for g in groups:
        for tk, b in source_states[g].items():
            key = tk + struct.pack('<I', g)
            i = pos.get(key)
            if i is None:
                i = struct.unpack('<Q', key)[0] % WORLD_SLOTS
                while t[i * 8:i * 8 + 8] != EMPTY_KEY:
                    i = (i + 1) % WORLD_SLOTS
                t[i * 8:i * 8 + 8] = key
                pos[key] = i
            if b:
                mk[i >> 3] |= 1 << (i & 7)
            else:
                mk[i >> 3] &= ~(1 << (i & 7)) & 0xFF
    if len(pos) > WORLD_SLOTS * 0.9:
        raise ValueError('world table would be too full')
    return [(k, bytes(t) if k == 9 else bytes(mk) if k == 10 else struct.pack('<I', len(pos)) if k == 1 else v)
            for k, v in world_records]


def mark_sams(items_records, groups, source=None):
    """Item list 3 SAM entries of these groups: flag 2 -> 1 (destroyed), edited in place (order and sizes kept).
    A SAM site the save has no entry for yet (it never got near it) gets the source save's entry: the lists are then
    rebuilt in the game's own order (by group id, then type key), and a rebuild of an unchanged section is
    byte-identical. Returns (records, count changed)."""
    out, changed = _mark_sams_in_place(items_records, groups)
    if source is None:
        return out, changed
    lists, src = item_lists(out), item_lists(source)
    have = {struct.unpack('<I', k[4:])[0] for k in lists[3] if k[:4] == SAM_LIST3} | \
           {struct.unpack('<I', k[4:])[0] for k in lists[2] if k[:4] == SAM_LIST2}
    added = set()
    for li, key, flag in ((3, SAM_LIST3, 1), (2, SAM_LIST2, 0)):
        for k, v in src[li].items():
            g = struct.unpack('<I', k[4:])[0]
            if k[:4] == key and g in groups and g not in have and g not in added and v[flag] == b'\x01':
                lists[li][k] = list(v); added.add(g)
    if added:
        out = build_item_lists(lists)
    return out, changed + len(added)


def _mark_sams_in_place(items_records, groups):
    d = dict(items_records)
    sizes = [u32(d[i]) for i in range(4)]
    out = list(items_records)
    rows = [n for n, r in enumerate(out) if r[0] >= 5]          # positions of entry records in the section
    start = sum(n * len(s) for n, s in zip(sizes[:3], ITEM_LISTS[:3]))
    changed = 0
    for e in range(sizes[3]):
        key_pos, flag2_pos = rows[start + 3 * e], rows[start + 3 * e + 2]
        key = out[key_pos][1]
        if key[:4] == SAM_LIST3 and struct.unpack('<I', key[4:])[0] in groups and out[flag2_pos][1] == b'\x00':
            out[flag2_pos] = (out[flag2_pos][0], b'\x01'); changed += 1
    return out, changed
