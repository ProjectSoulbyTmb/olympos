# HEART capability atlas

The full capability space for HEART at its fullest, mapped to phases and
constraints. Decision authority: `docs/adr/0001-heart-layered-sovereignty.md`.
Phase detail: `docs/plans/heart-roadmap.md`. Wire schemas:
`docs/contracts/heart-interface-v1.md`. Baseline: heart v0.2.0 (audited
2026-08-24 morning; **tree currently absent from the workspace** — restore
and re-verify before any phase lands, per ADR evidence-status note).

## Tiers used here

- **shipped** — in v0.2.0 today; protect, don't regress
- **phased** — has a roadmap phase (H1–H9)
- **stretch** — designed-for, unscheduled; lands only after H5 without breaking C8
- **non-goal** — formally rejected; reversing requires a logged decision

## Capability matrix

| # | Capability | Mistral pattern | Tier | Phase | Notes / hard rule |
|---|---|---|---|---|---|
| 1 | Focus/break timer | — | shipped | — | pure timestamp math; restarts free |
| 2 | Nudge lanes + acks | — | shipped | — | settings-driven cadence |
| 3 | Notes + search | Vibe knowledge search | shipped | H3 upgrades | JSONL; quarantine on corrupt read |
| 4 | Stats/milestones/badges | — | shipped | — | derived, never stored truth |
| 5 | Coach voice (text) | system of record | shipped | H2 skill packs | built-ins byte-equal fallback |
| 6 | Daily digest | — | shipped | H3 grounding | cites note ids |
| 7 | Brain ladder (Ollama) | model tiering | shipped | H5 router | localhost only, small-first, fail-open |
| 8 | Judge/guardrails | Studio evals/judges, Shieldstral | phased | H5 | every generated line gated |
| 9 | Avatar forge + studio | — | shipped | — | SVG pipeline; allowlisted statics |
| 10 | Overlay + Electron shell | — | shipped | H6/H8 extend | lockfile-pinned (`electron ^43.4.1`, caret range); shell hardening mandated (contract §8 Electron clause) |
| 11 | Venus bridge | — | shipped | — | file-only, silently off |
| 12 | Skills system-of-record | prompts/skills SoR | phased | H2 | content-addressed ledger |
| 13 | Typed memory | Vibe persistent memory | phased | H3 | kinds: note/goal/fact |
| 14 | Horizon plans | Vibe multi-step scheduling | phased | H4 | steps bind to focus blocks |
| 15 | Fleet buslink | unified observability | phased | H5 | opt-in via RATATOSK_ROOT |
| 16 | Voice & presence | Voxtral | phased | H6 | client-side SpeechSynthesis; zero deps |
| 17 | Insight engine | Studio observability | phased | H7 | descriptive-only analytics |
| 18 | Widget presence | Studio apps surface | phased | H8 | id allowlist; createElementNS/textContent-only rendering incl. SVG attributes; shell hardening (contract §8) |
| 19 | Deep-work DND flag | — (fleet courtesy) | phased | H9 | advisory flag file, default off |
| 20 | i18n locale packs | — | stretch | via H2 | locale = coach-voice skill pack; no code change |
| 21 | Pack lab (live line editing) | Forge | stretch | post-H5 | preview-before-activate; ledger keeps versions |
| 22 | Desktop global hotkeys | — | stretch | desktop shell | Electron already present; start/pause from any app |
| 23 | Backup rotation of data dir | Vulcan save pattern | stretch | hygiene | copy-rotate, never move |
| 24 | Accounts / cloud sync | — | **non-goal** | — | violates C8 sovereignty |
| 25 | Telemetry home | — | **non-goal** | — | nothing leaves the machine |
| 26 | OCR/doc-intel import | Mistral OCR | **non-goal** | — | no product fit; revisit only by ADR |
| 27 | Model training/fine-tune | Forge training | **non-goal** | — | HEART customizes *behavior data*, not models |
| 28 | Multi-user / shared instance | — | **non-goal** | — | single operator, single machine |

## Mood engine (deterministic)

`mood` is a pure derivation over timestamps and counters (contract §6) —
never persisted, replay-safe. The avatar consumes it: celebrating → badge
burst animation; focused → steady work loop; warming → settle-in; resting →
break sway; idle → ambient breathing. All variants ride the existing SVG
render pipeline (`avatars.renderSVG`) — no new rendering stack.

## Voice architecture decision sketch

Speech happens **in the UI layer** (Chromium/Electron SpeechSynthesis), not
Node: zero backend deps, zero audio libs, OS-provided voices. Gating logic
(quiet hours, one-shot-per-event) lives in pure `lib/voice-policy.js` —
the server decides and transports the verdict via `state.voiceGate`
(contract §6), so the decision math is unit-testable in Node while the
client merely obeys. Failure mode is always silence, never an error surface.

## Privacy & threat model (short form)

- Data residency: everything under `HEART_DATA_DIR`; export = folder copy.
- Network surface: loopback HTTP + optional localhost Ollama. Nothing else,
  ever (C8).
- Buslink publishes aggregate `scoreHint` only — no notes, no lines, no raw
  behavior (C7).
- DND flag contains session timing only (H9).
- Behavioral data (focus logs, nudge responses) is sensitive-by-inference;
  insights stay local and descriptive; fleet sees at most what C7 allows.
- Threat: local malicious process reading data dir — mitigated by OS user
  isolation only; documented honestly rather than pretended away.
- **Loopback is not a trust boundary (rev 2):** the operator's browser is on
  loopback too. DNS rebinding lets a hostile page rebind a hostname to
  127.0.0.1 and read the API same-origin; any open page can cross-origin
  POST/beacon to state-changing endpoints (`fetch` no-cors,
  `sendBeacon`). Mitigations land in H1: `Host` header allowlist
  (`127.0.0.1:4767`/`localhost:4767`) + same-origin/per-boot-token checks
  on mutating verbs.
- **Shell threat (rev 2):** DOM-level injection inside a legacy-configured
  Electron window is Node-level RCE with access to `HEART_DATA_DIR`;
  contract §8's webPreferences/CSP mandate closes the amplifier.

## Hygiene backlog (no phase yet, take with any PR)

- Graceful EADDRINUSE message ("HEART is already running") instead of raw throw.
- `log.jsonl` rotation policy (size cap + archive) before insights ship (H7 reads get cheaper).
- `npm test` in CI as informational gate lands with H0 — keep it green.

## Sequencing rule

H-phase order is dependency-honest (H2 skills feed H6 voice lines and H8
widgets; H4 plans feed H7 velocity). Stretch items must not jump the queue:
each lands only when its phase's acceptance is green and its rollback path is
written.
