"""The game data the tools need, extracted from Just Cause 2's own files (see tools/build_data.py and docs in the
README). Positions are world coordinates in metres (x east, y up, z north).

- targets.json.gz       every completion target: collectibles (weapon/vehicle/armor parts, cash) and sabotage targets
                        (the groups the game itself tags with an "act_*" objective marker), plus propaganda trailers and
                        pipelines; "ignored" = parked helicopters that carry a marker but should not get arrows
- done_flags.json       world-table type key -> the bit value that means destroyed/collected (see save/world.py)
- pipeline_panels.json  pipeline control panel group -> pipeline group (pipelines are sabotaged at the panel)
- settlements.json      the 405 locations; a save's location id is the index in this list
- group_cells.json.gz   target group -> the placement cell (map tile) it lives in, used to credit settlement counters
"""
import functools
import gzip
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _json(name):
    path = os.path.join(HERE, name)
    if name.endswith('.gz'):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    with open(path, encoding='utf-8') as f:
        return json.load(f)


@functools.lru_cache(maxsize=None)
def targets():
    """[(kind, label, group, (x, y, z))], kind 'item' or 'sabotage'."""
    return [(t['kind'], t['label'], t['group'], tuple(t['pos'])) for t in _json('targets.json.gz')['targets']]


@functools.lru_cache(maxsize=None)
def ignored():
    return [(t['label'], t['group'], tuple(t['pos'])) for t in _json('targets.json.gz')['ignored']]


@functools.lru_cache(maxsize=None)
def done_flags():
    """{4-byte type key: bit meaning done}."""
    return {bytes.fromhex(k): v for k, v in _json('done_flags.json').items()}


@functools.lru_cache(maxsize=None)
def pipeline_panels():
    return {int(k, 16): int(v, 16) for k, v in _json('pipeline_panels.json').items()}


@functools.lru_cache(maxsize=None)
def settlements():
    return _json('settlements.json')


@functools.lru_cache(maxsize=None)
def group_cells():
    return {int(k, 16): v for k, v in _json('group_cells.json.gz').items()}
