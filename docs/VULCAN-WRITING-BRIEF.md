# VULCAN — Writing Brief: "Build All Written Text for Olympos"

**Prepared for:** VULCAN (autonomous writing agent, `auto/vulcan` lane)
**Prepared by:** primary session, per operator order 2026-08-27
**Scope:** ALL written/user-facing text across the Olympos (THOTH) fleet on `D:\THOTH`
**Delivery:** this file + inline copy to the operator

---

## 0. What you are being asked to do

Produce, revise, and keep consistent **every piece of written text** in this
repository that a human or another agent reads: repository docs, per-organ
READMEs, the architecture/strategy/integration/flow docs, ADRs, contracts,
plans, the knowledge corpus, in-code docstrings, CLI help text, error and
alert messages, schema/rule messages, and (where the operator asks) satellite
product copy. You are the **scribe of record** for prose. You do not write
code logic — you write the words around it, and you keep them true to the code.

You are an AI agent. Treat the codebase as your source of truth; the docs are
models to match, not the authority. Re-verify against disk before asserting a
fact (rule 1 of the ATHENA doctrine, see §6).

**How to ship:** follow `FLOW.md`. Work only in the `auto/vulcan` worktree
(`D:\THOTH\.worktrees\vulcan` or create it). One branch, squash PRs to `main`,
green `python doctor.py --ci` before shipping. Never commit to `main` directly.

---

## 1. Project identity (use these verbatim where a one-liner is needed)

- **Project name:** *Olympos* (ecosystem). The repo root is `THOTH` (the
  integration mirror / home base). Historically "Project Olympos".
- **One-line positioning (canonical, from `INTEGRATION.md` §0):**
  > You describe a game or an app; Olympos designs it, writes the code,
  > verifies it, and iterates autonomously — entirely on your machine,
  > fully open source. The Vulcan sandbox is the proving ground where
  > build-and-verify loops harden before they target arbitrary projects.
- **Elevator framing:** a local-first, fully autonomous, open-source game and
  app development platform + the protective/operational ecosystem that runs it.
- **What it is NOT (hard non-goals — never imply otherwise):**
  - Not a cloud service. No external dependency for core (T0–T2) function.
  - Not a game-simulation engine. The retired game-simulation core was
    removed 2026-08-24; **no game-simulation naming, code, or third-party
    game marks remain anywhere in the fleet.** The sanctioned visual layer is
    a thin read-only viewer over a JSON-lines realm server — never a new sim.
  - Not a SaaS. Operator-supplied snapshot files only; no shipped scrapers.

---

## 2. Audience

Write for three overlapping readers; label mentally, do not label in text:

1. **Operator / power user** — runs `doctor.py`, `sentinel.py`, registers
   scheduled tasks, reads ADRs. Wants precise, copy-pasteable commands and
   exact port/paths.
2. **Fleet agent** — another autonomous writer that consumes docs as
   spec. Wants unambiguous contracts, enumerated guarantees, machine-readable
   tables.
3. **External contributor / curious dev** — reads README first. Wants the
   pitch, the map of organs, and a quick start that actually works.

Tone by surface:
- Root README / public docs: confident, plain, concrete. Sell the autonomy,
  prove the trust model.
- Architecture/strategy/integration/flow: clinical, declarative, table-heavy.
  "Verify before claiming health." State guarantees as owned-and-tested.
- ADRs/contracts/plans: decision-oriented; record *what was decided* and *why*,
  with rollback.
- In-code: terse docstrings, no marketing. Explain the contract, cite the
  lesson id (e.g. `L006`) when a rule is enforced.
- Error/alert messages (incl. Vulcan `content.py`): short, actionable, name the
  failing thing. Never blame the user; name the fault.

---

## 3. Voice & style rules (match the existing docs)

- **Terse and concrete.** Prefer "quarantine, never destroy" over a paragraph.
- **Tables over prose** for any enumerated set (organs, ports, guarantees,
  tiers, gates). The repo's docs are table-driven; follow that.
- **Present tense, active voice.** "Every realm ships a verify suite." Not
  "A verify suite should be shipped by every realm."
- **Code/font conventions:** `monospace` for commands, paths, ports, module
  names, env vars, and JSON keys. Use fenced ```powershell``` / ```python```
  / ```json``` blocks for runnable or structural content.
- **No emojis.** No exclamation-mark marketing. Calm, engineering register.
- **Define on first use**, then use the short name. ZEUS = protection kernel;
  Vulcan = smart-building automation sandbox / proving ground.
- **Cite provenance:** when a doc states a rule, it cites the lesson id from
  `knowledge/lessons.json` (e.g. "atomic or nothing (L006)"). Continue this
  convention — if you state a doctrinal rule, find or propose its `L###`.
