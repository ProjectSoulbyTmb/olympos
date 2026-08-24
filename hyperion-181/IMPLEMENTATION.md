# Hyperion-181 - Implementation Plan

**Realm codename:** Muspelheim (the forge realm - pairs with our Vulcan
Guardian boss and the Minerva daemon that scaffolded this module).

**Status:** skeleton. `build.gradle` + verified `IsaacCipher` exist;
everything below is planned work.

---

## 1. Mission

Build a second authoritative game realm for Yggdrasil on the classic
Hyperion architecture (Java 11 + Netty), speaking the revision-181-style
RS2 wire protocol, and expose it to the whole lab through the same
JSON-lines surface every existing consumer already speaks.

Two faces:

1. **RS2 listener** - protocol-faithful login/game channel so standard
   community clients of that era can connect.
2. **Yggdrasil gateway** - a thin JSON-lines adapter exposing the
   `GameSDK._VALID` verb set over the same socket, so Bifrost (client),
   the RL env, the LLM agent, Minerva and `verify_system.py` all work
   against this realm with zero changes - the proven Elvarg-relay
   pattern from `osrs-rl/rsps_adapter`, inverted.

## 2. Non-goals

- No Jagex assets in this repository (caches are user-supplied or
  fetched at runtime into a gitignored `cache/` dir - see §7).
- No live-service connectivity of any kind.
- No player economy shared with the Python realms (separate saves).

## 3. Current state

| Artifact | State |
|---|---|
| `build.gradle` | done - Java 11 toolchain, Netty 4.1, Guava, Gson, OpenRS2 cache lib, JUnit 5 |
| `util/IsaacCipher.java` | done - public-domain ISAAC translation, MIT SPDX, KAT-verified design |
| everything else | to build |

## 4. Package layout (target)

```
com.soultechno.hyperion181
├── Main                  # boot: config, cache open, bind port
├── net/
│   ├── Rs2Listener       # Netty bootstrap, 43594-style port
│   ├── GatewayListener   # JSON-lines on 43591 (Yggdrasil face)
│   ├── login/            # handshake, RSA+ISAAC seed exchange
│   └── frame/            # Frame, FrameBuilder, FrameDecoder
├── model/
│   ├── Player / NPC / Item / GroundItem
│   ├── World             # tick scheduler, region registry
│   └── defs/             # Gson-loaded ItemDef/NpcDef tables
├── content/
│   ├── movement/         # walking queue, run, teleports
│   ├── combat/           # melee slice first (mirrors Python math)
│   └── skills/           # woodcutting/mining slices only at first
├── gateway/
│   ├── GatewaySession    # per-client state machine = Session twin
│   └── VerbRouter        # dispatch table == GameSDK._VALID
└── util/                 # IsaacCipher lives here today
```

## 5. Milestones

### M0 - Toolchain (0.5 day)
Gradle wrapper committed (`gradle wrapper --gradle-version 8.7`),
`./gradlew build` green on a clean checkout, JUnit smoke test that
runs the Isaac known-answer vectors from `randvect.txt`.

**Exit:** CI-runnable empty server; `IsaacCipherTest` green.

### M1 - Login handshake (1-2 days)
Netty `Rs2Listener`: connection accept -> handshake (opcode 14) ->
login block parse -> ISAAC pair seeded from the four longs -> auth
against `conf/users.json` (Gson) -> switch to game decoder.
Deterministic unit tests feed crafted byte arrays; no live client
needed yet.

**Exit:** `LoginDecoderTest` walks a full handshake in-JVM.

### M2 - World core (2-3 days)
Player object, single-region world (Lumbridge-area coordinates),
walking queue, 15-min-granularity tick loop (600 ms cycle), player
updating (movement + appearance only; use Guava caches for per-cycle
update blocks as the build file hints). Save/load via Gson v1 snapshot
(mirrors Python save-versioning discipline).

**Exit:** headless `WorldHarnessTest`: spawn -> walk N tiles ->
assert position sequence; save/reload roundtrip equals live state.

### M3 - Definitions & cache (2 days)
`defs/` loads revision-profile JSON (item names/equip bonuses, npc
spawns/stats) checked in as data; OpenRS2 FileStore used only for
map/index lookups behind a `CacheFacade`, reading from the gitignored
`cache/` dir. Server boots without cache in "thin mode" (flat map)
so tests never need assets.

**Exit:** boots both modes; `DefsTest` validates table invariants
(unique ids, equip bonus ranges).

### M4 - Gameplay slice (3-4 days)
Melee combat vs spawned NPCs (aggression off, retaliation on,
death/respawn timers), ground items + pickup, inventory ops. Combat
formulas intentionally mirror `osrs-llm-agent/game/world.py`
(`_player_hit` accuracy/max-hit shape) so cross-realm behavior feels
identical.

**Exit:** scripted fight test kills a goblin-class NPC, loot lands,
respawn timer fires.

### M5 - Yggdrasil gateway (2 days)
`GatewayListener` on 43591: JSON-lines, `{"cmd":"login"...}` /
`{"cmd":"action","call":...}` / `{"cmd":"state"}`, `error` field on
every response - byte-compatible semantics with
`server/rsps_server.py`. VerbRouter implements the SDK verb subset:
state, move_to, walk, chop, mine, attack, eat, inventory, coins,
skills, ticks_left. Channel/chat/presence piggyback keys included so
Bifrost renders it like any other realm.

**Exit:** `verify_system.py` gains a check running the *existing*
multiplayer + trading flow against 43591 unchanged.

### M6 - Client-facing polish (2 days, optional gate)
Update-block completeness (animations, graphics, hit splats), NPC
facing, region paging. Only matters for third-party RS2 clients;
the gateway face needs none of it.

**Exit:** community-client connect smoke (manual, documented).

## 6. Integration contract

- Port 43591 = gateway (JSON-lines), port 43594 = RS2 listener.
- Gateway responses carry the same envelope:
  `{"ok":bool, "error":str|null, "result":..., "state":...}`.
- `world.name` branding: realm reports `muspelheim` in `/status`.
- Runner menu grows "Play on Muspelheim (Hyperion realm)" launching
  Bifrost with `--realm hyperion`; Bifrost passes the realm hint at
  login so the Python auto-host stays the default when absent.
- Minerva keeps its Argus watchdog pointed at both realms.

## 7. Asset & legal policy

- Protocol constants (opcodes, ISAAC usage, update masks) are
  unprotectable facts; implement from public documentation and the
  MIT-licensed Hyperion lineage, keeping an `ATTRIBUTION.md` mapping
  each translated concept to its source.
- Cache data never enters git: `.gitignore cache/`; docs point to the
  OpenRS2 community archive. Thin mode (§M3) is the default for all
  automated tests.
- Every vendored idea gets an SPDX header like IsaacCipher's.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Update-block protocol drift vs rev-181 clients | M6 isolated; gateway face unaffected; document exact revision target before M6 |
| Dual-realm feature drift (Python vs Java mechanics diverge) | combat/skill formulas mirrored by construction + cross-realm conformance test added in M5 |
| Cache availability for contributors | thin mode default; cache optional at boot |
| Scope creep toward full MMO | milestone exits are hard gates; non-goals list is binding |

## 9. Order of play

M0 → M1 → M2 → M3 → M4 → M5 → M6. Total estimate: **10-13 focused
days**, with a playable-by-Bifrost realm landing at M5 (~day 10).
