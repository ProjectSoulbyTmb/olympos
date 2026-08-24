# Multi-Writer Git Flow — worktrees, lanes, PRs

When several autonomous agents share one repository, the default
shared-checkout workflow is a lost-update machine: resets sweep staged
files, commits land on moved HEADs, force-pushes orphan lineages
mid-task. The fix is structural, not behavioral.

## Worktree per writer

`git worktree add .worktrees/<name> -b auto/<name>` gives each writer
an independent index and HEAD inside one object store. A `reset --hard`
in checkout A cannot touch checkout B. Untracked scratch stays private.
The integration mirror (root checkout) PULLS; it never hosts commits.

## Branch-per-writer, PR-per-change

Writers push `auto/<name>` branches and open PRs against main. Squash
merges keep main linear and reviewable. Delete merged branches; the
history lives in main. Force-push only your OWN feature branch after an
interactive rewrite — never shared refs, never main.

## Client-side guardrails

A tracked `hooks/pre-push` script that rejects any push updating
`refs/heads/main` turns the policy into physics for every worktree of
the clone (hooks are shared via the common git dir). Provide an
installer command; document it. Server-side rulesets (require PR,
block force-push/deletion) add defense when the hosting plan allows.

## Recovery patterns that saved us

- Lost commits survive in reflog and in pushed branches: find them with
  `git log --all --oneline -- <path>` and cherry-pick onto fresh lanes.
- Stale snapshots masquerading as restores: before trusting a file you
  did not just write, re-read it. Diff against origin, not memory.
- Empty-diff duplicate PRs: check `rev-list --count origin/main..branch`
  before shipping; if zero, the content already landed under another sha.

## Committing under concurrency

Re-read every file immediately before editing. Stage and commit in one
breath when the tree is contested. Prefer many small commits — they
cherry-pick cleanly and conflicts shrink to lines. Never sweep unknown
modified files into your commit with `add -A` in a shared tree.

## Lessons database

Every incident worth an hour earns a lesson entry: monotonic id,
category, source incident, the generalizable rule, tags. Append-only.
The next agent reads lessons before it reads code.
