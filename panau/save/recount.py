"""Tallies the game shows but never recounts, recounted from what the save records as done.

Next to the progress itself (objects destroyed, items picked up, locations discovered) the game keeps tallies that it
only ever adds 1 to, per event:
  - faction items: stats 333 (skulls), 334 (black boxes), 335 (drug drops); the total in 336 and 370
  - locations discovered: stat 316 (the 360 in the location list + region titles)
  - each activity type's "destroyed" count: stat 349 + 3 * type (fuel depots = type 01 -> 352, generators = 17 -> 400)
  - collectibles: stats 326 (weapon parts), 327 (vehicle parts), 328 (armor), 329 (cash); the total in 331
  - each settlement's counter (its completion), raised by the '<settlement>.count.up' events of its objects
A merge that brings progress over from another save without its tallies leaves them short: the game then shows
things missing that are already done and never come back.

Each tally = what it counts in the save + an offset (things the game counted that the data can't see, or the
reverse), and the offset stays the same as you play: every new event raises both. So, given the two original saves:
    tally = max(now, counted now + offset in the originals)
which only ever raises a tally and gives the same answer when run again (see offsets() for which offset). Without the
originals the offset is 0.
Verified on two unmerged saves (Casual and Hardcore): the faction items and 14 of the 20 activity types match with
offset 0 in both; the rest have small, steady offsets.
"""
import struct
from collections import Counter

from panau import data
from panau.save import sections, world
from panau.save.format import u32
from panau.save.progress import FACTION_ITEMS, FACTION_TOTALS, faction_items

DISCOVERED = 316
RESOURCE = {'weapon part': 326, 'vehicle part': 327, 'armor': 328, 'cash': 329}
RESOURCE_TOTAL = 331
TYPE_BASE = 349


def _type_stat(t):
    return TYPE_BASE + 3 * t


def counted(save):
    """{tally key: count from the save's own records}. Keys: ('stat', n) and ('settlement', location id)."""
    w = world.states(save['world'])
    collected = {struct.unpack('<I', d[4:])[0] for k, d in save['collected'] if k}
    sams = world.sam_done(save['items'])
    cnt, out = data.counters(), Counter()
    by_grid = Counter()
    for kind, label, g, _ in data.targets():
        if kind == 'item':
            done = g in collected or world.is_done(w.get(g, {}))
        elif label == 'SAM site':
            done = g in sams
        else:
            done = world.is_done(w.get(g, {}))
        if not done:
            continue
        if kind == 'item' and label in RESOURCE:
            out[('stat', RESOURCE[label])] += 1
            out[('stat', RESOURCE_TOTAL)] += 1
        atype, grid = cnt.get(g, (None, None))
        if atype is not None:
            out[('stat', _type_stat(atype))] += 1
        if grid:
            by_grid[grid] += 1
    found = faction_items(save)
    for k, stat in FACTION_ITEMS.items():
        out[('stat', stat)] = found[k]
    for stat in FACTION_TOTALS:
        out[('stat', stat)] = sum(found.values())
    out[('stat', DISCOVERED)] = len(sections.discovered(save['locations']))
    settlements = data.settlements()
    locs = dict(save['locations'])
    for i in range(360):
        lid = u32(locs[1 + 4 * i])
        out[('settlement', lid)] = by_grid.get(settlements[lid]['grid'], 0)
    return out


def values(save):
    """{tally key: the value the save holds now}."""
    stats = dict(save['stats'])
    out = {}
    for k, d in stats.items():
        if len(d) == 4 and (k in (DISCOVERED, RESOURCE_TOTAL, *RESOURCE.values(), *FACTION_ITEMS.values(), *FACTION_TOTALS)
                            or (TYPE_BASE < k <= TYPE_BASE + 3 * 31 and (k - TYPE_BASE) % 3 == 0)):
            out[('stat', k)] = u32(d)
    locs = dict(save['locations'])
    for i in range(360):
        out[('settlement', u32(locs[1 + 4 * i]))] = u32(locs[2 + 4 * i])
    return out


def offsets(originals):
    """{tally key: offset} from the original (unmerged) saves: the smaller of theirs, so nothing is credited that an
    original did not count (SAM sites destroyed in a story mission are done but never raised their settlement), and
    an original itself needs no fix. Except the locations: their offset is the region titles discovered, which no
    save lists, so the merged save has the larger of the two."""
    per = []
    for s in originals:
        c, v = counted(s), values(s)
        per.append({k: v[k] - c.get(k, 0) for k in v})
    out = {}
    for k in set().union(*per) if per else ():
        have = [p[k] for p in per if k in p]
        out[k] = max(have) if k == ('stat', DISCOVERED) else min(have)
    return out


def fixes(save, originals=()):
    """{tally key: (now, should be)} for every tally that is short."""
    c, v, off = counted(save), values(save), offsets(originals)
    out = {}
    for k, now in v.items():
        should = c.get(k, 0) + off.get(k, 0)
        if should > now:
            out[k] = (now, should)
    return out


def apply(save, fx):
    """Writes the fixes into the save (in memory)."""
    stats = {k[1]: new for k, (_, new) in fx.items() if k[0] == 'stat'}
    if stats:
        save['stats'] = [(k, struct.pack('<I', stats[k]) if k in stats else d) for k, d in save['stats']]
    sett = {k[1]: new for k, (_, new) in fx.items() if k[0] == 'settlement'}
    if sett:
        rows = list(save['locations'])
        pos = {k: n for n, (k, _) in enumerate(rows)}
        d = dict(rows)
        for i in range(360):
            lid = u32(d[1 + 4 * i])
            if lid in sett:
                rows[pos[2 + 4 * i]] = (2 + 4 * i, struct.pack('<I', sett[lid]))
        save['locations'] = rows


def describe(fx):
    """Human-readable lines, grouped."""
    names = {DISCOVERED: 'locations discovered', RESOURCE_TOTAL: 'collectibles total', 336: 'faction items total',
             370: 'faction items total (2)'}
    names.update({v: f'{k}s collected' for k, v in RESOURCE.items()})
    names.update({stat: {'csk': 'skulls', 'cbb': 'black boxes', 'cdd': 'drug drops'}[k] for k, stat in FACTION_ITEMS.items()})
    labels = {}
    for kind, label, g, _ in data.targets():
        t = data.counters().get(g, (None, None))[0]
        if t is not None:
            labels.setdefault(_type_stat(t), Counter())[label] += 1
    settlements = data.settlements()
    out, sett = [], []
    for (kind, k), (old, new) in sorted(fx.items(), key=lambda kv: (kv[0][0] != 'stat', kv[0][1])):
        if kind == 'stat':
            label = labels[k].most_common(1)[0][0] if k in labels else None
            plural = {'propaganda': 'propaganda trailers'}.get(label, f'{label}s')
            name = names.get(k) or (f'{plural} destroyed' if label else f'stat {k}')
            out.append(f'{name} (stat {k}): {old} -> {new}')
        else:
            sett.append(f'{settlements[k]["grid"]} {old}->{new}')
    if sett:
        out.append(f'settlement counters ({len(sett)}): ' + ', '.join(sett))
    return out
