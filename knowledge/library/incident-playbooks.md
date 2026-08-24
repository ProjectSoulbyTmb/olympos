# Incident Playbooks — signatures, diagnosis, remediation

## Signature: suite passes alone, fails in battery

Cause: resource contention — ports in TIME_WAIT/live listeners, CPU
starvation stretching SLO pulses and backoff timers, accept-thread
races on threaded servers.
Diagnosis: run the failing gate standalone; if green, it is contention.
Remediation: settle-and-retry once inside batteries (sentinel/doctor
convention); make assertions delta-based; bind port 0 everywhere;
tolerate dropped frames in polling loops with deadlines.

## Signature: files vanish between commands

Cause: a concurrent writer ran reset/clean on the shared checkout.
Diagnosis: reflog + `git log --all -- <path>`; check worktree list for
strays. Remediation: recover from commits or stash; stop sharing
checkouts — move to per-writer worktrees (FLOW.md). Re-read files
immediately before editing; never trust earlier reads under concurrency.

## Signature: force-push orphaned local lineage

Cause: another writer rewrote main while you built on old tip.
Remediation: your commits are immortal — find them via
`git log --all --oneline -- <path>` or reflog; cherry-pick onto fresh
branch off origin/main; ship through PR. Never fight force-push with
force-push.

## Signature: shell command "works interactively, fails from agent"

Causes: quoting mangling by cmd /s /c list-form; missing CWD; PATH
differences; stdin expectations.
Remediation: string-form shell=True; resolve cwd inside workspace;
absolute tool paths via sys.executable; capture stderr into the error
field so observations teach.

## Signature: JSON API returns HTML/garbage to clients

Cause: an unhandled exception fell through to the server library's
default error page, or a connection dropped mid-body.
Remediation: guard every route with a catch-all that emits clean JSON
with correct status; clients poll tolerantly (retry malformed frames
until deadline) but never silently accept them as data.

## Signature: seal/baseline verification flags everything after an OS quirk

Cause: text-mode writes changed line endings before hashing.
Remediation: normalize deliberately at write time (newline=""), re-seal
after legitimate bulk edits, keep anchor files independent of working
tree state.

## Signature: scheduled kernel missing after reboot

Check: task exists? last result code? python path still valid?
battery flags set? WorkingDirectory valid? Remediate by re-registering
with explicit paths and battery-friendly settings; verify with a manual
run before trusting the schedule.

## Ledger discipline

Every incident: stable id, first-seen timestamp, signature, severity,
status open→resolved, MTTR banked on close. Auto-close only when a full
sweep comes back clean. Resolved history is reliability telemetry —
median MTTR is the metric leadership should ask about.
