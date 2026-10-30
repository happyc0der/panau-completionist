"""Read-only checks that a (merged) save holds the best of other saves.

objectives(): per completion-target kind, how many are done in one of the other saves but not in this one.
sections(): for every mergeable section, whether merging the other save in would still change anything.
"""
import collections
import struct

from panau import data
from panau.save import sections as S, world
from panau.save.format import Save


def _done_sets(save):
    w = world.states(save['world'])
    collected = {struct.unpack('<I', d[4:])[0] for k, d in save['collected'] if k}
    sams = world.sam_done(save['items'])
    done = set()
    for kind, label, g, _ in data.targets():
        if kind == 'item':
            if g in collected or world.is_done(w.get(g, {})):
                done.add(g)
        elif label == 'SAM site':
            if g in sams:
                done.add(g)
        elif world.is_done(w.get(g, {})):
            done.add(g)
    return done


def objectives(current_path, other_paths):
    cur = _done_sets(Save.load(current_path))
    others = set().union(*(_done_sets(Save.load(p)) for p in other_paths))
    totals, missing = collections.Counter(), collections.Counter()
    for _, label, g, _ in data.targets():
        totals[label] += 1
        if g in others and g not in cur:
            missing[label] += 1
    return {label: (missing[label], totals[label]) for label in totals}


# stats the game resets itself on the next save (two float records; seen 2026-10-30: merged to 19.07, back to 0 in
# the game's own next autosave), so a difference there is not something a merge can fix
GAME_MANAGED = {'stats': {315, 330}}

MERGEABLE = {'stats': S.merge_stats, 'flags59': S.merge_flags59, 'unlocks': S.merge_unlocks,
             'locations': S.merge_location_flags, 'activities': S.merge_activities,
             'factions': S.merge_factions, 'main': S.merge_main}


def sections(current_path, other_paths):
    cur = Save.load(current_path)
    out = {}
    for name, fn in MERGEABLE.items():
        diffs = 0
        for p in other_paths:
            o = Save.load(p)
            a, m = dict(cur[name]), dict(fn(cur[name], o[name]))
            skip = GAME_MANAGED.get(name, ())
            diffs += sum(1 for k in set(a) | set(m) if a.get(k) != m.get(k) and k not in skip)
        out[name] = diffs
    return out