- **Dates** in `YYYY-MM-DD` (e.g. 2026-08-24). Keep decision-log rows dated.
- **Numbers live in code, not prose.** See §5 — never hardcode a tunable in
  running text when a `content.py`/registry value exists; reference it.

---

## 4. Hard naming, brand & legal constraints (do NOT violate)

These are non-negotiable; violations are review-rejected and CI-lint-refused
in places.

1. **Trademark hygiene (L024).** Public product names avoid third-party
   marks. Public product names were moved to the public domain
   2026-08-23; internal organ names follow the current scope policy. Keep
   disclaimers in the README.
2. **No retired-scope residue.** Zero references to the removed game-sim core,
   its scripts, seeds, or registry rows. `verify_scope.py` guards this
   boundary; your text must too.
3. **Repo home is `D:\`.** The only localside repository home (L033). The
   OneDrive `Documents\Default Project` checkout is **frozen** — never cite it
   as disk truth, never reference OneDrive paths as canonical. For VOLTAGE
   task installers specifically, `voltage-*` names only; OneDrive/Olympos
   references are lint refusals before installation.
4. **Organ names = Greek deities / role words** already in use: ZEUS, Hades,
   Vulcan, GAIA, THOTH, PTAH, Ratatosk, NORN, Hypnos, Atlas, Daedalus, Relay,
   Hebe, Poseidon, Kinema, Persephone, Haven, Ares, Artemis, Sindri, Forseti,
   Kronos, Harmonia, Hermes, Heimdall, Venus, Aphrodite, Riley, Eidovara,
   Athena, Metis, Argus, Logia, Kerux, Kourai, Talos, Perdix, Icarus, Epeios,
   Trophonios. Do not invent new organ names without an ADR + operator sign-off.
5. **No secrets in text.** License keys, tokens, passphrases, `.pem` contents
   never appear in docs, lessons, codices, or logs (engineering rule 18,
   FLOW.md boundaries). Scanners denylist binaries; describe secret *handling*,
   never the secret.
6. **Open source / local-first** is the default stance; state it, don't
   qualify it away.
7. **The five guarantees are sacred (INTEGRATION §1).** Any text that implies
   weakening one is wrong by default; changing one requires an ADR with
   migration + rollback. List them as owned-and-tested, not aspirational:
   1. Deterministic replay — `norn.replay`
   2. Every mutation attested — `norn.witness` → Hades
   3. Least privilege by default — `norn.rights` / THOTH L0–L2
   4. No partial reads — `ratatosk.bus` atomic `os.replace`
   5. Health claims require gates — verify suite must pass

---

## 5. The "numbers live in code" contract (critical for Vulcan's own realm)

The architecture-playbook pattern 2 ("Data lives once") and the Vulcan
house contract (DESIGN.md 2026-08-23) require:

- **Every numeric constant for a realm lives in its `content.py`** (Vulcan:
  `vulcan/content.py`). Mechanics read it; nothing re-declares a table.
- **Therefore your prose must not bake in tunables.** When documenting Vulcan,
  reference the constant's *meaning* and point at `content.py` rather than
  printing the value. Example: "comfort target is `COMFORT_TARGET_C` in
  `content.py`" — not "the temperature is 21 °C" (which will rot).
- **User-facing strings that ARE data** (alert messages, scene names, rule
  names in `content.py`) are part of the data module and you may author/revise
  them *there*, keeping them consistent with the rest of the prose. Current
  Vulcan strings to preserve the voice of: `sec_away_open` ("Contact opened
  while building is AWAY: {device}"), `smoke_response`, `freeze_guard`,
  `server_room_watch`, `evening_precool`. Keep alert messages short,
  name-the-fault, and templated with `{...}` placeholders the engine fills.
- **Registry values** (ports, paths, kinds, tiers, verify commands) live in
  `realms/registry.json` — single source. INTEGRATION.md supersedes the older
  `fleet.json` proposal; cite `realms/registry.json` as authoritative for
  endpoints.

---

## 6. Canonical facts you must get right (verify against disk; these are
current as of 2026-08-27 but re-check)

**Version:** `1.16.0` — `D:\THOTH\VERSION` is the single version source. Source/
site/service versions must agree (STRATEGY Phase 4).

**Port map (authoritative in `realms/registry.json`; re-audited 2026-08-25):**
| Realm | Port | Note |
|---|---|---|
| vulcan | 43901 | building-sandbox, SDK `VulcanSDK`, `vulcan/host.py` |
| zeus | 43902 | protection kernel |
| ptah | 43903 | agent kernel, REST `127.0.0.1:43903` |
| aphrodite | 43904 | external satellite `D:/Aphrodite` |
| daedalus | 43905 | workshop, `127.0.0.1:43905` |
| riley | 43907 | external satellite `D:/riley` |
| harmonia | 43908 | re-based after colliding with riley studio |
| haven | 43910 | search organ, SQLite FTS5 |
| heart | 4767 | **proposed only / UNBOUND** — tree absent; do not claim live |
| 43590 / 43591 | — | **retired**; any listener there is a squatter |

**Rights ladder (one map, two vocabularies — INTEGRATION §4.3):**
watcher / L0 read-only < agent_rw / L1 standing < admin / L2 elevated;
build = agent escalated to agent_rw, escalation logged in `norn.rights` + THOTH
grants. Default least privilege; agents start `agent` (introspection only).

**Tier model (STRATEGY §3.1):** T0 Infra (doctor, sentinel, CI, buskit,
forseti, knowledge, learning, gates) · T1 Kernels (zeus, gaia, ratatosk, norn,
hypnos, atlas, ares, artemis, daedalus, relay) · T2 Realms (vulcan, hades,
hebe, poseidon, kinema, harmonia, haven, persephone, sindri, kronos) · T3
Satellites (riley, aphrodite, riley-studio, godot-template, venus/assistant,
eidovara/project---soul — gitignored, self-gated, never block core CI).

**Autonomous build loop (the product — INTEGRATION §7):**
describe → design → code → verify → prove → seal → ship; each stage bus-gated;
failures emit `build.stage{iterate}` up to an L2-bounded policy cap.

**Time model:** no organ invents its own timer; periodic work registers with
`norn.pulse` (`every_beats`, SLOs, quarantine, revive). Node organs follow
Venus `heart.js`. Vulcan sim tick = 5 min logical; realm tick 0.6 s (see
`content.py` for the sandbox's own cadence: real tick 2.0 s).

**Vulcan sandbox specifics (from `content.py`, reference not copy):**
host `127.0.0.1`, port 43901, `MAX_SESSIONS` 16, `SAVE_VERSION` 1,
`START_CLOCK` 2026-08-23 06:00; zones lobby/hallway/utility/garage/office_a/
office_b/meeting; modes home/away/night/vacation; warden self-heals stuck
sensors, runaway HVAC, vacant lights, sheds load under escalation, recovers
corrupt saves from rotating backups (`backup_copies` 3).

**Doc-of-record reading order (ATHENA codex §1) — read these before writing:**
1. `INTEGRATION.md` (model of record) 2. `STRATEGY.md` 3.
`knowledge/engineering-rules.md` (law) 4. `knowledge/architecture-playbook.md`
5. `knowledge/lessons.json` 6. `DESIGN.md`. Plus root `AGENTS.md` (fleet-build
doctrine) and `FLOW.md` (shipping).

---

## 7. Inventory of text surfaces to build / maintain

Grouped. For each, the file(s) and what "done" means. Prefer editing existing
files; create only where the inventory marks "(missing)".

### 7.1 Root repository docs (live)
- `README.md` — pitch, organ map table, quick start. **Model for voice.**
  Keep the organ table in sync with `realms/registry.json` (doc drift is a
  known high-risk gap — STRATEGY §2.1).
- `AGENTS.md` — standing orders; "all building delegated to muster fleet."
- `DESIGN.md` — what the architecture IS; ecosystem table + hard rules +
  decision log. Append dated decision-log rows for any change you document.
- `STRATEGY.md` — direction; tier model, gaps, phased roadmap, risk register,
  non-goals. Keep non-goals and risk register current.
- `FLOW.md` — multi-agent git flow; keep the worktree/topology table accurate.
- `INTEGRATION.md` — model of record; runtime topology, envelope, registry v2
  schema, rights ladder, build loop, acceptance A1–A8. Highest-truth doc.
- `VERSION` — single version source; bump only via the release process.
- `LICENSE` — seed present; ensure it matches the public-domain stance.

### 7.2 `docs/` suite (live)
- `docs/SAFETY_DOCTRINE.md` — protective guarantees in operator language.
- `docs/adr/` — `0001`–`0005` present. New decisions = new ADR; format:
  title, status, context, decision, consequences, rollback.
- `docs/contracts/` — `heart-interface-spec-v1.md`,
  `voltage-command-spec-v1.md`. Contract docs: schema + owner + test.
- `docs/plans/` — capability-ledger, expansion-stability, heart-*,
  project-voltage-roadmap, release-v3-stable, riley-studio, sovereign-workshop,
  ui-design-system, and `cycles/` dated journals. Plans are proposals; mark
  human-gated items explicitly.

### 7.3 Per-organ READMEs (audit and fill)
Present for many (gaia, hades, ratatosk, norn, hypnos, atlas, relay, hebe,
poseidon, kinema, persephone, haven, ares, artemis, daedalus, sindri, forseti,
kronos, harmonia, riley-studio, server-deploy, godot-knowledge-db,
image-toolkit, templates/godot-game, knowledge, transfer). **Vulcan has NO
README** — author `vulcan/README.md` first: what the sandbox is, the
content.py contract, the warden, the JSON-lines server + `error` on every
response, the one SDK surface, versioned saves, and its verify gate
(`python vulcan/verify_vulcan.py`). Each organ README: one-paragraph role,
quick-start command(s), port (if any), verify command, and a pointer to its
DESIGN/INTEGRATION section.

### 7.4 In-code text (prose that ships in the binary)
- **Module/docstring headers** — every `.py`/`.js` top docstring states the
  contract in one sentence + cites the lesson id when a rule is enforced.
- **CLI help** (`argparse`/`--help`, `cli.py` across organs) — imperative,
  example-driven. Every command shows a working invocation.
- **Error messages** — short, name the fault, suggest the fix. Vulcan and all
  JSON-lines servers return an `error` field on EVERY response (house
  contract); your error strings must be human-readable and non-leaky (no stack
  dumps, no secrets).
- **Alert / rule messages** — Vulcan `content.py` DEFAULT_RULES + WARDEN
  messages (see §5). Keep the templated `{...}` placeholders.
- **Schema/rule rejection text** — precise `key + type` (engineering rule 2).

### 7.5 Knowledge corpus (live, must stay true)
- `knowledge/lessons.json` — append-only, monotonic `L###`, never renumber,
  deprecate-don't-delete, every entry cites `source`.
