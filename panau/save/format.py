r"""Just Cause 2 save format (Steam build; 891,904-byte JustCause2SaveNN.sav files).

  0x000    slot summaries, 0x38 bytes each: u32 7, 0, money, ?, completion %, 0, playtime s, 0, unix time, 0,
           difficulty (0 Casual .. 3 Hardcore), 1, 0xC, 0x100. Entry 0 describes this file.
  0x200    SECTION TABLE: u32 count, then count x {u32 name hash, u32 0, u32 offset from 0x39A00, u32 size}, sorted by
           hash. The game seeks every section through this table, so whenever a section changes size the table must be
           rebuilt (rebuild_section_table) - a stale table makes the game read later sections at the wrong offsets and
           silently fall back to defaults (this was the cause of every "save got reset" while reverse engineering).
  0x39A00  the state stream: records {u16 index, u32 length, data}; index 0 starts a new section ("object").
           The rest of the file is zero padding.

Sections are recognised by shape (find()): main (missions, money), stats, flags59, unlocks (black market),
locations (360 x id/counter/2 discovery flags), factions, collected (collectible ids), world (the progress hash table,
see world.py), items (four keyed lists), activities (missions, races, stunts...: status bit 0x04 = completed), and the
lone difficulty u32.
"""
import struct

STREAM = 0x39A00
FILE_SIZE = 891904
WORLD_SLOTS = 23833
EMPTY_KEY = b'\xff' * 8
SECTION_TABLE = 0x200
ITEM_LISTS = [(8, 1, 4), (8, 1, 1, 4, 4), (8, 1, 1, 1, 1), (8, 1, 1)]   # entry shapes, keyed by the 8-byte id


class SaveFormatError(ValueError):
    pass


def u32(d):
    return struct.unpack('<I', d)[0]


def parse(b):
    """The state stream as a list of sections; each section is a list of (index, data)."""
    i, objs = STREAM, []
    while i + 6 <= len(b):
        idx, ln = struct.unpack_from('<HI', b, i)
        if ln > len(b) - i - 6:
            break
        if idx == 0 and ln == 0 and not any(b[i:i + 120]):
            break                                  # zero padding: end of stream
        if idx == 0:
            objs.append([])
        objs[-1].append((idx, bytes(b[i + 6:i + 6 + ln])))
        i += 6 + ln
    return objs


def serialize(objs):
    out = bytearray()
    for o in objs:
        for idx, d in o:
            out += struct.pack('<HI', idx, len(d)) + d
    return bytes(out)


def object_spans(objs):
    spans, pos = [], 0
    for o in objs:
        size = sum(6 + len(d) for _, d in o)
        spans.append((pos, size))
        pos += size
    return spans


def rebuild_section_table(out, old_objs, new_objs):
    n = struct.unpack_from('<I', out, SECTION_TABLE)[0]
    old, new = object_spans(old_objs), object_spans(new_objs)
    by_offset = {off: k for k, (off, _) in enumerate(old)}
    for e in range(n):
        p = SECTION_TABLE + 4 + 16 * e
        h, _zero, off, size = struct.unpack_from('<IIII', out, p)
        k = by_offset.get(off)
        if k is None or old[k][1] != size:
            raise SaveFormatError(f'section table entry {e} ({h:08x}) does not match a section')
        struct.pack_into('<II', out, p + 8, new[k][0], new[k][1])


