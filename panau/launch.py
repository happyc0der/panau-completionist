"""Steam launch option entry point: starts the game with Steam's own command, then (when unlocked) the overlay and the
cheats, which close themselves when the game exits.

Steam > Just Cause 2 > Properties > Launch Options:
    "<path to panau-launch.exe>" %command%
(`panau launch-option` prints the exact line for this PC.) Extra game arguments go after %command%, e.g.
/frameratecap=120.
"""
import os
import subprocess
import sys

from panau import config, unlock

CREATE_NO_WINDOW = 0x08000000


def _spawn(module_args):
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
    subprocess.Popen([pyw if os.path.exists(pyw) else exe, '-m', 'panau'] + module_args, creationflags=CREATE_NO_WINDOW)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: panau-launch %command% [game arguments]  (set as the Steam launch option)')
        return 2
    subprocess.Popen(argv, cwd=os.path.dirname(argv[0]) or None)
    ok, why = unlock.status()
    log = os.path.join(config.DIR, 'launch.log')
    os.makedirs(config.DIR, exist_ok=True)
    with open(log, 'a', encoding='utf-8') as f:
        f.write(f'launch: {" ".join(argv)} | {why}\n')
    if not ok:
        return 0
    cfg = config.load()['launch']
    if cfg['cheats']:
        _spawn(['cheats'])
    if cfg['overlay']:
        _spawn(['overlay', '--wait'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
