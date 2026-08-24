"""ZEUS process layer - stdlib-only Windows introspection.

Everything the sentinel and bolt need to know about live processes is
gathered here with ctypes against Psapi/Kernel32: pid table, image
paths, working sets, CPU time deltas and TCP listeners. No third-party
packages; on non-Windows hosts the layer degrades to an empty table
instead of crashing the kernel.
"""

import ctypes
import os
import socket
import struct
import sys
import time

IS_WINDOWS = sys.platform == "win32"

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87

if IS_WINDOWS:
    _psapi = ctypes.WinDLL("Psapi.dll", use_last_error=True)
    _k32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)

    _LPDWORD = ctypes.POINTER(ctypes.c_uint32)

    _psapi.EnumProcesses.argtypes = (_LPDWORD, ctypes.c_uint32, _LPDWORD)
    _psapi.EnumProcesses.restype = ctypes.c_int

    _k32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    _k32.TerminateProcess.restype = ctypes.c_int

    _k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int,
                                 ctypes.c_uint32)
    _k32.OpenProcess.restype = ctypes.c_void_p

    _k32.CloseHandle.argtypes = (ctypes.c_void_p,)
    _k32.CloseHandle.restype = ctypes.c_int

    _k32.QueryFullProcessImageNameW.argtypes = (
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
        _LPDWORD)
    _k32.QueryFullProcessImageNameW.restype = ctypes.c_int

    _k32.GetProcessTimes.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64))
    _k32.GetProcessTimes.restype = ctypes.c_int

    class _PMC(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_uint32),
            ("PageFaultCount", ctypes.c_uint32),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    _psapi.GetProcessMemoryInfo.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(_PMC), ctypes.c_uint32)
    _psapi.GetProcessMemoryInfo.restype = ctypes.c_int

    # dwState, localAddr, localPort, remoteAddr, remotePort, dwOwningPid
    class _TCPROW(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint32) for n in
                    ("state", "laddr", "lport", "raddr", "rport", "pid")]

    class _TCPTABLE(ctypes.Structure):
        _fields_ = [("num", ctypes.c_uint32),
                    ("rows", _TCPROW * 0)]  # flexible array via cast

    _TCP_TABLE_OWNER_PID_LISTENER = 3
    _AF_INET = 2

    _psapi.GetExtendedTcpTable.argtypes = (
        ctypes.c_void_p, _LPDWORD, ctypes.c_int, ctypes.c_uint32,
        ctypes.c_uint32, ctypes.c_uint32)
    _psapi.GetExtendedTcpTable.restype = ctypes.c_uint32


def _ntohs(port_be):
    return ((port_be & 0xFF) << 8) | ((port_be >> 8) & 0xFF)


class ProcInfo:
    """One row of the process table."""

    __slots__ = ("pid", "ppid", "name", "exe", "mem_mb",
                 "cpu_pct", "accessible")

    def __init__(self, pid, name="", exe="", mem_mb=0.0,
                 cpu_pct=None, accessible=True):
        self.pid = pid
        self.ppid = 0
        self.name = name
        self.exe = exe
        self.mem_mb = mem_mb
        self.cpu_pct = cpu_pct
        self.accessible = accessible

    def as_dict(self):
        return {"pid": self.pid, "name": self.name, "exe": self.exe,
                "mem_mb": round(self.mem_mb, 1),
                "cpu_pct": None if self.cpu_pct is None
                else round(self.cpu_pct, 1),
                "accessible": self.accessible}


