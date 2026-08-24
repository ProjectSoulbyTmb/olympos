# Engine Principles — learned from RuneSource & Hyperion

Distilled from two of the cleanest, highest-performance 317-era RSPS
codebases, with citations, and mapped onto **our** engine
(`server/rsps_server.py`). Applied changes are marked ✅.

## Sources

- **RuneSource** (blakeman8192, 2010) — single-threaded logic, async IO,
  strict cycles; 2,000 bot clients at ~35 ms/cycle (~6 % load) on a VPS.
  Blake's own follow-up benchmark: parallelizing *only* read-only update
  preparation took 2,000-client updating from 120 ms → 30 ms on four cores.
- **Hyperion** (Graham, 2009; → Apollo 2011) — cached update blocks per
  cycle; pooled read-only player updating with a blocking barrier; main loop
  as a blocking task queue ("when the server is idle, it really is idle");
  disk saves on a separate thread so saves never stall the loop.

## The laws, mapped to our engine

| # | Law (source) | Our engine today |
|---|---|---|
| 1 | **Single writer for mutable state** (RuneSource runs all logic on one thread; Blake: "keeping things simple… guarantees stability") | Each `Session` owns its `World`; no shared world state. Cross-session effects (chat/presence/join-leave notes) now serialize on `GameServer._lock`. ✅ hardened |
| 2 | **Parallelize only read-only work** (Blake's 4× update-prep result) | State snapshots are pure reads of one world. Nothing to parallelize yet at ≤32 sessions; the seam is `_state_bytes` if we ever need it. |
| 3 | **Cache per-cycle update blocks** (Hyperion) | `_state_bytes` caches the serialized state per tick — identical idea, already shipped. |
| 4 | **Strict cycle discipline + watchdog** (both) | We are request-driven rather than fixed-cycle; added a slow-handler watchdog (>0.5 s prints once). ✅ added |
| 5 | **Bounded queues everywhere** (Hyperion ActionQueue) | Chat feed is now `deque(maxlen=CHAT_HISTORY)` instead of unbounded. ✅ fixed |
| 6 | **Simplicity is the performance feature** (RuneSource README: bases failed "due to their complexity") | JSON-lines protocol, stdlib-only server, no ORM/framework layers. Keep it this way; reject abstraction without a measured win. |
| 7 | **Disk I/O off the hot path** (Hyperion separate save thread) | Atomic autosaves every 240 ticks via tmp+`os.replace`; save exceptions never break the loop. Matches doctrine. |
| 8 | **Login throttling / abuse resistance** (RuneSource feature list) | Per-connection rate bucket (`MAX_ACTIONS_PER_SECOND`) + `MAX_SESSIONS` cap. Already present. |

## Deliberate non-adoptions

- **Fixed global tick thread**: our worlds are instanced-per-session with
  `tick_budget`, so there is no global 600 ms beat to police. Adopting one
  would add contention for zero correctness gain at our scale.
- **Plugin system** (Groovy/Apollo-style): Graham's own retrospective — API
  boundary costs usually outweigh benefits for a small team. Content lives in
  `game/world.py` next to the engine.
- **MINA/reactor networking**: 32-session ceiling and JSON-lines framing make
  thread-per-connection + `makefile` the simpler correct choice.

## Regression rule for future engine work

Any PR that (a) adds cross-session mutation outside `self._lock`, (b)
creates an unbounded queue, or (c) blocks the accept loop on disk/network
I/O is rejected by review — cite this file in the rejection.
