# Muster decisions - 2026-08-25

Operator gave full approval orders for execution of the muster report
(metis/argus/logia parallel cycle, 18:47-18:48). Decisions applied:

## Promoted to knowledge/lessons.json (append-only, sequential ids)

| New id | Proposal file (deleted on promotion) | By | Note |
|---|---|---|---|
| L036 | L036-registry-loaders-must-reject-or-coalesce + L036-registry-truth-33-rows-32-unique-names-i | metis+argus | MERGED - same duplicate-artemis defect; loader rule = lesson, count fix = codex edit |
| L037 | L036-refuse-realm-admissions-whose-verifier-i | metis | |
| L038 | L036-impossible-coverage-readings-mean-broken | metis | |
| L039 | L036-incident-records-need-structured-failure | metis | |
| L040 | L036-codex-heart-watchlist-is-stale-heart-tre | argus | |
| L041 | L036-integration-md-corrections-section-9-res | argus | corrections applied to INTEGRATION.md same day |
| L042 | L036-orphan-organs-haven-43910-sqlite-fts5-an | argus | haven/ares documented in DESIGN.md same day |
| L043 | L036-resolve-an-organ-s-current-home-before-w | logia | >=4 corroborations |
| L044 | L037-doc-sourced-claims-are-hypotheses-verify | logia | >=4 corroborations |
| L045 | L038-mirrors-converge-on-commit-audit-before- | logia | >=3 corroborations |

All proposals carried provisional id L036 (concurrent-staging collision,
known Vault.next_id gap); real ids assigned sequentially here at
promotion. Queue is now empty (healthy).

## Disk fixes executed

1. Duplicate artemis row deleted from realms/registry.json (was lines
   36-50, verbatim copy of 21-35). Registry now 32 unique members.
2. heart restore-vs-retire: NOT decided - restoration is not executable
   from this lineage anyway (repo-home policy L033 forbids cloning into
   OneDrive). Remains an open operator decision.
3. haven/ares adjudication: documented non-destructively in DESIGN.md
   with keep/retire marked open; retiring rows stays operator-owned.

## Codex corrections applied (dated)

- INTEGRATION.md: header no longer "pending restoration"; data-plane
  line cites declared ports instead of retired :43590/:43591; section 9
  still-missing list re-derived (all five items landed) per L041.
- DESIGN.md: ecosystem table rows added for Haven and Ares.
- .opencode/skills/athena-codex/SKILL.md: disk watchlist re-audited
  (heart absent both roots), ports section updated (:43910, aphrodite
  live), membership corrected 29 -> 32 with provenance.

## Open items handed back to operator

- ZEUS audit silence ~28h while token refreshed - confirm patrols.
- Doctor-green vs sentinel-red coverage divergence - confirm whether
  env healed or doctor scope misses what failed.
- wiring.md:26 claims "L036-L039 minted" vs vault ended at L034 -
  reconcile (superseded by this promotion for L036 onward).
- Provisional-id collision gap in Vault.next_id() - consider loader fix.

> Merge note 2026-08-25: ids shifted one slot at merge with main -
> main's #93 had already minted its own L035; our ten muster lessons
> were promoted here as L036-L045. Filenames above keep their original
> provisional-id prefixes.
