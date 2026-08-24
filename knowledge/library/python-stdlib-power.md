# Python Stdlib Power — building platforms without dependencies

A standard-library-only rule is a feature: instant checkout, zero
supply-chain, immortal code. These are the load-bearing idioms.

## HTTP clients & servers

urllib.request for calls (Request with data/headers/method; urlopen
with timeout; HTTPError carries status + body — read it). Retry loops
belong in YOUR code: catch URLError/TimeoutError and 5xx-class
HTTPErrors, sleep exponential, honor Retry-After.

http.server.ThreadingHTTPServer serves local APIs. Wrap route handlers
in a guard that converts every exception into a JSON error response —
default HTML error pages corrupt JSON clients. Bind 127.0.0.1 by
default. Daemon threads plus allow_reuse_address make tests painless.
For worktrees/clones sharing hooks, remember handlers run per-connection
threads: keep shared state behind locks.

## subprocess discipline

Capture with PIPEs and communicate(timeout=). Kill trees, not just
children (taskkill /T /F on Windows, killpg on POSIX with
start_new_session). Decode with errors="replace". Cap captured output
before embedding into logs or prompts.

## Data plumbing

json with ensure_ascii=False for human-visible files; explicit
encoding="utf-8" everywhere; newline="" when writing text that must not
shift endings. dataclasses over dicts for internal shapes; keep
to_dict/from_dict pairs so events serialize cleanly without pydantic.
itertools + collections.Counter solve most analysis one-liners.

## CLI craft

argparse subparsers per command; every command returns an exit code;
--json variants for machine callers. Print progress to stdout sparingly,
diagnostics to stderr, machine payloads only when asked.

## Persistence patterns

JSONL append-only logs with flush-per-line are the crash-safe backbone:
events, incidents, audits. Replay = read lines, deserialize, done.
Atomic writes need temp-file-plus-replace under an exclusive lock
(O_CREAT|O_EXCL spinlocks with stale-takeover timestamps).

## Indexing & search

An inverted index is ~80 lines: tokenize (lowercase, split non-word),
count term frequencies per doc, store postings term→doc→tf plus doc
lengths; score queries with TF-IDF and return best sentences as
snippets. This handles tens of thousands of documents without a search
service — and stays grep-able.

## Testing stdlib services

Spawn servers on port 0, poll health endpoints with deadlines, use
TextTestRunner with buffered streams inside gates. unittest discovery
from the repo root keeps import paths stable across checkouts.
