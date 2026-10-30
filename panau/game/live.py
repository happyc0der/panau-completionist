"""What is still left to do, kept up to date while you play.

Three sources, cheapest and most real-time first:
  1. the game's loaded objective markers and pickups (game memory lists, read 5x a second): an objective's marker
     flips to "destroyed" the instant it blows up, a pickup's flag the instant you grab it. Only loaded near you.
  2. the game's in-memory progress table: the same hash table the save stores, committed by the game every 1-2
     minutes. Found once per session by searching memory for a run of keys from the save, then read every 2 s.
  3. the newest save file: re-read in the background whenever the game writes it.

Rules learned the hard way:
  - a marker saying "destroyed" (status bit 0 clear) hides its target immediately.
  - a marker saying "standing" never overrides the save: objects copied as destroyed by a save merge keep a stale
    "standing" marker forever. It does undo what was seen destroyed live: a failed mission or a reload brings
    objects back (their markers stand again, and the progress table drops them).
  - SAM sites are tracked in the save's item lists, not the progress table (see save/world.py).
  - pipelines are sabotaged at a control panel. Its marker's status bit 0 clears the moment the pipeline is done
    (0x21 -> 0x20), like a sabotage marker's; a panel marker that disappears next to you counts too.
  - a sabotage marker that is not in the data is a prop or a mission marker, never a completion target.
"""
import collections
import ctypes
import ctypes.wintypes as wt
import math
import os
import struct
import threading
import time

from panau import data, steam
from panau.game import addresses as A
from panau.game.memory import k32
from panau.save import world
from panau.save.format import EMPTY_KEY, WORLD_SLOTS, Save

TABLE_BYTES = WORLD_SLOTS * 8
BITS_BYTES = (WORLD_SLOTS + 7) // 8


class MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p), ('AllocationProtect', wt.DWORD),
                ('PartitionId', wt.WORD), ('RegionSize', ctypes.c_size_t), ('State', wt.DWORD), ('Protect', wt.DWORD),
                ('Type', wt.DWORD)]


k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]


def camera(game):
    """(right, up, back, position, x scale, y scale) of the render camera, or None (menus, loading)."""
    if not game.attach():
        return None
    ptr = game.u32(A.CAMERA)
    raw = game.read(ptr + A.CAMERA_MATRIX, 128) if ptr else None
    if not raw:
        return None
    q = struct.unpack('<32f', raw)
    R, U, B, T, sx, sy = q[0:3], q[4:7], q[8:11], q[12:15], q[16], q[21]
    if not all(abs(sum(v * v for v in a) - 1) < 0.01 for a in (R, U, B)) or not (0.3 < sx < 10 and 0.3 < sy < 10):
        return None
    if not (abs(T[0]) < 17000 and abs(T[2]) < 17000 and -100 < T[1] < 5000):
        return None
    return R, U, B, T, sx, sy