- `knowledge/architecture-playbook.md`, `knowledge/engineering-rules.md` —
  patterns/rules each link a lesson id and living code.
- `knowledge/library/*.md` — agent-architecture, automation-contracts,
  fleet-topology, git-multi-worktree, incident-playbook, knowledge-management,
  llm-agent-flight, llm-integration, mcp-protocol, observability,
  python-stdlib, security-guardrails, testing-doctrine, windows-pitfalls.
- `knowledge/webstudio/*` — external product DB (Webstudio): agent/MCP
  integration, data/CMS, design system, publishing, playbooks, overview.
- `knowledge/goth/*` — Godot research (background only; never a sim core).
- When you author a lesson/rule, keep it context-free: name the *pattern*,
  not the old project.

### 7.6 Satellite product copy (out of core scope unless operator directs)
- `assistant/` (Venus), `eidovara` / `project---soul` / `project-soul` /
  `live-soul` (Eidovara lineage), `D:/riley`, `D:/Aphrodite`. These are
  gitignored, self-owned, non-blocking. Their legal/brand docs
  (`docs/BRAND_GUIDE.md`, `TRADEMARK_*`, `COPYRIGHT.md`, `MARKETING_CLAIMS.md`)
  already exist and are maintained by their own lanes. **Do not** rewrite
  satellite legal copy unless the operator explicitly asks; if you touch it,
  preserve their trademark/copyright posture and do not import Olympos
  internal organ names as if they were the product's.

