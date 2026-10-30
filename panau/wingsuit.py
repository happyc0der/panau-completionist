"""Install or remove a community wingsuit mod. The mods are other people's work, so they are not included: download
one of them yourself and point `panau wingsuit install` at the zip.

  "JC2 Wingsuit Mod" by mctheminer (2017, inspired by Just Cause 3)
      https://videogamemods.com/vgm/justcause2/mods/jc2-wingsuit-mod
      Replaces DLC\\pc_140.arc/.tab and adds 5 files to dropzone\\. Jump, glide, Space = fly, Shift = faster,
      Space again = stop. Speed: Black Market > Equipment > "Slow Flying" / "Fast Flying".
  "Just Cause 2 Wingsuit (Or Superman)" (2010)
      https://videogamemods.com/vgm/justcause2/mods/just-cause-2-wingsuit-or-superman
      Adds archives_win32\\x_jj_wingsuit.arc/.tab. Deploy like the parachute, slingshot to speed up.

Only one is installed at a time; installing one removes the other. The original DLC\\pc_140 files are backed up once
and put back on remove. Close the game first.
"""
import json
import os
import shutil
import zipfile

from panau import config, steam
from panau.game.memory import find_pid

BACKUP = os.path.join(config.DIR, 'backups', 'wingsuit')
MANIFEST = os.path.join(config.DIR, 'wingsuit.json')


def _kind(names):
    low = [n.replace('\\', '/').lower() for n in names]
    if any(n.endswith('dlc/pc_140.arc') for n in low) and any('/dropzone/' in n or n.startswith('dropzone/') for n in low):
        return '2017'
    if any(n.endswith('x_jj_wingsuit.arc') for n in low):
        return '2010'
    return None


def status():
    try:
        with open(MANIFEST, encoding='utf-8') as f:
            m = json.load(f)
        return f"installed: the {m['kind']} mod ({len(m['files'])} files)"
    except (OSError, ValueError):
        return 'not installed'


def remove():
    if find_pid():
        return 'close Just Cause 2 first'
    game = steam.game_dir()
    try:
        with open(MANIFEST, encoding='utf-8') as f:
            m = json.load(f)
    except (OSError, ValueError):
        return 'not installed'
    for rel in m['files']:
        p = os.path.join(game, rel)
        if os.path.exists(p):
            os.remove(p)
    for name in ('pc_140.arc', 'pc_140.tab'):
        if os.path.exists(os.path.join(BACKUP, name)):
            shutil.copy2(os.path.join(BACKUP, name), os.path.join(game, 'DLC', name))
    drop = os.path.join(game, 'dropzone')
    if os.path.isdir(drop) and not os.listdir(drop):
        os.rmdir(drop)
    os.remove(MANIFEST)
    return 'removed; the game is back to its own files'


def install(zip_path):
    if find_pid():
        return 'close Just Cause 2 first'
    game = steam.game_dir()
    with zipfile.ZipFile(zip_path) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        kind = _kind(names)
        if not kind:
            return 'this zip is neither of the two supported wingsuit mods'
        if os.path.exists(MANIFEST):
            remove()
        os.makedirs(BACKUP, exist_ok=True)
        files = []
        for n in names:
            low = n.replace('\\', '/').lower()
            base = os.path.basename(n)
            if kind == '2017' and low.endswith(('dlc/pc_140.arc', 'dlc/pc_140.tab')):
                dest_rel = os.path.join('DLC', base)
                if not os.path.exists(os.path.join(BACKUP, base)):
                    shutil.copy2(os.path.join(game, dest_rel), os.path.join(BACKUP, base))
            elif kind == '2017' and '/dropzone/' in '/' + low:
                dest_rel = os.path.join('dropzone', base)
                files.append(dest_rel)
            elif kind == '2010' and base.lower().startswith('x_jj_wingsuit.'):
                dest_rel = os.path.join('archives_win32', base)
                files.append(dest_rel)
            else:
                continue                                    # readme, the mod's own backup folder
            os.makedirs(os.path.dirname(os.path.join(game, dest_rel)), exist_ok=True)
            with z.open(n) as src, open(os.path.join(game, dest_rel), 'wb') as dst:
                shutil.copyfileobj(src, dst)
    os.makedirs(config.DIR, exist_ok=True)
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump({'kind': kind, 'files': files}, f, indent=1)
    return f'installed the {kind} wingsuit mod'