class Progress:
    def __init__(self, game):
        self.game = game
        self.flags = {k: v for k, v in data.done_flags().items()}
        self.panel_link = data.pipeline_panels()
        self.collected, self.sam_done = set(), set()       # from the save
        self.done_groups = set()                           # from the progress table (save, then live)
        self.live_collected, self.live_destroyed = set(), set()
        self.inactive = set()                              # not objectives right now (see Overlay.check_inactive)
        self.alive_pos, self.panels_prev, self.panels_now = {}, {}, {}
        self.save_keys = self.save_bits = None
        self.stamp, self.next_save, self.parsing = None, 0.0, False
        self.table_at, self.table_pid, self.next_table, self.locating = None, None, 0.0, False
        self.last_t = self.last_bits = None
        self.slot_info, self.g_slots = {}, {}

    # --- the save ---------------------------------------------------------------------------------------------------
    def refresh(self):
        now = time.time()
        if now >= self.next_save and not self.parsing:
            self.next_save = now + 2
            try:
                newest = steam.newest_save()
                stamp = (newest, os.path.getmtime(newest))
            except (steam.NotFound, OSError):
                stamp = None
            if stamp and stamp != self.stamp:
                self.parsing = True
                threading.Thread(target=self._read_save, args=stamp, daemon=True).start()
        self._table()

    def _read_save(self, path, mtime):
        try:
            s = Save.load(path)
            self.collected = {struct.unpack('<I', d[4:])[0] for k, d in s['collected'] if k}
            d = dict(s['world'])
            self.save_keys, self.save_bits = d[9], d[10]
            self.sam_done = world.sam_done(s['items'])
            if not self.table_at:
                self._apply(self.save_keys, self.save_bits)
            self.stamp = (path, mtime)
        except Exception as e:                             # a half-written save: try again on the next change
            print('save read failed:', e)
        finally:
            self.parsing = False

    # --- the progress table -----------------------------------------------------------------------------------------
    def _apply(self, t, bits):
        done = set()
        self.slot_info, self.g_slots = {}, collections.defaultdict(list)
        for i in range(WORLD_SLOTS):
            key = t[i * 8:i * 8 + 8]
            if key == EMPTY_KEY:
                continue
            want = self.flags.get(key[:4])
            if want is None:
                continue
            g = struct.unpack('<I', key[4:])[0]
            self.slot_info[i] = (g, want); self.g_slots[g].append(i)
            if ((bits[i >> 3] >> (i & 7)) & 1) == want:
                done.add(g)
        self._set_done(done)
        self.last_t, self.last_bits = t, bits

    def _set_done(self, done):
        """A group the game had recorded as done and no longer does was undone (a failed mission, a reload): forget
        that it was seen destroyed or collected live as well."""
        undone = self.done_groups - done
        self.live_destroyed -= undone
        self.live_collected -= undone
        self.done_groups = done

    def _apply_changes(self, bits):
        touched = set()
        for j in range(len(bits)):
            if bits[j] != self.last_bits[j]:
                touched.update(self.slot_info[i][0] for i in range(j * 8, j * 8 + 8) if i in self.slot_info)
        done = set(self.done_groups)
        for g in touched:
            if any(((bits[i >> 3] >> (i & 7)) & 1) == self.slot_info[i][1] for i in self.g_slots[g]):
                done.add(g)
            else:
                done.discard(g)
        self._set_done(done)
        self.last_bits = bits

    def _table(self):
        if time.time() < self.next_table or not self.game.h or self.save_keys is None:
            return
        self.next_table = time.time() + 2.0
        if self.table_pid != self.game.pid:
            self.table_at, self.table_pid = None, self.game.pid
        if self.table_at:
            t = self.game.read(self.table_at, TABLE_BYTES)
            bits = self.game.read(self.table_at + A.WORLD_BITS_OFFSET, BITS_BYTES)
            if t and bits and t == self.last_t:
                if bits != self.last_bits:
                    self._apply_changes(bits)
                return
            same = t and sum(t[i:i + 8] == self.save_keys[i:i + 8] for i in range(0, TABLE_BYTES, 400))
            if t and bits and same > (TABLE_BYTES // 400) * 0.8:
                self._apply(t, bits)
                return
            self.table_at = None                           # rebuilt after a load: find it again
        if not self.locating:
            self.locating = True
            threading.Thread(target=self._locate, daemon=True).start()

    def _locate(self):
        """The table's address: an 8-aligned copy of a run of the save's keys with a matching bit array after it.
        Reads memory in 16 MB pieces with short pauses so the search never stalls the game."""
        try:
            run = next(i for i in range(0, TABLE_BYTES - 128, 8)
                       if all(self.save_keys[j:j + 8] != EMPTY_KEY for j in range(i, i + 128, 8)))
            probe = self.save_keys[run:run + 128]
            addr, m = 0, MBI()
            while addr < 0x7FFF0000 and k32.VirtualQueryEx(self.game.h, ctypes.c_void_p(addr), ctypes.byref(m), ctypes.sizeof(m)):
                base, size = m.BaseAddress or 0, m.RegionSize
                readable = m.State == 0x1000 and m.Protect in (0x04, 0x40) and size < 0x20000000
                for off in (range(0, size, 0x1000000) if readable else ()):
                    b = self.game.read(base + off, min(0x1000000 + 128, size - off)) or b''
                    time.sleep(0.003)
                    i = b.find(probe)
                    while i >= 0:
                        at = base + off + i - run
                        bits = self.game.read(at + A.WORLD_BITS_OFFSET, BITS_BYTES)
                        if at % 8 == 0 and bits and sum(x == y for x, y in zip(bits, self.save_bits)) > BITS_BYTES * 0.8:
                            self.table_at = at
                            return
                        i = b.find(probe, i + 1)
                addr = base + size
        finally:
            self.locating = False

    # --- live lists ---------------------------------------------------------------------------------------------------
    def pickups(self):
        got, there, p, n = set(), set(), self.game.u32(A.PICKUP_HEAD) or 0, 0
        while p and n < 2000:
            b = self.game.read(p, 0x48)
            if not b or struct.unpack_from('<I', b, 0)[0] != A.PICKUP_VTABLE:
                break
            (got if b[A.PICKUP_COLLECTED] else there).add(struct.unpack_from('<I', b, A.PICKUP_GROUP)[0])
            p = struct.unpack_from('<I', b, A.PICKUP_NEXT)[0]; n += 1
        self.live_collected |= got
        self.live_collected -= there - got                 # lying there again: a failed mission or a reload

    def markers(self):
        """[(group, type, standing, (x, y, z))] for every loaded sabotage/item marker; records destroyed ones, and
        forgets ones seen destroyed whose markers stand again (a failed mission or a reload undid them)."""
        out, panels, p, n = [], {}, self.game.u32(A.MARKER_HEAD) or 0, 0
        down, up = set(), set()
        while p and n < 3000:
            b = self.game.read(p, 0xC0)
            if not b or struct.unpack_from('<I', b, 0)[0] != A.MARKER_VTABLE:
                break
            typ = b[A.MARKER_TYPE]
            g = struct.unpack_from('<I', b, A.MARKER_GROUP)[0]
            pos = struct.unpack_from('<3f', b, A.MARKER_POS)
            standing = bool(b[A.MARKER_STATUS] & 1)
            if g in self.panel_link:
                panels[g] = (typ, pos)
                (up if standing else down).add(self.panel_link[g])
            if (typ == A.MARKER_SABOTAGE or typ in A.MARKER_ITEMS) and abs(pos[0]) < 17000 and abs(pos[2]) < 17000:
                if typ == A.MARKER_SABOTAGE:
                    (up if standing else down).add(g)
                out.append((g, typ, standing, pos))
            p = struct.unpack_from('<I', b, A.MARKER_NEXT)[0]; n += 1
        self.live_destroyed |= down
        self.live_destroyed -= up - down
        self.panels_prev, self.panels_now = self.panels_now, panels
        return out

    def vanished(self, markers, cam_pos):
        """Markers that disappear next to you (within 120 m; the game unloads them only far away) were destroyed:
        standing sabotage markers, and pipeline control panels."""
        if not markers:                                    # a load or a menu, not destruction
            return
        near = lambda q: math.hypot(q[0] - cam_pos[0], q[2] - cam_pos[2]) < 120
        for g, (typ, q) in self.panels_prev.items():
            if typ == A.MARKER_PANEL and g not in self.panels_now and near(q):
                self.live_destroyed.add(self.panel_link[g])
        now = {g: q for g, typ, standing, q in markers if typ == A.MARKER_SABOTAGE and standing}
        for g, q in self.alive_pos.items():
            if g not in now and near(q):
                self.live_destroyed.add(g)
        self.alive_pos = now

    # --- the answer ---------------------------------------------------------------------------------------------------
    def remaining(self, target):
        kind, label, g, _ = target
        if kind == 'item':
            return g not in self.collected and g not in self.done_groups and g not in self.live_collected
        if g in self.done_groups or g in self.live_destroyed or g in self.inactive:
            return False
        if label == 'SAM site':
            return g not in self.sam_done
        return True