def find(objs):
    """{section name: index in objs}, recognised by shape."""
    f = {}
    for k, o in enumerate(objs):
        first = o[0][1]
        maxidx = max(i for i, _ in o)
        if len(o) == 175 and 'main' not in f:
            f['main'] = k
        elif len(first) == 8 and maxidx == 442:
            f['stats'] = k
        elif len(first) == 4 and u32(first) == 59 and maxidx == 500:
            f['flags59'] = k
            f['unlocks'] = k + 1
        elif len(first) == 4 and u32(first) == 360 and maxidx == 1440:
            f['locations'] = k
        elif len(first) == 4 and u32(first) == 9 and len(o) == 46:
            f['factions'] = k
            f['collected'] = k + 1
        elif len(first) == 4 and u32(first) == WORLD_SLOTS and len(o) == 4:
            f['world'] = k
            f['items'] = k + 1
        elif len(first) == 4 and u32(first) == 0 and maxidx > 1000 and len(o) > 1 and o[1][0] == 1:
            f['activities'] = k
    if 'items' in f:                               # the difficulty: the lone u32 two sections after 'items'
        k = f['items'] + 2
        if len(objs[k]) == 1 and len(objs[k][0][1]) == 4 and u32(objs[k][0][1]) <= 3:
            f['difficulty'] = k
    need = ['main', 'stats', 'flags59', 'unlocks', 'locations', 'factions', 'collected', 'world', 'items',
            'activities', 'difficulty']
    missing = [n for n in need if n not in f]
    if missing:
        raise SaveFormatError(f'save layout not recognised (missing {missing})')
    return f


def item_lists(o):
    """idx 0-3 = the sizes of four lists; entries follow from idx 5 (shapes in ITEM_LISTS). [{id: [values]}] x 4"""
    d = dict(o)
    sizes = [u32(d[i]) for i in range(4)]
    rows = [r for r in o if r[0] >= 5]
    lists, p = [], 0
    for n, shape in zip(sizes, ITEM_LISTS):
        ents = {}
        for _ in range(n):
            vals = [rows[p + j][1] for j in range(len(shape))]
            if [len(v) for v in vals] != list(shape):
                raise SaveFormatError('item list layout not recognised')
            ents[vals[0]] = vals[1:]
            p += len(shape)
        lists.append(ents)
    if p != len(rows):
        raise SaveFormatError('item list layout not recognised (leftover records)')
    return lists


def build_item_lists(lists):
    """Inverse of item_lists (entries sorted by group id, then type key)."""
    out = [(i, struct.pack('<I', len(ea))) for i, ea in enumerate(lists)]
    k = 5
    for ea in lists:
        for key in sorted(ea, key=lambda d: (struct.unpack('<I', d[4:])[0], struct.unpack('<I', d[:4])[0])):
            for v in [key] + list(ea[key]):
                out.append((k, v)); k += 1
    return out


class Save:
    """A parsed save. .sections[name] is the section's record list; edit it, then to_bytes()."""

    def __init__(self, raw, path=None):
        if len(raw) != FILE_SIZE:
            raise SaveFormatError(f'unexpected size {len(raw)} (expected {FILE_SIZE}): not a full Just Cause 2 save')
        self.path, self.raw = path, raw
        self.objs = parse(raw)
        rebuilt = raw[:STREAM] + serialize(self.objs)
        if rebuilt + bytes(FILE_SIZE - len(rebuilt)) != raw:
            raise SaveFormatError('round trip failed: format not understood, refusing to touch this save')
        self.index = find(self.objs)
        self._original = [list(o) for o in self.objs]

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as f:
            return cls(f.read(), path)

    def __getitem__(self, name):
        return self.objs[self.index[name]]

    def __setitem__(self, name, records):
        self.objs[self.index[name]] = records

    @property
    def difficulty(self):
        return u32(self['difficulty'][0][1])

    def to_bytes(self, difficulty=None, money=None):
        stream = serialize(self.objs)
        if STREAM + len(stream) > FILE_SIZE - 0x1000:
            raise SaveFormatError('result would not fit the save file')
        out = bytearray(self.raw[:STREAM]) + stream
        out += bytes(FILE_SIZE - len(out))
        rebuild_section_table(out, self._original, self.objs)
        if money is not None:
            struct.pack_into('<I', out, 8, money)           # slot summary shown in the load menu
        if difficulty is not None:
            struct.pack_into('<I', out, 40, difficulty)
        if serialize(parse(bytes(out))) != stream:
            raise SaveFormatError('result does not parse back')
        return bytes(out)
