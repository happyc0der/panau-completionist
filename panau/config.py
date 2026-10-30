"""Settings, kept in %APPDATA%\\panau-completionist\\config.json. Missing keys fall back to DEFAULTS, so the file
only needs the values someone changed."""
import json
import os

DIR = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'panau-completionist')
PATH = os.path.join(DIR, 'config.json')

DEFAULTS = {
    # "earned": overlay, cheats and wingsuit unlock once the newest save shows the story finished (mercenary
    # mode) on Hardcore. "always": available from the start.
    'unlock': 'earned',
    'overlay': {
        'ranges_m': [250, 500, 1500, 5000, 0],   # F6 cycles these; 0 = arrows off
        'start_range': 1,                         # index into ranges_m
        'max_arrows': 15,                         # nearest on-screen arrows drawn
        'edge_arrows': 4,                         # nearest off-screen targets get an arrow at the screen edge
        'show_radar': False,                      # the small top-right radar (F7 toggles)
        'borderless': True,                       # stretch a windowed game over the whole screen
    },
    'cheats': {'health': True, 'ammo': True, 'reserve_min': 150},
    'launch': {'overlay': True, 'cheats': True},
    'game_dir': None,                             # override the Steam library search
    'save_dir': None,                             # override the Steam userdata search
}


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(base[k], v) if isinstance(base.get(k), dict) and isinstance(v, dict) else v
    return out


def load():
    try:
        with open(PATH, encoding='utf-8') as f:
            return _deep_merge(DEFAULTS, json.load(f))
    except (OSError, ValueError):
        return _deep_merge(DEFAULTS, {})


def set_value(dotted_key, value):
    """Change one setting, e.g. set_value('unlock', 'always') or set_value('cheats.ammo', False)."""
    try:
        with open(PATH, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    node = data
    keys = dotted_key.split('.')
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    os.makedirs(DIR, exist_ok=True)
    with open(PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    return load()
