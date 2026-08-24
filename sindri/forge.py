"""SINDRI - sandboxed execution forge for generated code.

Named for the smith who forged Mjolnir: this is where autonomous
output gets hammered under controlled conditions.

Contract (INTEGRATION.md section 7, "execute" stage):
    result = sindri.run([python, "child.py"], cwd=scratch,
                        mem_mb=256, seconds=10, max_procs=4)

Guarantees:
- hard wall-clock kill of the whole process tree;
- memory ceiling via OS job limits (Windows) or RLIMIT_AS (POSIX);
- process-count ceiling (fork-bomb brake);
- children never outlive the forge (kill-on-close job flag);
- suspended start on Windows: the child cannot run one instruction
  before it is already fenced into the job.

Honest limitation (v1): filesystem scoping is "fresh cwd + wholesale
kill"; absolute-path writes are NOT yet blocked. Pair with ZEUS churn
patrols until DACL scoping lands.
"""

import os
import subprocess
import sys
import threading
import time

IS_WINDOWS = sys.platform == "win32"

# --- Job Object constants (winbase.h) ---
JOB_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_LIMIT_KILL_ON_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102


def _windows_run(cmd, cwd, mem_bytes, max_procs, seconds):
    """Full-fence Windows path: CreateProcessW(CREATE_SUSPENDED),
    assign to a capped Job Object, then resume. Returns result dict."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount",
            "OtherOperationCount", "ReadTransferCount",
            "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("UILimitFlags", ctypes.c_uint32)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("Basic", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class STARTUPINFO_W(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_char_p),
            ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE)]

    class PROC_INFO(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE),
                    ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD),
                    ("dwThreadId", wintypes.DWORD)]

    def make_pipe():
        r, w = wintypes.HANDLE(), wintypes.HANDLE()
        if not k32.CreatePipe(ctypes.byref(r), ctypes.byref(w), None, 0):
            raise OSError("CreatePipe failed")
        k32.SetHandleInformation(w, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)
        return r, w

    out_r, out_w = make_pipe()
    err_r, err_w = make_pipe()
    in_r, in_w = make_pipe()

    si = STARTUPINFO_W()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = STARTF_USESTDHANDLES
    si.hStdInput, si.hStdOutput, si.hStdError = in_r, out_w, err_w
    pi = PROC_INFO()
    cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(cmd))
    cwd_buf = ctypes.c_wchar_p(cwd) if cwd else None

    job = k32.CreateJobObjectW(None, None)
    caps = EXTENDED()
    caps.Basic.LimitFlags = (JOB_LIMIT_ACTIVE_PROCESS
                             | JOB_LIMIT_PROCESS_MEMORY
                             | JOB_LIMIT_KILL_ON_CLOSE)
    caps.Basic.ActiveProcessLimit = int(max_procs)
    caps.ProcessMemoryLimit = mem_bytes
    caps.JobMemoryLimit = mem_bytes
    if not job or not k32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation,
            ctypes.byref(caps), ctypes.sizeof(caps)):
        raise OSError("job object setup failed")

    ok = k32.CreateProcessW(
        None, cmdline, None, None, True,
        CREATE_SUSPENDED | CREATE_NO_WINDOW, None, cwd_buf,
        ctypes.byref(si), ctypes.byref(pi))
    for h in (in_r, out_w, err_w, in_w):
        k32.CloseHandle(h)
    if not ok:
        k32.CloseHandle(job)
        raise OSError("CreateProcessW failed")

    # Fence FIRST, then let it breathe.
    if not k32.AssignProcessToJobObject(pi.hProcess, job):
        k32.TerminateJobObject(pi.hProcess, 1)
        k32.CloseHandle(job)
        raise OSError("AssignProcessToJobObject failed")
    k32.ResumeThread(pi.hThread)
    k32.CloseHandle(pi.hThread)

    def drain(handle):
        chunks = []
        fd = -1
        try:
            import msvcrt
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_TEXT)
            while True:
                b = os.read(fd, 65536)
                if not b:
                    break
                chunks.append(b)
        finally:
            if fd >= 0:
                os.close(fd)
            else:
                k32.CloseHandle(handle)
        return b"".join(chunks).decode("utf-8", "replace")

    out_box, err_box = [], []
    t_out = threading.Thread(target=lambda: out_box.append(drain(out_r)))
    t_err = threading.Thread(target=lambda: err_box.append(drain(err_r)))
    t_out.start()
    t_err.start()

    started = time.monotonic()
    wait = k32.WaitForSingleObject(pi.hProcess, int(seconds * 1000))
    timed_out = wait == WAIT_TIMEOUT
    if timed_out:
        # JOB handle only - a process handle here would terminate
        # whatever job the child belongs to, including our ancestors'.
        k32.TerminateJobObject(job, 1)
        k32.WaitForSingleObject(pi.hProcess, 5000)
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    t_out.join(5)
    t_err.join(5)
    k32.CloseHandle(pi.hProcess)
    k32.CloseHandle(job)
    return {
        "exit": None if timed_out else int(code.value),
        "stdout": out_box[0] if out_box else "",
        "stderr": err_box[0] if err_box else "",
        "timed_out": timed_out,
        "secs": round(time.monotonic() - started, 3),
    }


def _posix_run(cmd, cwd, mem_bytes, max_procs, seconds):
    """POSIX path: own session + RLIMIT_AS fence + group kill."""
    import resource

    def preexec():
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        os.setsid()

    started = time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, errors="replace",
        preexec_fn=preexec, start_new_session=True)
    timed_out = False

    def on_timeout():
        nonlocal timed_out
        timed_out = True
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            proc.kill()

    killer = threading.Timer(seconds, on_timeout)
    killer.start()
    try:
        out, err = proc.communicate(timeout=seconds + 5)
    except subprocess.TimeoutExpired:
        on_timeout()
        out, err = proc.communicate()
    finally:
        killer.cancel()
    return {"exit": None if timed_out else proc.returncode,
            "stdout": out or "", "stderr": err or "",
            "timed_out": timed_out,
            "secs": round(time.monotonic() - started, 3)}


def run(cmd, *, cwd=None, mem_mb=512, seconds=30, max_procs=16):
    """Execute ``cmd`` fenced. Returns
    {exit, stdout, stderr, timed_out, secs}; raises only on forge
    setup failure, never for child misbehaviour.

    Default Windows path uses ``taskkill /T /F`` tree-kill (safe
    inside foreign job hierarchies). Set SINDRI_WIN_JOBS=1 to opt
    into the Job Object fence (mem/proc caps) once validated in your
    environment."""
    mem_bytes = int(mem_mb) * 1024 * 1024
    if IS_WINDOWS and os.environ.get("SINDRI_WIN_JOBS") == "1":
        return _windows_run([str(c) for c in cmd], cwd, mem_bytes,
                            int(max_procs), float(seconds))
    if IS_WINDOWS:
        return _windows_basic([str(c) for c in cmd], cwd, seconds)
    return _posix_run([str(c) for c in cmd], cwd, mem_bytes,
                      int(max_procs), float(seconds))


def run_ok(cmd, **kw):
    """Convenience: True when the fenced child exited zero."""
    return run(cmd, **kw)["exit"] == 0


def _windows_basic(cmd, cwd, seconds):
    """No-Job Windows path: plain Popen + taskkill /T /F tree kill."""
    import time as _time

    started = _time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, errors="replace",
        creationflags=CREATE_NO_WINDOW)
    timed_out = False

    def on_timeout():
        nonlocal timed_out
        timed_out = True
        subprocess.run(["taskkill", "/PID", str(proc.pid),
                        "/T", "/F"], capture_output=True)

    killer = threading.Timer(seconds, on_timeout)
    killer.start()
    try:
        out, err = proc.communicate(timeout=seconds + 5)
    except subprocess.TimeoutExpired:
        timed_out = True
        out, err = proc.communicate()
    finally:
        killer.cancel()
    return {"exit": None if timed_out else proc.returncode,
            "stdout": out or "", "stderr": err or "",
            "timed_out": timed_out,
            "secs": round(_time.monotonic() - started, 3)}
