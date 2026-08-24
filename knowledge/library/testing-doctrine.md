# Testing & Verify-Gate Doctrine

## Every realm ships a gate

A realm without `verify_<realm>.py` is a realm without proof. The gate
is scenario-driven: build throwaway fixtures in temp dirs, drive the
REAL public surface (no white-box pokes), assert observable outcomes,
print `[ok]`/`[FAIL]` per check, end with `N/N checks passed`, exit
non-zero on any failure. Gates run standalone, in CI, in doctor sweeps,
and inside watchdog loops.

## Determinism is non-negotiable

Network-dependent tests use scripted brains or stub HTTP servers on
ephemeral ports. Time-based logic injects clocks. Randomness seeds
itself. A test that fails once a week teaches the team to ignore red.

## The remediated retry convention

Back-to-back batteries on a busy box trip timing-sensitive checks:
socket accepts race, SLO pulses land late, backoff timers stretch.
Convention: when a suite fails inside a battery, settle briefly and
re-run once before declaring red. Persistent failures still fail with
full tails. Instrument failures with the actual error text — a bare
"1 error" teaches nothing.

## Unit tests complement gates

Gates prove scenarios; unit suites pin contracts at function grain.
Keep both green: the gate runs the unit suite as one of its checks so
drift between them surfaces immediately.

## Assertions that survive concurrency

Polling loops need deadlines AND tolerance for dropped frames: retry
malformed or partial responses until the deadline, then assert.
Delta-based assertions beat absolute ones under async systems — assert
that patrol advanced by exactly 2, not that a counter equals 0 at an
arbitrary instant.

## Fixtures over mocks where possible

Real subprocesses speaking real protocols (a fixture MCP server, a stub
HTTP endpoint) catch integration bugs that mocks encode away. Keep
fixtures tiny, deterministic, and local — spawnable from any checkout
without network.

## Gates are documentation

Each check name is a sentence describing a guaranteed behavior.
Reading the list of check names should teach a newcomer what the realm
promises; reading a failure should teach them what broke.