---

## 8. Quality bar & gates for your text

1. **Truthful:** every factual claim re-verified against disk (code,
   `realms/registry.json`, `VERSION`, `content.py`). Stale truth is worse than
   missing truth (codex §5).
2. **Consistent:** organ names, ports, tiers, and the five guarantees read
   identically in every doc. One name, one number, one source.
3. **No drift:** README/DESIGN organ tables match `realms/registry.json`
   membership and tiers (STRATEGY §2.1 gap).
4. **Self-gated:** run `python doctor.py --ci` (it compiles entrypoints,
   checks port squatters, baselines, and discovers every `verify_*.py`).
   Doc-only PRs still must not break the safeguards pre-commit hook
   (`safeguards/check.py`: syntax, duplicate top-level defs, JSON validity).
5. **Shipped correctly:** `FLOW.md` — `auto/vulcan` worktree, squash PR,
   no direct `main` push (pre-push hook blocks it).
6. **No secrets, no retired-scope, no OneDrive-as-truth, no third-party
   marks** (§4).

---

## 9. Operating instructions for you (VULCAN)

1. Read §6's doc-of-record list end to end before authoring.
2. Start with the highest-value, currently-broken item: **`vulcan/README.md`
   does not exist** — write it. Then reconcile the root README/DESIGN organ
   tables against `realms/registry.json`.
3. For each surface in §7, decide: (a) exists-and-true → leave; (b)
   exists-and-drifted → fix against disk; (c) missing → author to the voice in
   §3. Log every decision in your PR description.
4. Keep tunables in code (§5); in prose, reference the constant, don't print
   it.
5. When you state a new rule, attach or propose its `L###` (coordinate with
   the learning subfleet; operator sign-off required to land lessons).
6. Never weaken a guarantee (§4.7) without an ADR + operator sign-off.
7. Ship per `FLOW.md`; keep PRs small and frequent.

---

*End of brief. This file is the assignment; the codebase is the authority.
When in doubt, re-read the disk and ask the operator — do not guess a fact.*
