# HEART interface contract v1

Normative schemas for the wire surface designed in ADR-0001 and phased in
`docs/plans/heart-roadmap.md` (H1–H5). Base truth: `heart/heart.js` (v0.2.0,
morning-audit evidence; tree currently absent from the workspace — re-verify
line-level claims when restored, per ADR evidence-status note). All endpoints
bind `127.0.0.1` only. JSON everywhere.

## 1. Response envelope (H1)

Every response object carries `error` — string on failure, `null` on success
(fleet house contract). Baseline note: v0.2 covers error paths except
DELETE-avatar 404 (returns `{deleted:0}`, no field); H1's sweep enumerates
every endpoint including that one.

| Field | Type | Required | Notes |
|---|---|---|---|
| `error` | string \| null | yes | machine-readable message; null = success |
| `schema_version` | number | in `/api/state` | 1 from H1 onward |

Example pair — success:

```json
GET /api/state → 200
{ "error": null, "schema_version": 1, "now": 1771900000000,
  "timer": {"phase": "running", "kind": "focus", "endsAt": 1771901500000},
  "dueNudges": [], "notes": [] }
```

Example pair — error:

```json
POST /api/snooze {"lane": "coffee"} → 400
{ "error": "unknown lane" }
```

Unknown-field rule: clients ignore unknown fields; servers reject unknown
**setting/skill/plan** fields with `400 {error: "unknown field: <name>"}`.
(Deliberate tightening: config.js currently *silently ignores* unknown keys;
the v1 contract makes rejection explicit.) **Ship order (rev 2):** this is a
behavior change for any client posting extra keys — the server starts
rejecting only after the bundled UI stops sending legacy keys, or the rule
is gated on `schema_version >= 1` being acknowledged by the client.

## 2. Skills manifest (H2)

Ledger: append-only `data/skills/ledger.jsonl`; one record per line; active
selection in `data/skills/state.json`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | sha256-16 of canonical manifest JSON |
| `v` | number | yes | manifest revision, starts 1 |
| `kind` | enum | yes | `coach-voice \| nudge-plan \| digest-style` |
| `name` | string | yes | human label |
| `lines` | object | for coach-voice | lane/event → line array (same shape as coach.js built-ins) |
| `cadences` | object | for nudge-plan | `{waterMin?, postureMin?, eyesMin?}` ≥ 1 |
| `createdAt` | ISO-8601 | yes | |
| `source` | enum | yes | `builtin \| import` |

Error path: corrupt ledger line → moved to `data/skills/quarantine.jsonl`,
built-in pack serves the request, response stays `200` with
`"skill_fallback": true` on `/api/state`. Missing ledger file → built-ins,
no error surfaced to the UI.

```json
{"id":"9f1c…","v":1,"kind":"coach-voice","name":"stoic-lite",
 "createdAt":"2026-08-24T10:00:00Z","source":"import",
 "lines":{"focus-start":["One block. Just one."]}}
```

## 3. Horizon plan (H4)

Store: `data/horizon.jsonl` (journal of mutations); current plans derived by
replay — same discipline as timer's timestamp math.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | `p-<ts>-<rand4>` |
| `goal` | string | yes | 1–200 chars |
| `createdAt` / `dueAt?` | ISO-8601 | see left | dueAt optional, must be > createdAt |
| `steps[]` | array | yes | ≥1 element |
| `steps[].id` | string | yes | `s-<n>` unique within plan |
| `steps[].title` | string | yes | 1–120 chars |
| `steps[].estBlocks` | number | yes | focus blocks estimate, ≥1 |
| `steps[].doneAt?` | ISO-8601 | derived | **read-only, computed**: timestamp of the first focus-session completion bound via `stepId`; never client-set — fits the journal-replay discipline |

Binding: a completed focus session may carry `stepId`; session log lines gain
optional `"stepId"` — additive, old logs valid forever.

Example pair:

