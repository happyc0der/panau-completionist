r"""Rebuild panau/data from your own Just Cause 2 install (read-only on the game; ~5-10 minutes).

    python tools/build_data.py [--game "D:\...\Just Cause 2"] [--out panau/data] [--check]

What it reads: archives_win32\pc*.tab/.arc -> zlib / SARC containers -> placement files (*.blo, Avalanche's
"RawPropertyFile": nested nodes of name-hashed variables) and settlements.bin.

What it builds:
  targets.json.gz       collectibles: groups with a CResourceItem "rei.<kind>BoostPickup" and a "dit.tin" pickup trigger
                        sabotage targets: groups whose CTargetIndicator carries an "act_<kind>_tin_txt" display text
                        (the game's own objective list), minus 9 undestroyable props (no damage component), a
                        mission's own props (enabled only during it) and the 8 untracked fuel depots of outposts dfd38 and dfd94
                        (neither is ever in the game's progress table), plus
                        propaganda trailer spawn points and pipelines (sabotaged at a control panel)
                        ignored: parked helicopters (GB017b cockpits), which carry a marker but should not get arrows
  settlements.json      the 405 locations in settlements.bin order (= a save's location id)
  group_cells.json.gz   target group -> placement cell (file stem), for crediting settlement counters in merges
  pipeline_panels.json  control panel group -> pipeline group
  counters.json.gz      target group -> [activity type, settlement]: the counters it raises (see save/recount.py)
done_flags.json is NOT rebuilt here: it was derived from saves and live play (see panau/save/world.py).

--check compares the result with the data already in --out instead of writing it. --counters writes only
counters.json.gz (keeping the shipped targets, whose positions were checked in game).

A group id (property ce458d96) ties the parts of one object together and is the id saves use.
Positions are world space: each node's mat43 is relative to its parent, so transforms are composed down the tree.
"""
import argparse
import collections
import glob
import gzip
import json
import math
import os
import re
import statistics
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panau.hashing import hashlittle  # noqa: E402

GROUP, TXT, CLS, NAME, MAT = 0xce458d96, 0xc9682bc3, hashlittle(b'_class'), hashlittle(b'name'), 0x6ca6d4b9
SETTLEMENT_GRID, SETTLEMENT_TOTAL = 0x0a1b210d, 0x4c4b2806
KIND_NAMES = {'fueldepot': 'fuel depot', 'gaspump': 'gas pump', 'smallantenna': 'small antenna', 'watertower': 'water tower',
              'samsite': 'SAM site', 'panaystatue': 'statue', 'commstation': 'comm station', 'largeantenna': 'large antenna',
              'windturbine': 'wind turbine', 'cargocrane': 'cargo crane', 'spheretank': 'sphere tank',
              'mobileradar': 'mobile radar', 'satellitedish': 'satellite dish', 'oilplatform': 'oil platform',
              'constructcrane': 'construction crane', 'radarsphere': 'radar sphere'}
ITEM_KINDS = {'weapon': 'weapon part', 'vehicle': 'vehicle part', 'armor': 'armor', 'cash': 'cash'}
DAMAGE = {'CDamageControl', 'CDamageableObject', 'CSAMSite'}
# objectives that look like sabotage targets but never count (the game never puts them in its progress table):
MISSION_ONLY = re.compile(r'\.specifics\.enable\b|\bmsy\.mission\.fail\b')       # a mission's own props
# the fuel depots of outposts dfd38 and dfd94: in no save's progress table (every other fuel depot in the game is,
# standing or destroyed) and no objective marker even 23 m away (seen in game 2026-10-30), so not objectives; nothing
# in the data tells them from dfd14's, which count (dfd94's even name settlement 35x36's counter)
UNTRACKED = {0x92c5e845, 0x2beeb995, 0xd021adea, 0x3735aee0,             # dfd38
             0x9bba5b98, 0xf4a650eb, 0xc7bbd815, 0xa11b7683}             # dfd94


# --- archives ------------------------------------------------------------------------------------------------------
def maybe_zlib(data):
    if data[:1] == b'\x78':
        try:
            return zlib.decompress(data)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(data)
            except zlib.error:
                pass
    return data


