# ATHENA validation record - learning proposal queue 2026-08-26

- Validator: @athena (planning kernel), bounded pass, read-only except this file.
- Scope: all 12 proposals in `knowledge/proposals/` (metis x5, argus x4, logia x3),
  validated per fleet-learning stage "ATHENA validates (dedupe vs vault, evidence spot-check)".
- Vault state at validation: L001-L045, `next_id: L046` (`python -m learning status`: lessons=45, proposals=12).
- No proposal files were edited, deleted, or renamed. `knowledge/lessons.json` untouched.
- Cross-reference: `docs/plans/learning/2026-08-26-advanced-code-inventory.md` sec 5 used as
  corroborating evidence only (its items are explicitly not proposals until staged).

## Verdict table

| # | Proposal file | By | Verdict | Evidence check (per citation) | Dedupe finding | One-line reason |
|---|---|---|---|---|---|---|
| 1 | L046-verify-claimed-ports-by-process-identity | metis | **ACCEPT** | soak-baseline.md:164 PASS; 2026-08-24-1138.md:13 PASS (both direct hits) | New; extends L022/L029/L037 family (port squatting named but no verification rule existed) | Process-identity port ownership is a genuine security rule; both incidents cited verbatim on disk |
| 2 | L046-unlock-construction-waves-only-on-provab | logia | **AMEND** | 0052.md:61 PASS; volt-comm.md:38 **FAIL** (blank line; content at :44-45); thoth-metal-w0.md:78 PASS-with-note (right block, bullets :80-82); full-comm-phase0.md:26 PASS | New; complements playbook pattern 9, no vault overlap | Rule is sound and corroborated x4, but one anchor points at an empty line - fix evidence ref to volt-comm.md:44-45; optionally replace meta-tags "pattern"/"synthesis" with topical tags (process, gates, sequencing) |
| 3 | L046-reconcile-monotonic-identifiers-against- | metis | **AMEND** | 0052.md:21 PASS (direct); volt-comm.md:60 **FAIL** (boundary-drift text; ADR duplication actually at :64-67); lessons.json:440 PASS-with-note (opening brace of the L035 object whose content differs from what 0200 planned) | New; extends L026 (sequence identity) + L033 (multi-home divergence); not a duplicate | Identifier-allocation race is real (L034 collision documented in two cycles), but volt-comm anchor misses - fix to volt-comm.md:64-67 |
| 4 | L046-pin-interpreters-by-absolute-path-in-gat | metis | **ACCEPT** | 0200.md:39 PASS (direct); 0200.md:75 PASS-with-note (mint directive is adjacent lines :73-74, same block) | New; codifies existing sentinel.py discipline (`PY = sys.executable`); watchdog.ps1:18-19 hardcode confirms need | Lost-mint story verified end-to-end (0200:73 queued it as L035; vault L035 is unrelated content); oldest unpaid reliability debt |
| 5 | L046-integration-md-sec6-updates-row-missing- | argus | **AMEND** | bus.py:137 PASS (exact); planning.py:167 PASS (exact); envelope.py:58 PASS (exact); INTEGRATION.md:231 PASS (updates row lacks fleet.plan) | New rule; extends L042 (document-on-arrival) to wire-kind catalogue rows | Finding + all citations solid, but paste-ready fix mis-files fleet.plan under *updates* when envelope.py catalogues it under topic *daedalus* and INTEGRATION has an "As-built lanes" section right after - re-target fix before promotion |
| 6 | L046-integration-md-sec2-registry-count-28-32 | argus | **REJECT** | INTEGRATION.md:70 PASS (verbatim "28 members"); registry count=32 PASS (programmatic); registry.json:360 PASS (persephone `"tier": 2` exact) | Near-duplicate of L041 (re-derive stale doc facts from disk, date-stamp) with NO new imperative | Correction-not-lesson: counts/tier-grouping are just L041's rule applied; execute the two paste-ready doc fixes via argus correction backlog instead of the vault |
| 7 | L046-finders-report-and-route-detection-lanes | logia | **AMEND** | soak-baseline.md:9 PASS; h0a.md:49 PASS; volt-comm.md:45 **FAIL** (soak-clock tail; routing header at :51); full-comm-phase0.md:34 PASS; thoth-metal-w0.md:72 PASS | New; correctly distinguished from L009/rule 23 by its own rationale (assigns WHO repairs vs WHAT may be touched) | Detector-independence rule is real with >=4 corroborations, but volt-comm anchor misses - fix to volt-comm.md:51-58 |
| 8 | L046-design-md-night-entry-cites-apollo-kinem | argus | **ACCEPT** | DESIGN.md:311-312 PASS-with-note (entry spans ~:305-311, cited span inside same bullet); registry grep apollo\|kinema-host\|riley-engine = 0 hits PASS (reproduced); bus.py:108-137 command-plane grep zero-hits PASS (visually confirmed) | Write-side attribution rule distinct from L044 (read-side verify), L040 (codex organ markers), L041 (list expiry) | Ghost-truth entry confirmed absent from checkout twice over; lineage-naming imperative is a genuine delta |
| 9 | L046-automated-merges-wait-for-required-check | metis | **ACCEPT** | 1112.md:25 PASS (direct); 1146.md:46 PASS (direct, names both #45/#49 + remediation options) | New; git-hygiene family L027/L028/L031/L035 covers lanes/indexes/pushes but nothing gates merges on checks | Direct guarantee-5 protection with clean two-source provenance; strongest proposal in queue |
| 10 | L046-athena-codex-skill-md-sec2-self-contradi | argus | **ACCEPT** | SKILL.md:69 PASS (exact "21 realm"); SKILL.md:76 PASS (exact "32 members"); registry=32 PASS | Borderline-but-real extension of L041: adds single-value-per-fact invariant + self-contradiction as drift vector (doc-vs-itself, not doc-vs-disk) | Both contradiction halves verified verbatim; invariant is crisp and not stated anywhere in the vault |
| 11 | L046-amend-historical-records-only-by-dated-a | logia | **ACCEPT** | w0:53 PASS (direct dedupe bullet); 0052:48 PASS (direct bracket annotation); 0200:26 PASS (bullet carrying [now ADR-0007] annotation); 1300:3 PASS (Recovered-record disclosure verbatim) | New; human-facing amendment discipline deliberately distinct from L011 machine chains (rationale already draws the line) | Four independent corroborations, every citation direct; unlocks safe completion of the pending ADR-number cleanup |
| 12 | L046-a-clean-ledger-proves-nothing-unless-the | metis | **ACCEPT** | soak-baseline.md:61 PASS (AMBER GAP paragraph); :30 PASS (quiesce timestamp exact) | Extends L037 (null-verifier green is meaningless) from static admission to dynamic certification liveness; kin to L038 broken-instrument rule | Absence-of-writer vs absence-of-incidents is exactly the auto-arm hole found in today's soak baseline; time-critical for the ~2026-09-01 certification |

## Counts

**7 ACCEPT / 4 AMEND / 1 REJECT** (of 12).

Amendments required (exact):
- **P2**: evidence[1] `docs/plans/cycles/2026-08-25-volt-comm.md:38` -> `:44-45`. Optional: tags -> `["process","gates","sequencing"]`.
- **P3**: evidence[1] `docs/plans/cycles/2026-08-25-volt-comm.md:60` -> `:64-67`. Optional: sharpen evidence[2] to `knowledge/lessons.json:440-451`.
- **P5**: keep finding + citations; rewrite paste-ready fix to document `fleet.plan` where it actually rides (envelope TOPICS["daedalus"] / INTEGRATION as-built-lane section) instead of appending to the updates kinds list at INTEGRATION.md:231 - appending as proposed would create new drift. Optional: category `architecture` -> `process`.
- **P7**: evidence[2] `docs/plans/cycles/2026-08-25-volt-comm.md:45` -> `:51-58`. Same optional tag normalization as P2.

Rejection reason:
- **P6**: true content is two concrete doc corrections (INTEGRATION.md:70 count/tier prose). The generalizable rule behind them ("derive counts from registry.json at every revision, date-stamp") already exists as L041; no new imperative survives dedupe. The corrections themselves remain valid work - route to @argus correction backlog.

## Recommended next-L### allocation order (if operator approves all accepts+amends)

Vault next_id = L046. Ranked by guarantee risk first (replay/attestation/least-privilege/no-partial-reads/gated-health-claims), then urgency and reversibility:

| Slot | Proposal | Why this position |
|---|---|---|
| L046 | P9 automated-merges-wait | Direct guarantee-5 protection; cheapest behavioral rule |
| L047 | P12 clean-ledger liveness | Time-critical: soak auto-arm certifies ~2026-09-01 |
| L048 | P1 port process-identity | Open operator escalation (:43904 squatter suspect) needs its rule |
| L049 | P11 dated-annotation amendments | Unblocks pending ADR-number cleanup currently half-done |
| L050 | P3 identifier reconciliation | Active risk: this very batch allocates 11 ids - allocate only after confirming upstream sync (the lesson applies to itself) |
| L051 | P4 interpreter pinning | Oldest debt (lost mint of 2026-08-25); mechanical, reversible |
| L052 | P2 provably-green wave gating | Process sequencing complement to playbook 9 |
| L053 | P7 finders-report-and-route | Detector independence; pairs with P2's stop-on-red |
| L054 | P5 kind-catalogue-row-on-landing | Promote only after fix re-target per amendment above |
| L055 | P10 single-value facts | Doc-integrity invariant extending L041 |
| L056 | P8 lineage attribution in decision logs | Write-side sibling of L044 |

Rejected P6 leaves no gap: slots run L046-L056 contiguous.

## Systemic observations (subfleet output quality)

1. **One root cause produced all four failed anchors.** Every missed citation points into
   `2026-08-25-volt-comm.md`, whose head gained the 2026-08-26 Track A/B relabel note
   (lines 3-7) AFTER the subfleet staged proposals at 01:55:44 - a uniform +6-line shift
   invalidated metis/logia anchors while argus's code/doc anchors (immutable surfaces that
   day) all held. Recommendation for @logia: propose a rule that cycle-log citations carry
   a stable secondary anchor (section header + short quoted fragment) so post-staging edits
   cannot orphan them; validators should re-verify anchors at validation time regardless.
