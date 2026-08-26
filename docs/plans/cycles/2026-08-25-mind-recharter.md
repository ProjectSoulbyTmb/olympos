# Commissioning order: MIND recharter - tech-intel gainer + system teacher

- date: 2026-08-25
- authority: operator order (recorded in DESIGN.md decision log, same date)
- classification: E1 commission (new organ duties on an existing surface-first base)
- delegated to: DAEDALUS muster fleet per AGENTS.md hard rule 5
- target: nested repo `mind/` (v2.0.0, local-only, gate `mind/verify.py`)

## Charter

MIND is the system-wide resource for advanced technology. It:

1. **GAINS** - acquires advanced technical information from curated,
   operator-approved sources and turns it into structured, citable
   knowledge entries.
2. **TEACHES** - serves that knowledge to any organ on request:
   on-demand answers, curated curricula, and per-consumer lesson feeds.

The existing OBS-companion production surface remains MIND's first
integrated surface; acquisition and teaching join it as new surfaces on
the same single-port control plane (127.0.0.1:43906).

## Build order for the muster fleet

1. **gain surface** (`/api/gain`, POST): accept a source reference
   (URL or local doc path from an allowlisted root), extract text,
   distill to a structured entry `{id, title, topics[], body, source,
   sha256, gained_at}` stored under `mind/knowledge.json`.
   Allowlist enforcement mirrors boundary.py path-jail discipline.
2. **teach surfaces**:
   - `/api/teach/topics` (GET) - table of contents of what MIND knows.
   - `/api/teach/entry?id=` (GET) - one entry, full prose.
   - `/api/teach/feed?consumer=N&topic=X` (GET) - per-consumer lesson
     feed; consumers register like haven's capability tokens.
3. **haven bridge**: new entries MAY publish condensed teach cards into
   `haven/teach/` using the existing card schema so aphrodite/riley/
   venus inherit the material through the established curriculum path.
4. **registry row**: once the endpoint is stable, register the control
   plane in `realms/registry.json` at :43906 (T3 satellite posture,
   loopback-only).
5. **gate growth**: extend `mind/verify.py` three-ring gate with
   acquire->store->teach round-trip checks; keep it stdlib-only and
   cwd-self-locating per house law.

## Constraints (house law)

- Standard library only; no cloud; no telemetry; loopback binds only.
- All numbers/config in content modules, never hardcoded inline.
- Every mutating verb gets a witness line (hades audit trail).
- No secrets in the knowledge store; sources are public/technical docs.
- Sentinel derivation must not strangle the grown gate (self-locating).

## Acceptance

- `python mind/verify.py` green with new rings.
- HYPNOS build-gate stays green (already repointed at `mind/verify.py`).
- Doctor 20+/20 suites green after landing.
- A teach round-trip demo: gain a sample entry -> serve it ->
  publish its haven card -> verify card census picks it up.
