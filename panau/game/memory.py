"""Reading (and, for the cheats, writing) Just Cause 2's memory from outside the game. No injection, no code patching.
32-bit game, so every pointer is a u32."""
import ctypes
import ctypes.wintypes as wt
import struct

from panau.steam import EXE_NAME

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
user32 = ctypes.WinDLL('user32', use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.CreateMutexW.restype = wt.HANDLE
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
user32.GetForegroundWindow.restype = wt.HWND

STILL_ACTIVE = 259
READ, READ_WRITE = 0x0410, 0x0438        # VM_READ|QUERY_INFORMATION, + VM_WRITE|VM_OPERATION


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD), ('th32DefaultHeapID', ctypes.c_void_p),
                ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD),
                ('pcPriClassBase', ctypes.c_long), ('dwFlags', wt.DWORD), ('szExeFile', ctypes.c_wchar * 260)]


def find_pid(name=EXE_NAME):
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == wt.HANDLE(-1).value:
        return None
    try:
        e = PROCESSENTRY32W(); e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == name.lower():
                return e.th32ProcessID
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return None


def lower_own_priority():
    """Below-normal priority: whenever Windows has to choose, the game gets the CPU first."""
    k32.SetPriorityClass(wt.HANDLE(-1), 0x4000)


def single_instance(name):
    """False if another copy holding this name is already running."""
    k32.CreateMutexW(None, False, 'Local\\panau-' + name)
    return ctypes.get_last_error() != 183


class Game:
    """The running JustCause2.exe. attach() finds/re-finds it (cheaply rate-limited); reads return None on failure."""

    def __init__(self, write=False):
        self.access = READ_WRITE if write else READ
        self.h, self.pid, self._next_find = None, None, 0.0
        self._got = ctypes.c_size_t()

    def attach(self, now=None):
        import time
        now = now or time.time()
        if self.h:
            code = wt.DWORD()
            if k32.GetExitCodeProcess(self.h, ctypes.byref(code)) and code.value == STILL_ACTIVE:
                return True
            k32.CloseHandle(self.h); self.h = self.pid = None
        if now < self._next_find:
            return False
        self._next_find = now + 2
        pid = find_pid()
        if pid:
            self.h, self.pid = k32.OpenProcess(self.access, False, pid), pid
        return bool(self.h)

    def read(self, addr, n):
        if not self.h or not 0x10000 <= addr < 0x7FFF0000:
            return None
        buf = ctypes.create_string_buffer(n)
        ok = k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, n, ctypes.byref(self._got))
        return buf.raw[:self._got.value] if ok and self._got.value == n else None

    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack('<I', b)[0] if b else None

    def i32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack('<i', b)[0] if b else None

    def f32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack('<f', b)[0] if b else None

    def write(self, addr, data):
        return bool(self.h) and bool(k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(self._got)))

    def is_foreground(self):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(p))
        return bool(self.pid) and p.value == self.pid
