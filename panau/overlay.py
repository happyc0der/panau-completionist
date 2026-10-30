"""On-screen arrows over every remaining completion target: white = collectibles, red = sabotage targets.

Arrows sit over targets in view; the nearest few off-screen targets get an arrow at the screen edge pointing their
way. Each arrow is its own tiny click-through window moved with SetWindowPos: moving a window costs the compositor
almost nothing, while repainting one full-screen transparent canvas cost ~8% of a CPU core.

Keys (while the game window is focused): F6 arrow range (from config, default 250/500/1500/5000 m/off),
F7 radar on/off, F8 radar range, F9 what to show (everything / collectibles / sabotage).
The game must run in a window or borderless window (fullscreen hides overlays); with overlay.borderless the
game window is stretched over the whole screen.
"""
import collections
import ctypes
import ctypes.wintypes as wt
import math
import os
import time
import tkinter as tk

from panau import config, data
from panau.game import addresses as A
from panau.game.live import Progress, camera
from panau.game.memory import Game, find_pid, lower_own_priority, single_instance, user32

ITEM_COLOR, SAB_COLOR = '#ffffff', '#ff2a2a'
ACCENT, KEY = '#a855f7', '#010203'                 # KEY = the transparent colour of the overlay windows
FILTERS = [('everything', None), ('collectibles', {'item'}), ('sabotage', {'sabotage'})]
RADAR_RANGES = [250, 500, 1000, 2500]
SWP_MOVE_SHOW = 0x0001 | 0x0004 | 0x0010 | 0x0040  # no resize, keep z-order, don't activate, show
EX_OVERLAY = 0x80000 | 0x20 | 0x80 | 0x08000000    # layered, click-through, no taskbar button, never takes focus


def game_window():
    return user32.FindWindowW(None, 'Just Cause 2')


def make_borderless():
    hwnd = game_window()
    if hwnd:
        user32.SetWindowLongW(hwnd, -16, 0x80000000 | 0x10000000)          # WS_POPUP | WS_VISIBLE
        user32.SetWindowPos(hwnd, 0, 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1), 0x0020 | 0x0040)


class CURSORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('flags', wt.DWORD), ('hCursor', wt.HANDLE), ('pt', wt.POINT)]


def menu_open(game):
    """True while the pause menu, the map or the black market is open. The first two show a mouse cursor, which play
    never does; the black market shows none but has a flag in the game."""
    ci = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
    if user32.GetCursorInfo(ctypes.byref(ci)) and ci.flags & 1:      # CURSOR_SHOWING
        return True
    return game.read(A.BLACK_MARKET_OPEN, 1) == bytes([1])


def game_rect():
    """The game's client area on screen, or None while another window is in front."""
    h = game_window()
    if not h or user32.GetForegroundWindow() != h:
        return None
    r = wt.RECT(); user32.GetClientRect(h, ctypes.byref(r))
    pt = wt.POINT(0, 0); user32.ClientToScreen(h, ctypes.byref(pt))
    return pt.x, pt.y, r.right, r.bottom


