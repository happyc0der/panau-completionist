"""Find Steam, the Just Cause 2 install and the save folder on this PC."""
import glob
import os
import re

from panau import GAME_APPID
from panau import config

EXE_NAME = 'JustCause2.exe'


class NotFound(RuntimeError):
    pass


def steam_root():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            path = winreg.QueryValueEx(k, 'SteamPath')[0]
            if os.path.isdir(path):
                return os.path.normpath(path)
    except OSError:
        pass
    for path in (r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam'):
        if os.path.isdir(path):
            return path
    raise NotFound('Steam not found (no SteamPath in the registry)')


def library_folders(root=None):
    root = root or steam_root()
    folders = [root]
    vdf = os.path.join(root, 'steamapps', 'libraryfolders.vdf')
    if os.path.exists(vdf):
        text = open(vdf, encoding='utf-8', errors='replace').read()
        folders += [p.replace('\\\\', '\\') for p in re.findall(r'"path"\s+"([^"]+)"', text)]
    seen, out = set(), []
    for f in folders:
        key = os.path.normcase(os.path.normpath(f))
        if key not in seen:
            seen.add(key); out.append(os.path.normpath(f))
    return out


def game_dir():
    """The Just Cause 2 install folder (config "game_dir" overrides the search)."""
    override = config.load().get('game_dir')
    if override:
        return override
    for lib in library_folders():
        if os.path.exists(os.path.join(lib, 'steamapps', f'appmanifest_{GAME_APPID}.acf')):
            path = os.path.join(lib, 'steamapps', 'common', 'Just Cause 2')
            if os.path.exists(os.path.join(path, EXE_NAME)):
                return path
    raise NotFound('Just Cause 2 is not installed in any Steam library (set "game_dir" in the config)')


def save_dir():
    """The folder holding JustCause2SaveNN.sav (Steam Cloud keeps it per Steam account). With several accounts,
    the one with the newest save wins; config "save_dir" overrides."""
    override = config.load().get('save_dir')
    if override:
        return override
    best, best_t = None, -1.0
    for d in glob.glob(os.path.join(steam_root(), 'userdata', '*', str(GAME_APPID), 'remote')):
        for s in glob.glob(os.path.join(d, 'JustCause2Save*.sav')):
            t = os.path.getmtime(s)
            if t > best_t:
                best, best_t = d, t
    if not best:
        raise NotFound('no Just Cause 2 saves found under Steam\\userdata (set "save_dir" in the config)')
    return best


def newest_save():
    """The most recently written save: usually the autosave (Save00), which "Continue" loads."""
    files = [f for f in glob.glob(os.path.join(save_dir(), 'JustCause2Save*.sav')) if os.path.getsize(f) > 1]
    if not files:
        raise NotFound('no Just Cause 2 saves in ' + save_dir())
    return max(files, key=os.path.getmtime)
