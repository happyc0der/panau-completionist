"""Infinite health and ammo, by keeping two numbers topped up in game memory (10 checks a second for health, one a
second for ammo). Nothing is patched or injected; every pointer is re-resolved and sanity-checked on every check,
and nothing is written while the values don't look like a live player (menus, loading screens, death).

  health: kept at max while you are alive (a dead character is left alone, so dying still works)
  ammo:   every carried gun's clip kept full, its reserve kept at least cheats.reserve_min

Keys (while the game is focused): F10 health on/off, F11 ammo on/off (high beep = on, low = off).
"""
import struct
import time
import winsound

from panau import config
from panau.game import addresses as A
from panau.game.memory import Game, lower_own_priority, single_instance, user32

VK_F10, VK_F11 = 0x79, 0x7A


class Cheats:
    def __init__(self, game, reserve_min):
        self.g, self.reserve_min = game, reserve_min

    def character(self):
        mgr = self.g.u32(A.CHARACTER_MANAGER)
        player = self.g.u32(mgr + A.PLAYER) if mgr else None
        return self.g.u32(player + A.CHARACTER) if player else None

    def keep_health(self, char):
        mx, hp = self.g.f32(char + A.HEALTH_MAX), self.g.f32(char + A.HEALTH)
        if mx is None or hp is None or not 50 <= mx <= 20000 or not 0 < hp <= mx * 1.01:
            return False
        if hp < mx:
            self.g.write(char + A.HEALTH, struct.pack('<f', mx))
        return True

    def clip_size(self, weapon, sizes):
        up = self.g.u32(weapon + A.WEAPON_UPGRADE)
        if up:
            b = self.g.read(up + 0x1A, 2)
            if b:
                lvl = 5 if b[0] else b[1]
                if 0 <= lvl <= 5:
                    return int(sizes[lvl])
        return int(max(sizes))                              # level unknown: the largest clip any level has

    def keep_ammo(self, char):
        inv = self.g.u32(char + A.INVENTORY)
        if not inv:
            return False
        seen_types = set()
        for i in range(16):
            w = self.g.u32(inv + A.WEAPON_SLOT + i * 8)
            if not w or w < 0x10000:
                continue
            wdata, clip = self.g.u32(w + A.WEAPON_DATA), self.g.i32(w + A.WEAPON_CLIP)
            if not wdata or clip is None or not -1 <= clip <= 2000:
                continue
            atype, raw = self.g.i32(wdata + A.AMMO_TYPE), self.g.read(wdata + A.CLIP_SIZES, 24)
            if atype is None or raw is None or not 0 <= atype < 32:
                continue                                    # e.g. the grappling hook
            sizes = struct.unpack('<6f', raw)
            if not all(0 <= s <= 2000 for s in sizes):
                continue
            full = self.clip_size(w, sizes)
            if full >= 1 and 0 <= clip < full:
                self.g.write(w + A.WEAPON_CLIP, struct.pack('<i', full))
            if atype not in seen_types:
                seen_types.add(atype)
                res = self.g.i32(inv + A.RESERVE + 4 * atype)
                if res is not None and 0 <= res < self.reserve_min:
                    self.g.write(inv + A.RESERVE + 4 * atype, struct.pack('<i', self.reserve_min))
        return True


def main(wait=True):
    lower_own_priority()
    if not single_instance('cheats'):
        return 0
    cfg = config.load()['cheats']
    g = Game(write=True)
    for _ in range(600 if wait else 1):                    # wait up to 10 minutes for the game
        if g.attach():
            break
        time.sleep(1)
    else:
        print('Just Cause 2 is not running')
        return 1
    time.sleep(3)
    if not A.build_ok(g):
        print('this JustCause2.exe is not the build these addresses were found in; refusing to write to it')
        return 1
    c = Cheats(g, cfg['reserve_min'])
    on = {'health': cfg['health'], 'ammo': cfg['ammo']}
    was_down, n = {VK_F10: False, VK_F11: False}, 0
    while g.attach():
        n += 1
        if g.is_foreground():
            for vk, key in ((VK_F10, 'health'), (VK_F11, 'ammo')):
                down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                if down and not was_down[vk]:
                    on[key] = not on[key]
                    winsound.Beep(1200 if on[key] else 500, 120)
                was_down[vk] = down
        char = c.character()
        if char:
            if on['health']:
                c.keep_health(char)
            if on['ammo'] and n % 10 == 0:
                c.keep_ammo(char)
        time.sleep(0.1)
    return 0