class Overlay:
    def __init__(self, cfg):
        self.cfg = cfg['overlay']
        self.ranges = self.cfg['ranges_m']
        self.state = {'range': self.cfg['start_range'], 'filter': 0, 'radar': self.cfg['show_radar'], 'radar_range': 1,
                      'targets': [], 'poi_targets': [], 'tver': 0, 'n': 0, 'keys': {}, 'moving': set(), 'last_pos': {}}
        self.targets = data.targets()
        self.ignored = data.ignored()
        self.target_groups = {t[2] for t in self.targets} | {i[1] for i in self.ignored}
        self.grid = collections.defaultdict(list)          # 500 m cells: a refresh only looks at nearby targets
        for t in self.targets:
            self.grid[(int(t[3][0] // 500), int(t[3][2] // 500))].append(t)
        self.game = Game()
        self.progress = Progress(self.game)
        self._build_windows()

    # --- windows ----------------------------------------------------------------------------------------------------
    def _layer(self, w, h):
        t = tk.Toplevel(self.root); t.overrideredirect(True); t.attributes('-topmost', True)
        t.configure(bg=KEY); t.attributes('-transparentcolor', KEY); t.geometry(f'{w}x{h}+-10000+-10000')
        cv = tk.Canvas(t, width=w, height=h, bg=KEY, highlightthickness=0); cv.pack()
        t.update()
        hw = user32.GetParent(t.winfo_id()) or t.winfo_id()
        user32.SetWindowLongW(hw, -20, user32.GetWindowLongW(hw, -20) | EX_OVERLAY)
        user32.ShowWindow(hw, 0)
        return cv, hw

    def _build_windows(self):
        self.root = tk.Tk(); self.root.withdraw()
        sh = user32.GetSystemMetrics(1)
        self.scale = sh / 2160
        self.font = ('Segoe UI', max(8, int(11 * self.scale)), 'bold')
        self.aw = int(40 * self.scale * 2.6) + 8
        n = self.cfg['max_arrows'] + self.cfg['edge_arrows']
        self.wins = []
        for _ in range(n):
            cv, hw = self._layer(self.aw, self.aw)
            self.wins.append({'cv': cv, 'hw': hw, 'poly': cv.create_polygon(0, 0, 0, 0, 0, 0, fill='', outline='black', width=2),
                              'shape': None, 'pos': None, 'on': False})
        self.mw, self.mh = int(600 * self.scale), int(60 * self.scale)
        self.msg_cv, self.msg_hw = self._layer(self.mw, self.mh)
        self.msg_item = self.msg_cv.create_text(self.mw // 2, self.mh // 2, text='', fill=ACCENT, font=self.font)
        self.rsize = int(440 * self.scale)
        self.radar_cv, self.radar_hw = self._layer(self.rsize, self.rsize + int(260 * self.scale))
        self.used = {'n': 0, 'shown': 0, 'msg': None}
        if game_window():
            user32.SetForegroundWindow(game_window())        # the game pauses when it loses focus

    # --- helpers ----------------------------------------------------------------------------------------------------
    def key_pressed(self, vk):
        down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
        was = self.state['keys'].get(vk, False); self.state['keys'][vk] = down
        return down and not was

    def near(self, x, z, r):
        cx, cz, n = int(x // 500), int(z // 500), int(r // 500) + 1
        for i in range(cx - n, cx + n + 1):
            for j in range(cz - n, cz + n + 1):
                yield from self.grid.get((i, j), ())

    def arrow(self, cx, cy, ang, s, col):
        i = self.used['n']
        if i >= len(self.wins):
            return
        self.used['n'] = i + 1
        w, h = self.wins[i], self.aw / 2
        s = round(s / 2) * 2                                # 2 px size steps: fewer repaints
        shape = (s, round(math.degrees(ang)), col)
        if shape != w['shape']:
            ca, sa = math.cos(ang), math.sin(ang)
            pts = [(s, 0), (-s * .6, s * .6), (-s * .25, 0), (-s * .6, -s * .6)]
            w['cv'].coords(w['poly'], *[v for px, py in pts for v in (h + px * ca - py * sa, h + px * sa + py * ca)])
            w['cv'].itemconfigure(w['poly'], fill=col); w['shape'] = shape
        pos = (round(cx - h), round(cy - h))
        if pos != w['pos'] or not w['on']:
            user32.SetWindowPos(w['hw'], 0, pos[0], pos[1], 0, 0, SWP_MOVE_SHOW)
            w['pos'] = pos; w['on'] = True

    # --- the target list (10x a second) -----------------------------------------------------------------------------
    def tick(self):
        st = self.state
        st['n'] += 1
        if self.key_pressed(0x76): st['radar'] = not st['radar']                                          # F7
        if self.key_pressed(0x77): st['radar_range'] = (st['radar_range'] + 1) % len(RADAR_RANGES)        # F8
        if self.key_pressed(0x78): st['filter'] = (st['filter'] + 1) % len(FILTERS)                       # F9
        if st['n'] % 20 == 0:                                                                            # every 2 s
            if self.game.attach():
                st['seen'] = True
            elif st.get('seen'):
                self.root.destroy(); return                 # the game has closed
        self.progress.refresh()
        if st['n'] % 2 == 0:
            self.progress.pickups()
        cam = camera(self.game)
        rng = self.ranges[st['range']]
        allowed = FILTERS[st['filter']][1]
        if cam and rng:
            x, z = cam[3][0], cam[3][2]
            if st['n'] % 5 == 1:                            # placement data, every 0.5 s
                st['poi_targets'] = [(d, t) for t in self.near(x, z, rng)
                                     if not (allowed and t[0] not in allowed)
                                     and (d := math.hypot(t[3][0] - x, t[3][2] - z)) <= rng and self.progress.remaining(t)]
            if st['n'] % 2 == 0:                            # live markers, every 0.2 s
                self.merge_markers(cam, rng, allowed)
        elif st['targets']:
            st['targets'] = []; st['tver'] += 1
        if st['radar'] or st.get('radar_was'):
            self.draw_radar(cam)
        st['radar_was'] = st['radar']
        self.root.after(100, self.tick)

    def merge_markers(self, cam, rng, allowed):
        st, pr = self.state, self.progress
        x, z = cam[3][0], cam[3][2]
        raw = pr.markers()
        before = set(pr.live_destroyed)
        pr.vanished(raw, cam[3])
        # a destroyed marker that is not in the data (the truck a propaganda spawn point puts out) takes the
        # sabotage target within 30 m with it
        for g, typ, standing, q in raw:
            if typ == A.MARKER_SABOTAGE and g in pr.live_destroyed and g not in before and g not in self.target_groups:
                for t in self.near(q[0], q[2], 30):
                    if t[0] == 'sabotage' and math.hypot(t[3][0] - q[0], t[3][2] - q[2]) < 30:
                        pr.live_destroyed.add(t[2])
        targets = [(d, t) for d, t in st['poi_targets'] if t[2] not in pr.live_destroyed]
        shown = [t[3] for _, t in targets]
        for g, typ, standing, q in raw:                     # pickups the data doesn't know (never sabotage: props)
            old = st['last_pos'].get(g); st['last_pos'][g] = q
            if old and abs(old[0] - q[0]) + abs(old[2] - q[2]) > 2:
                st['moving'].add(g)                         # vehicles, helicopters
            if typ == A.MARKER_SABOTAGE or g in self.target_groups or g in st['moving'] or not g:
                continue
            if allowed and 'item' not in allowed or g in pr.live_collected or g in pr.collected or g in pr.done_groups:
                continue
            if any(abs(q[0] - r[0]) < 15 and abs(q[2] - r[2]) < 15 for r in shown):
                continue
            d = math.hypot(q[0] - x, q[2] - z)
            if d <= rng:
                targets.append((d, ('item', A.MARKER_ITEMS.get(typ, 'item'), g, q)))
        if len(st['last_pos']) > 5000:
            st['last_pos'].clear()
        self.audit(raw)
        targets.sort(key=lambda t: t[0])
        key = tuple(t[1][2] for t in targets)
        if key != st.get('tkey'):                           # contents changed: redraw even if the camera didn't move
            st['tkey'] = key; st['tver'] += 1
        st['targets'] = targets

    def audit(self, raw):
        """Self-check, logged to %APPDATA%\\panau-completionist\\audit.log: a target the game's marker says is
        destroyed while the progress table still says standing. Right after destruction that is normal (the table
        catches up within ~2 minutes), so only disagreements lasting over 3 minutes are logged, once per object.
        One that stays points at a wrong per-type flag in done_flags.json."""
        pr, now = self.progress, time.time()
        first = self.state.setdefault('disagree', {})
        logged = self.state.setdefault('logged', set())
        labels = self.state.setdefault('labels', {t[2]: t[1] for t in self.targets})
        for g, typ, standing, _ in raw:
            if typ != A.MARKER_SABOTAGE or standing or g not in labels or labels[g] == 'SAM site':
                continue
            if g in pr.done_groups:
                first.pop(g, None)
            elif now - first.setdefault(g, now) > 180 and g not in logged:
                logged.add(g)
                keys = {pr.last_t[i * 8:i * 8 + 4].hex(): (pr.last_bits[i >> 3] >> (i & 7)) & 1
                        for i in pr.g_slots.get(g, ())} if pr.last_t else {}
                try:
                    os.makedirs(config.DIR, exist_ok=True)
                    with open(os.path.join(config.DIR, 'audit.log'), 'a', encoding='utf-8') as f:
                        f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {labels[g]} {g:08x}: marker destroyed, progress '
                                f'table still standing after 3 min; its entries {keys}\n')
                except OSError:
                    pass

    # --- arrows (15x a second, only when something changed) ---------------------------------------------------------
    def frame(self):
        try:
            self.draw_arrows()
        finally:
            self.root.after(66, self.frame)

    def draw_arrows(self):
        st, used = self.state, self.used
        if self.key_pressed(0x75):                          # F6
            st['range'] = (st['range'] + 1) % len(self.ranges); st['range_msg'] = time.time()
        rng = self.ranges[st['range']]
        gr = game_rect()
        if gr and menu_open(self.game):                     # nothing on top of the game's menus
            gr = None
        cam = camera(self.game) if rng and gr else None
        msg = bool(gr) and time.time() - st.get('range_msg', 0) < 2
        sig = (rng, bool(gr), msg, st['tver'], len(self.progress.live_collected),
               cam and tuple(round(v, 3) for v in cam[0] + cam[1] + cam[2]) + tuple(round(v, 1) for v in cam[3]))
        if sig == st.get('sig'):
            return
        st['sig'] = sig
        used['n'] = 0
        text = (f'arrows: {rng} m' if rng else 'arrows off') if msg else None
        if text != used['msg']:
            if text:
                self.msg_cv.itemconfigure(self.msg_item, text=text)
                user32.SetWindowPos(self.msg_hw, 0, int(gr[0] + gr[2] / 2 - self.mw / 2), int(gr[1] + gr[3] * .12 - self.mh / 2), 0, 0, SWP_MOVE_SHOW)
            else:
                user32.ShowWindow(self.msg_hw, 0)
            used['msg'] = text
        if cam:
            R, U, B, T, sx, sy = cam
            gx, gy, gw, gh = gr
            ccx, ccy = gx + gw / 2, gy + gh / 2
            off, shown = [], 0
            for dist, t in st['targets']:
                if dist > rng or t[2] in self.progress.live_collected:
                    continue
                d = (t[3][0] - T[0], t[3][1] + 2 - T[1], t[3][2] - T[2])
                x = d[0] * R[0] + d[1] * R[1] + d[2] * R[2]
                y = d[0] * U[0] + d[1] * U[1] + d[2] * U[2]
                z = d[0] * B[0] + d[1] * B[1] + d[2] * B[2]
                col = SAB_COLOR if t[0] == 'sabotage' else ITEM_COLOR
                if z < -1:                                  # in front of the camera
                    nx, ny = sx * x / -z, sy * y / -z
                    if abs(nx) < 0.97 and abs(ny) < 0.95:
                        if shown < self.cfg['max_arrows']:
                            shown += 1
                            s = max(16, min(40, 40 * (150 / max(dist, 1)) ** .5)) * self.scale
                            self.arrow(ccx + nx * gw / 2, ccy - ny * gh / 2 - s * .9, math.pi / 2, s, col)
                        continue
                off.append((dist, x, y, col))
            for dist, x, y, col in sorted(off)[:self.cfg['edge_arrows']]:
                ang = math.atan2(-y, x) if abs(x) + abs(y) > 1e-3 else math.pi / 2
                self.arrow(ccx + math.cos(ang) * gw * .44, ccy + math.sin(ang) * gh * .40, ang, 26 * self.scale, col)
        for i in range(used['n'], used['shown']):
            user32.ShowWindow(self.wins[i]['hw'], 0); self.wins[i]['on'] = False
        used['shown'] = used['n']

    # --- the optional radar (top right, north up) --------------------------------------------------------------------
    def draw_radar(self, cam):
        c, st, sc = self.radar_cv, self.state, self.scale
        c.delete('all')
        if not st['radar'] or not cam or not game_rect() or menu_open(self.game):
            user32.ShowWindow(self.radar_hw, 0); return
        sw = user32.GetSystemMetrics(0)
        user32.SetWindowPos(self.radar_hw, 0, sw - self.rsize - int(60 * sc), int(60 * sc), 0, 0, SWP_MOVE_SHOW)
        x, z = cam[3][0], cam[3][2]
        look = math.atan2(-cam[2][0], -cam[2][2])
        R = RADAR_RANGES[st['radar_range']]; half = self.rsize / 2; pr = half - 6
        allowed = FILTERS[st['filter']][1]
        c.create_oval(6, 6, self.rsize - 6, self.rsize - 6, fill='#0d0d0d', outline=ACCENT, width=2)
        c.create_text(half, 14, text=f'{R} m · {FILTERS[st["filter"]][0]}', fill='#dddddd', font=self.font)
        c.create_text(half, 34 * sc, text='N', fill=ACCENT, font=self.font)
        for t in self.near(x, z, R):
            dx, dz = t[3][0] - x, t[3][2] - z
            if math.hypot(dx, dz) > R or (allowed and t[0] not in allowed) or not self.progress.remaining(t):
                continue
            px, py, r = half + dx / R * pr, half - dz / R * pr, 5 * sc
            if t[0] == 'sabotage':
                c.create_rectangle(px - r, py - r, px + r, py + r, fill=SAB_COLOR, outline='black')
            else:
                c.create_oval(px - r, py - r, px + r, py + r, fill=ITEM_COLOR, outline='black')
        vx, vy = math.sin(look), -math.cos(look)
        for spread in (-0.35, 0.35):
            ex = vx * math.cos(spread) - vy * math.sin(spread); ey = vx * math.sin(spread) + vy * math.cos(spread)
            c.create_line(half, half, half + ex * pr, half + ey * pr, fill='#6b3fa0', width=2)
        c.create_oval(half - 6 * sc, half - 6 * sc, half + 6 * sc, half + 6 * sc, fill=ACCENT, outline='white')

    def run(self):
        self.tick()
        self.frame()
        self.root.mainloop()


def main(wait=False):
    lower_own_priority()
    if not single_instance('overlay'):
        return 0
    cfg = config.load()
    if wait:                                                # started with the game: wait for its window to settle
        for _ in range(600):
            if game_window() and find_pid():
                break
            time.sleep(1)
        else:
            return 1
        time.sleep(8)
    g = Game()
    if not g.attach():
        print('Just Cause 2 is not running')
        return 1
    if not A.build_ok(g):
        print('this JustCause2.exe is not the build these addresses were found in; refusing to run')
        return 1
    if cfg['overlay']['borderless']:
        make_borderless()
    Overlay(cfg).run()
    return 0
