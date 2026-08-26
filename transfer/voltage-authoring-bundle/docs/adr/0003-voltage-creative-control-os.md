# ADR-0003: VOLTAGE is the Studio Creative Control OS

| | |
|---|---|
| **Status** | Accepted (operator approval, session 2026-08-25: "approve") |
| **Date** | 2026-08-25 |
| **Author** | DAEDALUS workshop cycle (test-launch muster) |
| **Scope** | Extends ADR-0002; new blueprint `daedalus/blueprint_apollo.py`; paper contracts under `docs/` |
| **Supersedes** | Nothing; narrows ADR-0002's purpose statement into a product |

## Context

ADR-0002 committed VOLTAGE as a private sovereign OS at `D:\VOLTAGE`
without fixing its product definition. Operator direction this session:
the product **is** a command-based creative control OS - one shell over
fleet operations, creative studios, learning, and entertainment;
enterprise-grade on one seat; existing organs wired, none reinvented.
DAEDALUS commissions every component through its blueprint pipeline.

## Decision

1. **Name and shape.** The command plane is **APOLLO**: grammar,
   sessions, rights law, dispatch, witness, seals. First artifact is
   blueprint `apollo-os`, proven offline in any weave directory.
2. **The law is one table.** Verb -> grant class lives only in
   `apollo_rights_map` (`VERBS`); grammar domains derive from it; the
   `/catalog` endpoint emits it; docs reference it and never copy it.
   Profiles: guest=L0, editor=L1, admin=L2; ladder checked at dispatch,
   server-side, before execution.
3. **Test-launch honesty rule.** Builtins (`fleet status`, `know
   search`, `demo note`) are labeled doubles so the plane is provable
   with zero other organs present; organ-backed verbs answer
   `organ-not-wired (test-build)` AFTER passing the ladder - refusal
   reasons never impersonate capability.
4. **Attestation chain per command.** Seeded digest -> witness line ->
   transcript -> session seal (sha256); one flipped byte breaks the
   seal (proven by gate tamper probe).
5. **Port block.** 44100-44199 reserved; offset rule 439NN->441NN for
   seeded realms; apollo=:44120, riley-engine=:44128, kinema-host
   =:44130, ComfyUI tier=:44181 (ratification pending with ADR-0002's
   open item #3).
6. **Acceptance matrix B1-B10** adopted as the VOLTAGE release bar
   (see `docs/contracts/voltage-command-spec-v1.md` section 6).

## Constraints honored

- Stdlib-only; envelope `error` field via single choke point; loopback
  binds only; quarantine-over-destroy preserved in ops semantics.
- Faults are independent breakers; all four proven to bite (muster
  evidence 2026-08-25).
- Olympos-side scope guards untouched; test launches never touch
  `D:\VOLTAGE`.

## Consequences

- Batch V6 commissioning can proceed at the VOLTAGE root once ADR-0002
  W0/V2 open; until then `tools/voltage_export.py` stays dry-run.
- Studio adapters (video/image/media/game/entertain) swap builtin
  doubles without touching the law table or dispatch order.
- One orphan risk class eliminated by construction: woven gates carry
  bounded readline watchdogs; runners carry tree-kill fallbacks.

## Evidence at acceptance time

```
python tools/muster_launch.py                      -> GATE GREEN (clean)
python tools/muster_launch.py --fault silent_start -> BREAKER CONFIRMED
python tools/muster_launch.py --fault error_stripped -> BREAKER CONFIRMED
python tools/muster_launch.py --fault no_ladder    -> BREAKER CONFIRMED
python tools/muster_launch.py --fault unwitnessed  -> BREAKER CONFIRMED
python daedalus/verify_daedalus.py                 -> green (regression)
```