```json
POST /api/plan {"goal":"Ship HEART v0.3","steps":[
  {"id":"s-1","title":"skills layer","estBlocks":4}]} → 200
{"error":null,"plan":{"id":"p-1771900000-a1b2","goal":"Ship HEART v0.3",
 "createdAt":"2026-08-24T10:00:00Z","steps":[{"id":"s-1",
 "title":"skills layer","estBlocks":4}]}}
```

```json
POST /api/plan {"goal":""} → 400
{"error":"goal must be 1-200 chars"}
```

Digest gains `plans:[{id, goal, stepsDone, stepsTotal}]` when any plan is open.

## 4. Opt-in bus bridge letter (H5, only when RATATOSK_ROOT set)

Topic row `vitals.heart` must exist in the INTEGRATION.md §6 catalogue first.
Max one publish per digest.

**Rev 2 — conformance correction:** heart does not hand-write letters into
topic files (that breaks cursor/seq semantics). It calls the bus API:

```js
bus.publish("vitals.heart", {
  sessions: 3, focusMinutes: 75, streakDays: 6, scoreHint: 82
}, frm="heart", kind="vital")
```

`ratatosk/bus.py::broadcast()` stores exactly this record shape per topic
line — `{v, topic, seq, from, kind, ts, epoch, payload}` (no `id`, `rights`
or `error` member; those live in the point-to-point envelope, not broadcast
records):

```json
{"v":1,"topic":"vitals.heart","seq":42,"from":"heart","kind":"vital",
 "ts":"2026-08-24T21:00:00","epoch":"2026-08-24",
 "payload":{"sessions":3,"focusMinutes":75,"streakDays":6,"scoreHint":82}}
```

Enforcement prerequisites (verified against disk): `buskit/envelope.py`
validates topics by exact-match `TOPICS` lookup — add
`"vitals.heart": {"vital"}` before any publish or validation raises
`unknown topic`; `ratatosk/bus.py` requires a `kind` constant for `vital`.
INTEGRATION §6's prose says `vitals.<organ>` while the implementation uses
flat per-organ keys — reconcile by adding the explicit row (wildcard
matching is out of scope). The earlier sample letter in this section was
non-conformant to both shapes and is superseded by the above.

Heartbeat: `data/post/heart/heartbeat.json` stamped on activity, same as every organ.

## 5. Rights mapping (REST ↔ fleet ladder)

| Verb class | Endpoints | Ladder |
|---|---|---|
| observe (L0) | all GETs (`state/stats/search/catalog/digest`) | watcher |
| act (L1) | POST start/stop/snooze/note/settings/skills/plan; DELETE avatars | agent_rw |
| administer (L2) | none exists | keep it that way unless promoted via checklist |

Local-only loopback means the ladder is declarative today; it becomes binding
only at T2 promotion (roadmap checklist step 2). Vocabulary note (rev 2):
`rights` values here use the norn profile vocabulary (`watcher`, `agent_rw`)
per `buskit/envelope.py::PROFILES`; INTEGRATION §4.1's own example uses
registry-role vocabulary instead — inherited fuzziness, flagged for the
promotion checklist. Enforcement note: H1's Host/Origin checks (§8-adjacent
threat model) are what give this ladder practical value on loopback —
without them any web page can hit L1 verbs cross-origin.

## 6. Voice settings & mood (H6 / H4)

Additive `/api/state` field and known setting keys (unknown keys still
rejected per config.js rule).

| Field | Type | Default | Notes |
|---|---|---|---|
| `mood` | enum, in state | derived | `focused \| warming \| resting \| idle \| celebrating`; **derived from timestamps only, never persisted** |
| `voiceEnabled` | bool | `false` | master switch; off = zero audio path |
| `voiceRate` / `voicePitch` | number | `1` | clamped 0.5–2.0 server-side |
| `voiceName` | string \| null | `null` | platform voice; ≤80 chars; unknown name falls back silently to platform default at render time |
| `quietHours` | object \| null | `null` | `{start:"21:00", end:"07:00"}` local time; speech suppressed inside window |
| `voiceGate` | object, in state | derived | `{speechAllowed: bool, reason: "ok"\|"quietHours"\|"disabled"}` — decided server-side by voice-policy.js; the client speaks only what state allows. Prerequisite: config.js type-aware persistence (reviewer-verified boolean-revert bug; see roadmap H6). |

