import ctypes
import msvcrt
import os
import subprocess

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9
CREATE_NO_WINDOW = 0x08000000
CREATE_SUSPENDED = 0x4
STARTF_USESTDHANDLES = 0x100
HANDLE_FLAG_INHERIT = 0x1
WAIT_TIMEOUT = 0x102
STILL_ACTIVE = 0x103
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (n, ctypes.c_ulonglong)
        for n in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint32),
        ("dwY", ctypes.c_uint32),
        ("dwXSize", ctypes.c_uint32),
        ("dwYSize", ctypes.c_uint32),
        ("dwXCountChars", ctypes.c_uint32),
        ("dwYCountChars", ctypes.c_uint32),
        ("dwFillAttribute", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("wShowWindow", ctypes.c_uint16),
        ("cbReserved2", ctypes.c_uint16),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint32),
        ("dwThreadId", ctypes.c_uint32),
    ]


def new_job():
    h = _k32.CreateJobObjectW(None, None)
    if not h:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _k32.SetInformationJobObject(
        h, JobObjectExtendedLimitInformation,
        ctypes.byref(info), ctypes.sizeof(info),
    ):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    return h


def close_job(h):
    _k32.CloseHandle(h)


def spawn(job_handle, args, cwd, log_path):
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    fh = msvcrt.get_osfhandle(fd)
    _k32.SetHandleInformation(fh, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = STARTF_USESTDHANDLES
    si.hStdInput = None
    si.hStdOutput = fh
    si.hStdError = fh
    pi = PROCESS_INFORMATION()
    cmdline = subprocess.list2cmdline(args)
    ok = _k32.CreateProcessW(
        None, cmdline, None, None, True,
        CREATE_NO_WINDOW | CREATE_SUSPENDED, None, cwd,
        ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        os.close(fd)
        raise OSError(err, f"CreateProcessW failed: {cmdline}")
    assigned = _k32.AssignProcessToJobObject(job_handle, pi.hProcess)
    _k32.ResumeThread(pi.hThread)
    _k32.CloseHandle(pi.hThread)
    os.close(fd)
    return pi.hProcess, pi.dwProcessId, bool(assigned)


def is_alive(hproc):
    return _k32.WaitForSingleObject(hproc, 0) == WAIT_TIMEOUT


def exit_code(hproc):
    code = ctypes.c_uint32()
    _k32.GetExitCodeProcess(hproc, ctypes.byref(code))
    return code.value


def terminate(hproc, timeout_ms=10000):
    _k32.TerminateProcess(hproc, 1)
    _k32.WaitForSingleObject(hproc, timeout_ms)


def close_handle(hproc):
    _k32.CloseHandle(hproc)


def wait(hproc, timeout_ms):
    return _k32.WaitForSingleObject(hproc, timeout_ms)


def pid_alive(pid):
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    alive = _k32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT
    _k32.CloseHandle(h)
    return alive
