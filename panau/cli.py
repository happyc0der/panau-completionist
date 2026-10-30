"""panau: the command line. Run `panau` with no arguments for a status overview."""
import argparse
import os
import shutil
import sys
import time

from panau import __version__, config, steam


def cmd_status(_):
    from panau import crashfix, unlock, wingsuit
    from panau.game.memory import find_pid
    from panau.save import progress
    print(f'panau-completionist {__version__}')
    for label, fn in (('game', steam.game_dir), ('saves', steam.save_dir)):
        try:
            print(f'  {label:10} {fn()}')
        except steam.NotFound as e:
            print(f'  {label:10} NOT FOUND: {e}')
    try:
        path = steam.newest_save()
        s = progress.load_summary(path)
        print(f'  {"save":10} {os.path.basename(path)}: {s["difficulty_name"]}, story '
              f'{"finished" if s["story_finished"] else "not finished"}, {s["collected"]} collectibles')
    except (steam.NotFound, OSError, ValueError) as e:
        print(f'  {"save":10} {e}')
    ok, why = unlock.status()
    print(f'  {"unlock":10} {why}')
    try:
        print(f'  {"crash fix":10} {crashfix.state()}')
        print(f'  {"wingsuit":10} {wingsuit.status()}')
    except steam.NotFound:
        pass
    print(f'  {"running":10} {"yes" if find_pid() else "no"}')
    print(f'  {"config":10} {config.PATH}')
    return 0


def _backup_once(path):
    dest = os.path.join(config.DIR, 'backups', os.path.basename(path) + '.before-panau')
    if os.path.exists(path) and not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(path, dest)
        return dest
    return None


def cmd_merge(a):
    from panau.game.memory import find_pid
    from panau.save import merge
    out, report = merge.merge(a.base, a.other, difficulty=a.difficulty, take_missions=a.take_missions)
    for line in report:
        print(' ', line)
    if not a.out:
        print('(dry run: nothing written; pass --out FILE to write the merged save)')
        return 0
    target = a.out
    if a.out.isdigit():                                      # a slot number: write JustCause2Save0N.sav
        target = os.path.join(steam.save_dir(), f'JustCause2Save{int(a.out):02d}.sav')
    if os.path.abspath(os.path.dirname(target)) == os.path.abspath(steam.save_dir()) and find_pid():
        print('close Just Cause 2 first: it would overwrite the save on its next autosave')
        return 1
    kept = _backup_once(target)
    with open(target, 'wb') as f:
        f.write(out)
    print(f'written: {target}' + (f' (the previous file is kept at {kept})' if kept else ''))
    print('Load it in game; the game rewrites the autosave right after loading. Run `panau audit` afterwards.')
    return 0


def cmd_audit(a):
    from panau.save import audit
    current = a.save or steam.newest_save()
    print(f'checking {current} against {", ".join(a.others)}')
    misses = {k: v for k, v in audit.objectives(current, a.others).items() if v[0]}
    print('  completion targets done elsewhere but not here:', misses or 'none')
    diffs = {k: v for k, v in audit.sections(current, a.others).items() if v}
    print('  sections where another save is better:', diffs or 'none')
    return 0 if not misses and not diffs else 1


def _gated(fn, *args):
    from panau import unlock
    if not unlock.require():
        return 1
    return fn(*args)


def cmd_overlay(a):
    from panau import overlay
    return _gated(overlay.main, a.wait)


def cmd_cheats(_):
    from panau import cheats
    return _gated(cheats.main)


def cmd_wingsuit(a):
    from panau import unlock, wingsuit
    if a.action == 'status':
        print(wingsuit.status()); return 0
    if a.action == 'remove':
        print(wingsuit.remove()); return 0
    if not a.zip:
        print('usage: panau wingsuit install <mod zip>'); return 2
    if not unlock.require():
        return 1
    print(wingsuit.install(a.zip)); return 0


def cmd_crashfix(a):
    from panau import crashfix
    from panau.game.memory import find_pid
    if a.action != 'status' and find_pid():
        print('close Just Cause 2 first'); return 1
    print({'status': lambda: crashfix.state(), 'apply': crashfix.apply, 'restore': crashfix.restore}[a.action]())
    return 0


def cmd_config(a):
    if a.key is None:
        print(config.PATH)
        import json
        print(json.dumps(config.load(), indent=2))
        return 0
    value = a.value
    for conv in (int, float):
        try:
            value = conv(value); break
        except (TypeError, ValueError):
            pass
    if value in ('true', 'false', 'null'):
        value = {'true': True, 'false': False, 'null': None}[value]
    config.set_value(a.key, value)
    print(f'{a.key} = {value!r}')
    return 0


def cmd_launch_option(_):
    exe = shutil.which('panau-launch') or shutil.which('panau-launch.exe')
    if not exe:
        print('panau-launch not found on PATH (install with: uv tool install <repo folder>)'); return 1
    print('Steam > Just Cause 2 > Properties > General > Launch Options:')
    print(f'"{exe}" %command%')
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog='panau', description='Just Cause 2 completionist tools (Steam, PC).')
    sub = p.add_subparsers(dest='cmd')
    sub.add_parser('status', help='what was found, unlock state, installed fixes').set_defaults(fn=cmd_status)
    m = sub.add_parser('merge', help='merge two saves, taking the best of both')
    m.add_argument('base', help='the save to build on (the one with the furthest story)')
    m.add_argument('other', help='the save to take extra progress from')
    m.add_argument('--out', help='output file, or a slot number (0-7) to write into the save folder; omit for a dry run')
    m.add_argument('--difficulty', type=int, choices=range(4), help='0 Casual .. 3 Hardcore (default: the higher of the two)')
    m.add_argument('--take-missions', action='store_true', help='also merge mission/faction progress (experimental)')
    m.set_defaults(fn=cmd_merge)
    au = sub.add_parser('audit', help='check a save holds the best of other saves (read-only)')
    au.add_argument('others', nargs='+', help='the original saves')
    au.add_argument('--save', help='the save to check (default: your newest)')
    au.set_defaults(fn=cmd_audit)
    o = sub.add_parser('overlay', help='on-screen arrows (the game must be running)')
    o.add_argument('--wait', action='store_true', help='wait for the game window first')
    o.set_defaults(fn=cmd_overlay)
    sub.add_parser('cheats', help='infinite health and ammo (the game must be running)').set_defaults(fn=cmd_cheats)
    w = sub.add_parser('wingsuit', help='install/remove a wingsuit mod from its zip')
    w.add_argument('action', choices=['install', 'remove', 'status'])
    w.add_argument('zip', nargs='?')
    w.set_defaults(fn=cmd_wingsuit)
    c = sub.add_parser('crashfix', help='the 16-byte fix for the common random crash')
    c.add_argument('action', choices=['status', 'apply', 'restore'])
    c.set_defaults(fn=cmd_crashfix)
    cf = sub.add_parser('config', help='show the config, or set one value: panau config unlock always')
    cf.add_argument('key', nargs='?')
    cf.add_argument('value', nargs='?')
    cf.set_defaults(fn=cmd_config)
    sub.add_parser('launch-option', help='print the Steam launch option for this PC').set_defaults(fn=cmd_launch_option)
    a = p.parse_args(argv)
    if not getattr(a, 'fn', None):
        return cmd_status(a)
    try:
        return a.fn(a)
    except steam.NotFound as e:
        print(e); return 1


if __name__ == '__main__':
    sys.exit(main())
