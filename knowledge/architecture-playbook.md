# Architecture Playbook

Proven patterns for building systems in this workspace. Each pattern
links to the lessons database (`lessons.json`) and to living code that
embodies it.

## 1. One authority, one surface (L001, L018)

Every product is an authoritative process owning all mutable state.
Clients speak a line protocol of intents and receive `{error, result}`
always. All access funnels through a single SDK class - the only API
agents, humans and tests see. Cross-entity mutation serializes on one
lock; parallelism is read-only. Cached per-tick state snapshots give
readers lock-free views.

**Build order:** content/data module -> mechanics -> SDK verbs ->
wire server -> verifier checks.

## 2. Data lives once (L002)

A `content` module per engine holds every tunable number. Mechanics
import it; nothing re-declares. Schemas reference it; validators never
re-state values.

## 3. Registries over constants (L003)

Component endpoints (ports, paths, kinds) live in `realms/registry.json`.
Lookup helpers fall back to caller defaults so missing entries degrade
instead of crashing.

## 4. Organs talk through the post office (L004)

Cross-process events ride `ratatosk`: per-organ inboxes of atomic JSON
letters, append-only broadcast topics with consumer cursors, heartbeat
files for liveness. Two-line integration per organ:

```python
from ratatosk import publish, beat   # both never raise
publish("incidents", {...}, frm="myorgan", kind="gate")
beat("myorgan", note="9/9 gates")
```

## 5. Defense in depth around every moving part (L007, L008, L009)

- Circuit breakers trip after N consecutive subsystem failures,
  cool down, half-open retry.
- Periodic organs run on beat multiples with latency SLOs;
  breaches quarantine then auto-revive; vitals are queryable.
- Remediation quarantines artifacts, never destroys; ledgers record
  everything; judgment calls escalate to humans.

## 6. Prove integrity cryptographically (L011, L012)

Hash-chained audit logs make silent edits detectable at named
positions. Sealed manifests (SHA-256 file map + HMAC signature) gain
tamper-evidence from an independent anchor file holding the manifest
hash. Structural fingerprints catch rebranded copies of your own code.

## 7. Validate at the door (L010, L006)

All persisted documents pass schema gates on load: wrong types/versions
hard-fail with precise messages; unknown keys warn (forward-compat);
missing keys take load-side defaults; version field bumps on change.
Files covered by checksums are written atomically in binary or
newline-pinned text.

## 8. Make behavior replayable (L015, L016)

Inject clock + RNG behind one duck-typed object. Journal mutating verbs
with tick/actor/digest/deltas. State digest over canonical save proves
twin sessions identical. Attestation = replay with provenance.

## 9. Bound autonomy (L013, L017)

Code-generating agents get: SDK-only surfaces, capability profiles
checked per verb, witness journals, loop state persistence for resume,
and scoring signals. Denials cite the right needed.

## 10. Watch generically, protect specifically (L022)

Process supervision (liveness, runaway CPU, port squats) is generic and
reusable; domain protection (baselines, seals, policy) encodes product
doctrine. Both publish to shared bus topics.
