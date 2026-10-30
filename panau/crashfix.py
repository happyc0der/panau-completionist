"""A fix for Just Cause 2's most common random crash (Steam build).

The crash: an access violation reading address 0x224 at JustCause2.exe+0x209D00, with an identical call stack every
time. +0x209D00 is a 10-byte getter (mov eax,[ecx+0x224]; mov eax,[eax+8]; ret). Its caller walks a list of weak
references; when one of the objects is already gone, the game's own check fails (the release build carries on) and
the getter is called with ecx = NULL. The caller only uses the result as a map key, so returning 0 is harmless.

The patch rewrites the getter, using the 6 bytes of int3 padding after it:
    xor eax,eax ; test ecx,ecx ; jz ret ; mov eax,[ecx+0x224] ; mov eax,[eax+8] ; ret
Behaviour is unchanged whenever the object exists. Steam's "Verify integrity of game files" undoes it.
"""
import os
import shutil

from panau import config, steam

OFFSET = 0x209D00 - 0x1000 + 0x400                  # .text RVA 0x1000 -> file 0x400
ORIGINAL = bytes.fromhex('8b8124020000' '8b4008' 'c3' 'cccccccccccc')
PATCHED = bytes.fromhex('31c0' '85c9' '7409' '8b8124020000' '8b4008' 'c3')
BACKUP = os.path.join(config.DIR, 'backups', 'JustCause2.exe.orig')


def exe_path():
    return os.path.join(steam.game_dir(), steam.EXE_NAME)


def state(path=None):
    with open(path or exe_path(), 'rb') as f:
        f.seek(OFFSET)
        cur = f.read(16)
    return 'original' if cur == ORIGINAL else 'patched' if cur == PATCHED else 'unknown'


def apply():
    path = exe_path()
    st = state(path)
    if st != 'original':
        return f'not applied: the exe is {st}'
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    if not os.path.exists(BACKUP):
        shutil.copy2(path, BACKUP)
    with open(path, 'r+b') as f:
        f.seek(OFFSET)
        f.write(PATCHED)
    return f'patched (original kept at {BACKUP})'


def restore():
    if not os.path.exists(BACKUP):
        return 'no backup to restore'
    shutil.copy2(BACKUP, exe_path())
    return 'restored: ' + state()