2. **Argus precision was excellent**: 16/16 argus citations landed exactly or within one
   line, and both programmatic claims (32-row count, 0-hit name greps) reproduced on demand.
3. **Genre confusion in the argus queue**: instance-specific doc fixes dressed as lessons.
   P6 was rejected on exactly this basis; P5/P8/P10 survived because their lesson bodies
   contain genuinely generalized rules. Consider splitting the pipeline formally:
   a correction backlog (paste-ready fixes, executed by repair lanes) vs the lesson vault
   (durable rules only).
4. **Logia corroboration bar met**: all three syntheses cite >= 4 independent cycles each;
   their rationales pre-draw the distinctions from nearest vault relatives (L009, L041,
   L011), which materially sped up validation.
5. **Cross-surveyor agreement is healthy**: inventory-doc section 5 independently
   corroborates the queue's fleet.plan catalogue finding, and holds ~23 further verified
   stubs/drift items awaiting future staging - the pipeline backlog is well-fed but the
   correction-vs-lesson split (obs. 3) matters more as it grows.

## Cycle footer

```
CYCLE: ad-hoc (validation pass, 02:33)
DECISIONS: 7 ACCEPT, 4 AMEND (exact amendments listed above), 1 REJECT (P6 near-dupe of L041,
corrections routed to argus backlog instead); allocation order L046-L056 recommended; no files
touched besides this record; lessons.json and proposal queue untouched pending operator yes/no.
OPEN QUESTIONS: (a) operator yes/no per proposal and per amendment; (b) who executes the two
P6 doc fixes and the P5 re-targeted fix - @argus correction backlog?; (c) does the operator want
@logia to formalize observation 1 (stable-anchor rule) as its own proposal?
NEXT ACTIONS: 1. operator: rule on the 11 promotions (+amendments); 2. @hermes/operator: apply
promotions sequentially per allocation order after upstream-vault sync check; 3. @argus: absorb
P6 corrections + P5 re-targeted fix into correction backlog; 4. @logia: consider stable-anchor
proposal next cycle; 5. subfleet generally: adopt secondary anchors for mutable-file citations.
```