def sarc_entries(data):
    if data[4:8] != b'SARC':
        return None
    _ver, hsize = struct.unpack_from('<II', data, 8)
    p, out = 16, []
    while p + 4 <= 16 + hsize:
        nl = struct.unpack_from('<I', data, p)[0]
        if nl == 0 or nl > 512:
            break
        name = data[p + 4:p + 4 + nl].rstrip(b'\0').decode('latin-1'); p += 4 + nl
        off, size = struct.unpack_from('<II', data, p); p += 8
        out.append((name, data[off:off + size]))
    return out


def archive_files(game, wanted):
    """Yields (name, bytes) of every SARC member whose name passes wanted(name)."""
    for tab in sorted(glob.glob(os.path.join(game, 'archives_win32', 'pc*.tab'))):
        d = open(tab, 'rb').read()
        entries = [struct.unpack_from('<III', d, 4 + 12 * i) for i in range((len(d) - 4) // 12)]
        with open(tab[:-4] + '.arc', 'rb') as f:
            for _h, off, size in entries:
                f.seek(off)
                sub = sarc_entries(maybe_zlib(f.read(size)))
                for name, sd in sub or ():
                    if wanted(name):
                        yield name, maybe_zlib(sd)


# --- RawPropertyFile -------------------------------------------------------------------------------------------------
class Reader:
    def __init__(self, d): self.d, self.p = d, 0
    def u8(self): v = self.d[self.p]; self.p += 1; return v
    def u16(self): v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v
    def u32(self): v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v
    def s32(self): v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v
    def f32(self, n): v = struct.unpack_from(f'<{n}f', self.d, self.p); self.p += 4 * n; return v
    def raw(self, n): v = self.d[self.p:self.p + n]; self.p += n; return v


def variant(r):
    t = r.u8()
    if t == 1: return r.s32()
    if t == 2: return r.f32(1)[0]
    if t == 3: return r.raw(r.u16()).decode('latin-1')
    if t in (4, 5, 6, 7, 8): return r.f32({4: 2, 5: 3, 6: 4, 7: 9, 8: 12}[t])
    if t == 9: return [r.s32() for _ in range(r.s32())]
    if t == 10: return [r.f32(1)[0] for _ in range(r.s32())]
    raise ValueError(f'variant type {t}')


def node(r):
    n = {'nodes': [], 'vars': {}}
    for _ in range(r.u8()):
        st, cnt = r.u16(), r.u16()
        if st in (1, 2):
            for _ in range(cnt):
                h = hashlittle(r.raw(r.u32()))
                if st == 1: n['nodes'].append(node(r))
                else: n['vars'][h] = variant(r)
        elif st == 3:
            r.p += cnt
        elif st == 4:
            for _ in range(cnt):
                r.u32(); n['nodes'].append(node(r))
        elif st == 5:
            for _ in range(cnt):
                h = r.u32(); n['vars'][h] = variant(r)
        else:
            raise ValueError(f'section {st}')
    return n


def parse(d):
    r, out = Reader(d), []
    while r.p < len(d):
        out.append(node(r))
    return out


# --- transforms ------------------------------------------------------------------------------------------------------
IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)


def compose(local, parent):
    """Row-vector 4x3 matrices (rows 0-2 rotation, 3 translation): world = local x parent."""
    out = []
    for r in range(4):
        row = local[3 * r:3 * r + 3]
        for c in range(3):
            v = sum(row[k] * parent[3 * k + c] for k in range(3))
            out.append(v + (parent[9 + c] if r == 3 else 0))
    return tuple(out)


def objects(game):
    """[(class, name, group, world pos, ints-and-strings, cell)] for every placed object."""
    out = []

    def walk(n, parent, cell):
        v = n['vars']
        m = compose(v[MAT], parent) if isinstance(v.get(MAT), tuple) and len(v[MAT]) == 12 else parent
        if CLS in v:
            out.append((v[CLS], v.get(NAME), v.get(GROUP, 0) & 0xFFFFFFFF if isinstance(v.get(GROUP), int) else 0,
                        m[9:12], v, cell))
        for c in n['nodes']:
            walk(c, m, cell)

    for name, d in archive_files(game, lambda n: n.endswith('.blo')):
        stem = os.path.basename(name)
        for suf in ('.nl.blo', '.fl.blo', '.blo'):
            if stem.endswith(suf):
                stem = stem[:-len(suf)]; break
        try:
            for top in parse(d):
                walk(top, IDENTITY, stem)
        except (ValueError, struct.error, IndexError):
            pass
    return out


def settlements(game):
    for _name, d in archive_files(game, lambda n: os.path.basename(n) == 'settlements.bin'):
        top = parse(d)[0]
        lst = top['nodes'][0]
        return [{'grid': n['vars'][SETTLEMENT_GRID], 'total': n['vars'][SETTLEMENT_TOTAL], 'text': n['vars'][TXT],
                 'kind': (n['vars'][TXT].split('_') + ['?', '?'])[1]} for n in lst['nodes']]
    raise SystemExit('settlements.bin not found')


# --- targets -----------------------------------------------------------------------------------------------------------
def build(game):
    objs = objects(game)
    by_group = collections.defaultdict(list)
    for o in objs:
        if o[2]:
            by_group[o[2]].append(o)
    names = {g: {o[1] for o in os_ if o[1]} for g, os_ in by_group.items()}
    classes = {g: {o[0] for o in os_} for g, os_ in by_group.items()}
    world_pos = lambda os_: tuple(round(statistics.median(o[3][i] for o in os_), 2) for i in range(3))

    targets, ignored, cells = [], [], {}
    for g, os_ in by_group.items():                                    # collectibles
        rei = [o for o in os_ if o[0] == 'CResourceItem' and o[1]]
        if not rei or 'dit.tin' not in names[g]:                  # crate-spawned copies have no pickup trigger
            continue
        m = re.match(r'rei\.(\w+?)BoostPickup', rei[0][1])
        if m and m.group(1) in ITEM_KINDS:
            targets.append({'kind': 'item', 'label': ITEM_KINDS[m.group(1)], 'group': g, 'pos': list(rei[0][3])})
    for g, os_ in by_group.items():                                    # the game's objective list
        tins = [(o, m.group(1)) for o in os_ if o[0] == 'CTargetIndicator' and isinstance(o[4].get(TXT), str)
                and (m := re.match(r'act_([a-z]+)_', o[4][TXT]))]
        if not tins:
            continue
        kind = tins[0][1]
        marker_pos = list(tins[0][0][3])                             # the arrow points at the objective marker
        text = [v for o in os_ for v in o[4].values() if isinstance(v, str)]
        if 'geo.GB017b' in names[g]:                                   # parked helicopters
            ignored.append({'label': 'helicopter', 'group': g, 'pos': list(world_pos(os_))})
        elif any(MISSION_ONLY.search(s) for s in text):                # exists only during its mission (f3t05's silo)
            ignored.append({'label': 'mission prop', 'group': g, 'pos': marker_pos})
        elif g in UNTRACKED:
            ignored.append({'label': 'untracked fuel depot', 'group': g, 'pos': marker_pos})
        elif classes[g] & DAMAGE:                                      # props without a damage component never count
            targets.append({'kind': 'sabotage', 'label': KIND_NAMES.get(kind, kind), 'group': g, 'pos': marker_pos})
    for o in objs:                                                     # propaganda trailer spawn points
        if o[1] == 'sps.propagandaGuard1' and o[2]:
            targets.append({'kind': 'sabotage', 'label': 'propaganda', 'group': o[2], 'pos': list(o[3])})
    pipes = {g: next(o[3] for o in os_ if o[1] in ('geo.valve', 'sro.valve')) for g, os_ in by_group.items() if 'sht.valve.stop' in names[g]}
    panels = {g: next(o[3] for o in os_ if o[1] == 'tin') for g, os_ in by_group.items() if {'sro.dcs.panel1', 'sob', 'tin'} <= names[g]}
    link = {}
    for g, v in pipes.items():
        p = min(panels, key=lambda b: math.dist((v[0], v[2]), (panels[b][0], panels[b][2])))
        link[f'{p:08x}'] = f'{g:08x}'
        targets.append({'kind': 'sabotage', 'label': 'pipeline', 'group': g, 'pos': list(panels[p])})
    seen, uniq = set(), []
    for t in targets:
        if t['group'] not in seen:
            seen.add(t['group']); uniq.append(t)
    for t in uniq:
        cells[f'{t["group"]:08x}'] = by_group[t['group']][0][5] if t['group'] in by_group else None
    return {'targets': uniq, 'ignored': ignored}, cells, link, counters(uniq, by_group)


def counters(targets, by_group):
    """{group: [activity type, settlement]}: the counters a target raises when destroyed/collected. Its events name
    them: 'gsy.activity.typeNN' (the per-type 'destroyed' stat, 349 + 3 * NN) and '<settlement grid>.count.up'.
    Propaganda trailers fire type 06 from the spawned vehicle, so it is not in their placement."""
    out = {}
    for t in targets:
        text = [v for o in by_group.get(t['group'], ()) for v in o[4].values() if isinstance(v, str)]
        types = sorted({int(m.group(1)) for s in text for m in re.finditer(r'gsy\.activity\.type(\d+)', s)})
        ups = sorted({m.group(1) for s in text for m in re.finditer(r'(?<![\w.#])([\w.#]+?)\.count\.up\b', s)})
        kind = 6 if t['label'] == 'propaganda' else (types[0] if len(types) == 1 else None)
        if kind is not None or ups:
            out[f'{t["group"]:08x}'] = [kind, ups[0] if len(ups) == 1 else None]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', help='Just Cause 2 folder (default: found through Steam)')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'panau', 'data'))
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--counters', action='store_true', help='write only counters.json.gz')
    a = ap.parse_args()
    game = a.game
    if not game:
        from panau import steam
        game = steam.game_dir()
    targets, cells, link, cnt = build(game)
    sett = settlements(game)
    print(f'targets {len(targets["targets"])} ignored {len(targets["ignored"])} settlements {len(sett)} pipelines {len(link)}')
    if a.counters:
        shipped = {t['group'] for t in json.load(gzip.open(os.path.join(a.out, 'targets.json.gz'), 'rt', encoding='utf-8'))['targets']}
        cnt = {g: v for g, v in cnt.items() if int(g, 16) in shipped}
        with gzip.open(os.path.join(a.out, 'counters.json.gz'), 'wt', encoding='utf-8') as f:
            json.dump(cnt, f, separators=(',', ':'))
        print(f'counters for {len(cnt)} of {len(shipped)} shipped targets written to', a.out)
        return
    if a.check:
        with gzip.open(os.path.join(a.out, 'targets.json.gz'), 'rt', encoding='utf-8') as f:
            old = {t['group']: t for t in json.load(f)['targets']}
        new = {t['group']: t for t in targets['targets']}
        moved = sorted(math.dist(old[g]['pos'], new[g]['pos']) for g in old.keys() & new.keys())
        print(f'groups: {len(old.keys() & new.keys())} shared, {len(old.keys() - new.keys())} only in shipped data, '
              f'{len(new.keys() - old.keys())} only in the rebuild')
        print(f'labels differing: {sum(old[g]["label"] != new[g]["label"] for g in old.keys() & new.keys())}')
        if moved:
            print(f'position difference: median {moved[len(moved) // 2]:.1f} m, 95% {moved[int(len(moved) * .95)]:.1f} m, max {moved[-1]:.1f} m')
        return
    os.makedirs(a.out, exist_ok=True)
    with gzip.open(os.path.join(a.out, 'targets.json.gz'), 'wt', encoding='utf-8') as f:
        json.dump(targets, f, separators=(',', ':'))
    with gzip.open(os.path.join(a.out, 'group_cells.json.gz'), 'wt', encoding='utf-8') as f:
        json.dump(cells, f, separators=(',', ':'))
    json.dump(sett, open(os.path.join(a.out, 'settlements.json'), 'w'), indent=1)
    json.dump(link, open(os.path.join(a.out, 'pipeline_panels.json'), 'w'), indent=1)
    with gzip.open(os.path.join(a.out, 'counters.json.gz'), 'wt', encoding='utf-8') as f:
        json.dump(cnt, f, separators=(',', ':'))
    print('written to', a.out)


if __name__ == '__main__':
    main()