Mood derivation is deterministic from existing timestamps: `celebrating`
(milestone unlocked this session-end) > `resting` (break running) >
`focused` (focus running ≥5 min) > `warming` (focus running <5 min) >
`idle`. Replay-safe: same logs → same mood.

## 7. Insights endpoint (H7)

```http
GET /api/insights?range=day|week|all
```

Success:

```json
{ "error": null, "range": "week", "generatedAt": "2026-08-24T21:00:00Z",
  "bestHour": {"hour": 9, "focusMinutes": 210},
  "heatmap": [{"startIso": "2026-08-18", "buckets": [0,45,120,0]}],
  "nudgeResponse": {"water": {"shown": 12, "acknowledged": 9}},
  "planVelocity": {"stepsDone": 3, "blocksUsed": 11} }
```

Error path:

```json
GET /api/insights?range=month → 400
{ "error": "range must be day|week|all" }
```

Empty log → valid structure with `bestHour:null`, zeroed counters — never
NaN/undefined. Output is byte-deterministic for identical log input.

## 8. Widgets layout (H8)

```json
GET /api/widgets → 200
{ "error": null,
  "layout": [{"id":"timer","slot":"a"},{"id":"mood-avatar","slot":"b"}] }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `layout[]` | array | yes | order = z-order in overlay |
| `layout[].id` | enum | yes | allowlist: `timer \| nudge-next \| streak \| plan-ring \| mood-avatar` |
| `layout[].slot` | string | yes | grid slot id, `[a-f][1-6]` |

Error paths: unknown id → `400 {"error":"unknown widget: <id>"}`; corrupt
stored layout → defaults served with `"layout_reset": true`, corrupt file
quarantined. Widgets render text/SVG only — the contract forbids any HTML
string passthrough.

**String-safety mandate (tightened rev 2):** every user-derived string
(plan goal/title, avatar name, note text) reaches the DOM exclusively via
DOM APIs — `textContent` for text, and for SVG exclusively
`document.createElementNS(...)` element construction plus `textContent`
text nodes. **Never** string-built markup, **never** user data interpolated
into attributes (`href`, `style`, `on*` — attribute-borne vectors survive
text escaping via `javascript:`/entity URLs and `<image href>` beacons).
Static widget chrome may use string templates but interpolates zero user
data. The known sink (`studio.html` avatar-name `innerHTML`) gets a retro
fix in H8, covered by an injection-payload test whose corpus includes
SVG-borne cases: `</text><script>alert(1)</script>`,
`"><svg onload=alert(1)>`, `&#106;avascript:` entities, and
`<image href="http://127.0.0.1:4767/api/state">` beacon probes — assert
zero element creation **and zero network requests**.

**Electron shell mandate (rev 2):** widgets render inside the
`desktop/main.js` BrowserWindow; DOM containment is worthless if the shell
exposes Node. Normative for H8 (and retro-checked at H6): `nodeIntegration:
false`, `contextIsolation: true`, `sandbox: true`, no `loadURL` of remote
content ever, CSP meta `default-src 'self'` on dashboard/overlay/studio
pages, and a startup self-test asserting those flags (deviation = boot
failure). Without this, any injection that slips through becomes Node-level
RCE with filesystem access to `HEART_DATA_DIR`.

## 9. Deep-work DND flag (H9, advisory)

File: `<dndDir>/heart-focus.flag` (written only when `dndDir` configured).

```json
{"v":1,"untilTs":1771911500000,"sessionId":"f-1771900000","reason":"focus-block"}
```

Contract for consumers (Venus, fleet agents): **advisory only**; MUST treat
flag as expired after `untilTs`; MUST NOT block or queue-kill on it — defer,
never drop. HEART clears the file at session end but readers cannot rely on
the clear (crash-safe by expiry). Writes are atomic (temp + rename);
unparseable flags are treated as expired; writers clamp `untilTs` to at
most 24h ahead.
