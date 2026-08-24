# Multi-Agent Git Flow

Several autonomous writers share this repository. The rules below make
concurrent work safe: nobody commits to `main` directly, and every
writer owns a private checkout where no one else can clobber it.

## Topology

| Checkout | Path | Writer | Branch |
|---|---|---|---|
| Integration mirror | `D:\THOTH` | humans + release automation only | `main` |
| Hermes worktree | `D:\THOTH\.worktrees\hermes` | Hermes agent sessions | `auto/hermes` |
| Forge worktree | `D:\THOTH\.worktrees\forge` | concurrent builder agent | `auto/forge` |

Each worktree is a full independent checkout with its own index and
HEAD - resets or sweeps in one cannot touch another.

## Protocol

1. **Work only inside your own worktree.** The root checkout is an
   integration mirror: it pulls `main`, it never hosts direct commits.
2. **One branch per writer:** `auto/<name>`. Recreate it freely; never
   share it.
3. **Ship through pull requests:**
   - commit in your worktree,
   - push your branch,
   - open a PR against `main`,
   - merge it (squash keeps `main` linear),
   - pull `main` into the mirror.
4. **Verify before shipping:** run the suites your change touches plus
   `python doctor.py --ci`. Gates are the shared language; if yours are
   green and theirs were green before you started, conflicts surface in
   the PR instead of in someone's working tree.
5. **Sync often:** rebase/merge `main` into your branch at least once
   per session. Small frequent PRs lose races; big rare ones start wars.
6. **Releases:** tag `v*` off `main` only after a green doctor sweep.
7. **Guardrails:** the canonical `pre-push` guard is tracked at
   `hooks/pre-push`; install it into every clone once with
   `powershell -File flow.ps1 install-hooks` - after that any direct
   push to `main` is refused client-side for all worktrees of the
   clone. Server-side branch protection/rulesets need GitHub Pro while
   the repo is private; if the repo goes public or the plan upgrades,
   add a `main-pr-only` ruleset (require pull request, block
   force-pushes and deletions) so the rule holds server-side too.

## Quick reference

```powershell
# one-time setup (already done during bootstrap)
git worktree add .worktrees/hermes -b auto/hermes
git worktree add .worktrees/forge   -b auto/forge

# daily loop - from anywhere in the repo:
powershell -File flow.ps1 sync  -Name hermes          # refresh branch
powershell -File flow.ps1 ship  -Name hermes -Message "fix: thing"  # commit+push+PR+merge
```

`flow.ps1 ship` commits everything in YOUR worktree (you are the only
writer there), pushes `auto/<name>`, opens/merges the PR, prunes the
branch, then fast-forwards the mirror. Add `-NoMerge` to stop after the
PR for human review instead.