class ProcTable:
    """Live snapshotter with CPU deltas between consecutive samples.

    The first sample of any new pid carries cpu_pct=None; from the
    second sample onward ZEUS can see real per-process load.
    """

    def __init__(self):
        self._last_cpu = {}      # pid -> (wall_s, cpu_time_s)
        self._ncpu = os.cpu_count() or 1

    def sample(self):
        if not IS_WINDOWS:
            return {}
        pids = self._enum_pids()
        now = time.monotonic()
        out = {}
        seen = set()
        for pid in pids:
            info = self._probe(pid, now)
            if info is not None:
                out[pid] = info
            seen.add(pid)
        for dead in list(self._last_cpu):
            if dead not in seen:
                del self._last_cpu[dead]
        return out

    def _enum_pids(self):
        size = 4096
        while True:
            buf = (ctypes.c_uint32 * size)()
            ret = ctypes.c_uint32(0)
            if not _psapi.EnumProcesses(buf, ctypes.sizeof(buf),
                                        ctypes.byref(ret)):
                raise OSError("EnumProcesses failed")
            n = ret.value // ctypes.sizeof(ctypes.c_uint32)
            if n < size:
                return [buf[i] for i in range(n) if buf[i]]
            size *= 2

    def _probe(self, pid, now):
        h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            err = ctypes.get_last_error()
            if err == ERROR_ACCESS_DENIED:
                # Alive but dark: system-protected process.
                return ProcInfo(pid, accessible=False)
            return None
        try:
            exe = self._exe_path(h)
            mem_mb = self._working_set_mb(h)
            cpu_pct = self._cpu_delta(pid, h, now)
            name = os.path.basename(exe) if exe else ""
            return ProcInfo(pid, name=name, exe=exe,
                            mem_mb=mem_mb, cpu_pct=cpu_pct)
        finally:
            _k32.CloseHandle(h)

    @staticmethod
    def _exe_path(h):
        n = ctypes.c_uint32(1024)
        buf = ctypes.create_unicode_buffer(n.value)
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""

    @staticmethod
    def _working_set_mb(h):
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if _psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / (1024.0 * 1024.0)
        return 0.0

    def _cpu_delta(self, pid, h, now):
        created = ctypes.c_uint64(0)
        exited = ctypes.c_uint64(0)
        kern = ctypes.c_uint64(0)
        user = ctypes.c_uint64(0)
        if not _k32.GetProcessTimes(h, ctypes.byref(created),
                                    ctypes.byref(exited),
                                    ctypes.byref(kern), ctypes.byref(user)):
            return None
        cpu_s = (kern.value + user.value) / 10_000_000.0
        prev = self._last_cpu.get(pid)
        self._last_cpu[pid] = (now, cpu_s)
        if prev is None:
            return None
        wall = max(now - prev[0], 1e-6)
        pct = (cpu_s - prev[1]) / wall / self._ncpu * 100.0
        return max(0.0, min(pct, 100.0 * self._ncpu))


def tcp_listeners():
    """Listening TCP endpoints owned by pid: [(pid, port, addr)]."""
    if not IS_WINDOWS:
        return []
    size = ctypes.c_uint32(16 * 1024)
    for _ in range(4):
        buf = ctypes.create_string_buffer(size.value)
        rc = _psapi.GetExtendedTcpTable(
            buf, ctypes.byref(size), False, _AF_INET,
            _TCP_TABLE_OWNER_PID_LISTENER, 0)
        if rc == 0:
            break
        if rc == 122:  # ERROR_INSUFFICIENT_BUFFER - size updated
            continue
        raise OSError(f"GetExtendedTcpTable failed rc={rc}")
    else:
        raise OSError("GetExtendedTcpTable would not fit")
    num = struct.unpack_from("<I", buf, 0)[0]
    rows = []
    off = 4
    row_fmt = "<6I"
    for i in range(min(num, 4096)):
        state, laddr, lport, _raddr, _rport, pid = \
            struct.unpack_from(row_fmt, buf, off + i * 24)
        ip = socket.inet_ntoa(struct.pack("<I", laddr))
        rows.append((pid, _ntohs(lport), ip))
    return rows


def kill_pid(pid):
    """Terminate a pid. Returns (ok, detail)."""
    if not IS_WINDOWS:
        return False, "kill unsupported on this platform"
    h = _k32.OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION,
                         False, pid)
    if not h:
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            return False, "access denied"
        return False, f"open failed (err={err})"
    try:
        if _k32.TerminateProcess(h, 137):
            return True, "terminated"
        return False, f"terminate failed (err={ctypes.get_last_error()})"
    finally:
        _k32.CloseHandle(h)
