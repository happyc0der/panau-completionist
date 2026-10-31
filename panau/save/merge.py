"""Merge two saves: the base save, plus everything the other save has done that the base hasn't ("best of both").

What is merged (each step was verified in game: the game's next autosave kept it):
  - destroyed / collected objects: every completion target done in the other save and not in the base gets the other
    save's world-table state (all of its type keys, inserted properly into the hash table)
  - collected list: the other save's collectible ids for the collectibles brought over
  - resource stats 326-329/331 (parts and cash collected): raised by what was brought over
  - SAM sites: destroyed in the other save -> destroyed in the base
  - settlement counters: credited with the objects brought over (the game trusts these counters, it never recounts)
  - location discovery flags, stats (records and counters), flags59, black market unlocks, activities (missions,
    races, stunts, faction items; best race times): the better of the two
  - the tallies the game never recounts (faction items, locations discovered, each type's "destroyed" count, the
    collectible and settlement counters): recounted for the merged save (see recount.py)
  - difficulty: the higher of the two (or what you pass)
Missions and faction progress stay the base's unless take_missions=True (implemented, but not verified in game:
pick the save with the furthest story as the base).

The four item lists are not merged: their flags switch on and off during play, so "more" is not "better".
"""
import collections
import struct

from panau import data
from panau.save import recount, sections, world
from panau.save.format import Save, item_lists, u32

RESOURCE_STATS = {'e1162daa': 326, 'e6fb1698': 327, '5353acb9': 328, 'f8fc3159': 329}   # item list 2 key -> stat
RESOURCE_TOTAL = 331


def settlement_cells():
    out = {}
    for i, s in enumerate(data.settlements()):
        g = s['grid']
        out[i] = g[:-4] if g.endswith('base') and 'x' in g and g[:-4].replace('x', '').isdigit() else g
    return out


def bring_over(base, other, rewrite_collected=True):
    """Every completion target done in `other` and not in `base` gets other's world-table state (all of its type
    keys), and the collectibles among them other's collected-list ids. Edits base in place. Returns (groups brought
    over, collected ids added, collected list size). rewrite_collected=False leaves the collected list untouched when
    nothing is added."""
    target_groups = {g for _, _, g, _ in data.targets()}
    wa, wb = world.states(base['world']), world.states(other['world'])
    new_groups = [g for g, st in wb.items()
                  if g in target_groups and world.is_done(st) and not world.is_done(wa.get(g, {}))]
    if new_groups:
        base['world'] = world.copy_groups(base['world'], wb, new_groups)
    new_set = set(new_groups)
    ca = {d for k, d in base['collected'] if k}
    cb = {d for k, d in other['collected'] if k}
    add = {v for v in cb - ca if struct.unpack('<I', v[4:])[0] in new_set}
    ids = sorted(ca | add, key=lambda v: (struct.unpack('<I', v[4:])[0], struct.unpack('<I', v[:4])[0]))
    if add or rewrite_collected:
        base['collected'] = [(0, struct.pack('<I', len(ids)))] + [(i + 1, v) for i, v in enumerate(ids)]
    return new_groups, add, len(ids)


def merge(base_path, other_path, difficulty=None, take_missions=False):
    """Returns (merged file bytes, report lines). Nothing is written."""
    base, other = Save.load(base_path), Save.load(other_path)
    report = []

    # 1-2. objects done in the other save, and the collected list
    new_groups, add, total = bring_over(base, other)
    labels = {g: l for _, l, g, _ in data.targets()}
    report.append(f'objects brought over: {len(new_groups)} ' +
                  str(dict(collections.Counter(labels[g] for g in new_groups).most_common())))
    report.append(f'collectibles brought over: {len(add)} (total {total})')

    # 3. stats: the better of the two, then the resource counters = base + what was brought over
    kind = {}
    for s in (other, base):
        kind.update({k[4:]: k[:4].hex() for k in item_lists(s['items'])[2]})
    plus = collections.Counter(kind.get(v[4:]) for v in add)
    base_stats = dict(base['stats'])
    merged_stats = sections.merge_stats(base['stats'], other['stats'])
    out = []
    for k, v in merged_stats:
        if k in RESOURCE_STATS.values():
            t = next(t for t, s in RESOURCE_STATS.items() if s == k)
            v = struct.pack('<I', u32(base_stats[k]) + plus[t])
        elif k == RESOURCE_TOTAL:
            v = struct.pack('<I', u32(base_stats[k]) + sum(plus[t] for t in RESOURCE_STATS))
        out.append((k, v))
    base['stats'] = out

    # 4. SAM sites
    base['items'], sams = world.mark_sams(base['items'], world.sam_done(other['items']), other['items'])
    report.append(f'SAM sites marked destroyed: {sams}')

    # 5. settlement counters (credited with what was brought over) and discovery flags
    cells, gcell = settlement_cells(), data.group_cells()
    la, lb = dict(base['locations']), dict(other['locations'])
    cnt_b = {u32(lb[1 + 4 * i]): u32(lb[2 + 4 * i]) for i in range(360)}
    new_in_cell = collections.Counter(gcell.get(g) for g in new_groups)
    rows, changed = list(base['locations']), 0
    pos = {k: n for n, (k, _) in enumerate(rows)}
    for i in range(360):
        lid, a = u32(la[1 + 4 * i]), u32(la[2 + 4 * i])
        b = cnt_b.get(lid, 0)
        if b <= a:
            continue
        new = b if a == 0 else max(b, a + new_in_cell.get(cells.get(lid), 0))
        rows[pos[2 + 4 * i]] = (2 + 4 * i, struct.pack('<I', new)); changed += 1
    base['locations'] = sections.merge_location_flags(rows, other['locations'])
    report.append(f'settlement counters raised: {changed}')

    # 6. the rest: the better of the two
    base['activities'] = sections.merge_activities(base['activities'], other['activities'])
    base['flags59'] = sections.merge_flags59(base['flags59'], other['flags59'])
    base['unlocks'] = sections.merge_unlocks(base['unlocks'], other['unlocks'])
    report.append(f'black market unlocks: {u32(dict(base["unlocks"])[0])} + {u32(dict(base["unlocks"])[8])}')
    if take_missions:
        base['main'] = sections.merge_main(base['main'], other['main'])
        base['factions'] = sections.merge_factions(base['factions'], other['factions'])
        report.append('missions and factions: merged (experimental)')

    # 7. the tallies the game never recounts (faction items, locations, per-type, collectible and settlement counters):
    # the merged save's own records + the originals' offsets
    fx = recount.fixes(base, (Save.load(base_path), Save.load(other_path)))
    recount.apply(base, fx)
    report.append(f'tallies recounted: {len(fx)}')
    report.extend('  ' + line for line in recount.describe(fx))

    diff = max(base.difficulty, other.difficulty) if difficulty is None else difficulty
    base['difficulty'] = [(0, struct.pack('<I', diff))]
    report.append(f'difficulty: {diff}')
    money = u32(dict(base['main'])[4])
    return base.to_bytes(difficulty=diff, money=money), report
