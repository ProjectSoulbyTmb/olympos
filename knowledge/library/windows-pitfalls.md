# Windows Pitfalls — field notes from a Windows-first fleet

## subprocess on Windows

`shell=True` with a STRING is the reliable way to honor shell semantics;
cmd.exe parses it verbatim. The list form `[comspec, "/d","/s","/c", cmd]`
mangles embedded quotes via list2cmdline — avoid it.

Timeouts kill only the direct child. A shell wrapping a grandchild
orphans it: `subprocess.run(..., timeout=)` returns while ping keeps
running. Use Popen + communicate(timeout), and on expiry kill the whole
tree: `taskkill /PID <pid> /T /F`; on POSIX use start_new_session=True
at spawn plus `os.killpg`.

## Ports, TIME_WAIT, and ephemeral ranges

Bind port 0 for tests and resolve the real port from getsockname().
SO_REUSEADDR does not mean two live listeners can share; check netstat
before blaming code when connect_ex hits a stranger. Live scheduled-task
daemons own ports across test runs — self-hosted fixtures must not
target production ports.

## Paths, ownership, OneDrive

Repos under OneDrive or similar trip git's `safe.directory` ownership
check for worktrees; add explicit
`git config --global --add safe.directory <path>` per checkout. MAX_PATH
still bites with deep node_modules; prefer shallow trees. Text mode
opens translate CRLF silently — pass `newline=""` when bytes matter and
hash with newline normalization decided deliberately (seal anchors
broke on this exact trap).

## PowerShell 5.1 quirks

`>` redirection writes UTF-16 — corrupts files meant to be text; use
cmdlets or git-native plumbing instead of shell redirection for bytes.
Native stderr output becomes error records under `$ErrorActionPreference="Stop"`
even when the command succeeds; drive git/gh by `$LASTEXITCODE`, keep
stderr visible, and filter profile noise rather than silencing streams.
Backtick-n inside double-quoted here-strings leaks literally into files.

## Git on Windows

Hooks run under sh — keep them POSIX. `git config core.hooksPath` can
redirect all hooks to a tracked directory for portable contracts.
Line-ending warnings on every touch are cosmetic; decide policy once
(`core.autocrlf`) and stop fighting it per-file.

## Scheduled tasks

Register kernels with `-AllowStartIfOnBatteries -StartWhenAvailable
-MultipleInstances IgnoreNew` and an ExecutionTimeLimit slightly above
the task's worst case. Resolve python explicitly (LOCALAPPDATA first,
PATH fallback). WorkingDirectory matters more than arguments — many
tools assume CWD-relative state.
