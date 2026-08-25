# Release readiness — full studio release, V3 STABLE (fully free)

Cycle: 2026-08-24 ~11:30 local (ATHENA ad-hoc, "prepare a full studio release
across the board, fully free V3 STABLE"). Companion to cycle log
`2026-08-24-1112.md` (formal release refusal on red CI) and
`docs/plans/heart-roadmap.md`. This file is the single checklist to drive once
blockers clear. Evidence cited inline; `[UNVERIFIED]` marks what must be
re-checked at execution time.

## 1. What "V3 STABLE" means here (interpretation, operator to confirm)

Two coherent readings of the request; both share one execution spine.

| | Option A — fleet-wide v3 line | Option B — Eidovara v3 headline |
|---|---|---|
| Meaning | Root olympos `VERSION` jumps 1.13.0 -> 3.0.0 and every satellite re-aligns | Eidovara cuts v3.0.0 STABLE packaging the THOTH v3.x autonomic era; fleet continues its own 1.x line (next stop 1.14.0) |
| Effort | High: 4+ repos' version surfaces move together | Low-moderate: one repo's release machinery (already tag-driven) |
| Blast radius | Large — every gate/doc referencing version lines | Contained — `auto-sync-facts` workflow enforces consistency inside project---soul |
| Reversibility | Poor (many surfaces) | Good (tag delete + worker redeploy + fact-sync revert) |
| Fit to evidence | Weak: no doc plans a unified v3 | Strong: CHANGELOG Unreleased is dominated by THOTH v2.8->v3.3.0 ("Autonomic Operator"); thoth-private README declares "Autonomic loop (v3.0.0+)"; product README still says "Stable Alpha" |

**Recommendation: Option B.** Ties break toward reversibility; the THOTH v3
milestone gives "V3" an honest referent, and "across the board" is satisfied by
the release-facts sync that propagates one canonical version through every
advertised surface (package.json, docs/knowledge.js, server/worker.js,
ip-certification.json, CITATION.cff, site). Option A remains available as a
follow-up decision row if the operator truly wants the internal fleet line at 3.

"Fully free" = current product truth ("full free Alpha. No live checkout,
subscription, payment processing, or paid entitlement") carried into v3:
commerce lane P3 stays CLOSED, no new paid dependency may enter the dependency
graph this release.

## 2. Blockers (ordered; each cites evidence)

1. **Fleet main CI red — hard stop.** `ecosystem` failed 7+ consecutive runs on
   the `daedalus` gate (~125s, deterministic-in-CI, green standalone). Fix path
   already minted: lesson L030 "Failure output is part of the gate"
   (`safeguards/gate.py` keeps a 3-line tail that hides the real `[FAIL]`);
   PR from `auto/athena` carrying L030 was open at cycle time. No tag until a
   full green sweep on main (FLOW rule 6; guarantee #5).
2. **Gate-output repair lands before any release tag** (subset of #1, listed
   separately because it changes future diagnostics): merge the gate.py
   retention fix so the next red is readable.
3. **Poseidon auto-merge fires while checks are pending/failing** (observed on
   PR #45). Until the operator sets policy, treat every post-auto-merge main
   commit as UNVERIFIED until its push-run completes green.
4. **Dual writer lanes with disjoint lock scopes on project---soul**:
   `eidovara/` clone (role=writer, lane=opencode-main, default per-.git lock)
   and `project---soul/` clone (role=writer, lane=temp-writer,
   lockDir=`C:\Users\Earth949\.eidovara-lane`). Two writers can race the same
   remote because their leases don't contend. Demote `temp-writer` to mirror or
   point both at one lockDir before tagging.
5. **heart/ still undeclared** (L029's exact warning): port 4767 has no
   registry row, npm test surface aggregated by nothing. H0 sign-off pending.
   Not strictly blocking an Eidovara tag; blocking for "across the board"
   health claims about the studio suite.
6. **Untracked top-level dirs** `gamedev/`, `godot-knowledge-db/`: declare
   (registry/doc-table/gate per L029) or relocate out of the repo root. They
   currently sit outside every truth boundary.
7. **Staged trio already covered**: hermod import-light + hypnos gate wiring +
   safeguards patch-lane rewrite are PR #43 (`auto/hermes-feed`) — do not
   double-commit them locally; land via that PR.

## 3. Promotion checklist (execute in order; all boxes must be checked)

### Phase F — fleet green (owner: safeguards/daedalus lanes + hermes)

- [ ] L030 gate.py output-retention fix merged; `daedalus` gate identity visible on any failure
- [ ] `daedalus` flake fixed or isolated (retry-heal is not a fix); root cause recorded as lesson if environmental
- [ ] Fresh push to main shows full ecosystem job GREEN end-to-end (`gh run list --repo ProjectSoulbyTmb/olympos`)
- [ ] PR #43 (hermod feed pipeline) merged green
- [ ] PR #44 (knowledge library gate joins ecosystem job) merged or explicitly deferred by operator
- [ ] `python doctor.py --ci` locally green on post-merge main (20/20 expected)

### Phase S — studio hygiene (owner: DAEDELUS lane / hermes)

- [ ] Writer-lane conflict resolved (blocker #4): one writer lease holder on project---soul
- [ ] `git -C eidovara status --porcelain` empty; synced with origin/main (0 ahead/behind)
- [ ] Decide Unreleased scope: confirm THOTH v3.x companion-doctrine/knowledge-seam items are the v3 payload; anything half-done moves back behind a feature seam
- [ ] "STABLE" label justification written down (what changed since "Stable Alpha"; honest compatibility statement) — operator sign-off required; truth boundaries forbid vibes-based claims
- [ ] 18+ gate statement unchanged; "fully free" wording kept; P3 commerce lane untouched

### Phase R — Eidovara v3.0.0 release (owner: DAEDELUS/hermes, per AGENTS.md + DAEDELUS.md §3)

- [ ] `node scripts/session-guard.cjs claim` in the writer clone; `EIDOVARA_SESSION=<name>`
- [ ] `npm run doctor` clean
- [ ] `npm run lint`; `npm run check`; `npm test` — zero failures, zero ratchet
- [ ] Bump canonical version: `src/core/release.js` -> 3.0.0
- [ ] `node scripts/sync-release-facts.mjs` — package.json/docs/worker/citation restated exactly; consistency tests green
- [ ] CHANGELOG "Unreleased" retitled `## v3.0.0 - <date>` with measured-facts placeholders marked as such until Phase R measurement
- [ ] Land via reviewed push to main (pre-push runs full gates)
- [ ] `git tag v3.0.0 ; git push origin v3.0.0` -> `release-windows.yml` builds NSIS + portable, attaches artifacts + evidence
- [ ] Paste measured values from release assets `LIVE-INSTALLER-FACTS.json` into `src/core/release.js`; re-run `sync-release-facts.mjs`; commit + push (never advertise an unmeasured digest)
- [ ] `npm run workers:deploy` so api.eidovara.org reports the new digests
- [ ] Verify: `Invoke-RestMethod https://api.eidovara.org/v1/config` shows 3.0.0 + installer digest; `curl.exe -sSL https://eidovara.org/download` still enforces the 18+ gate; GitHub Pages/Cloudflare Pages redeployed

### Phase V — across-the-board statements (owner: ATHENA authorship, human sign-off)

- [ ] DESIGN.md decision-log row: release decision + version-alignment choice (A/B) recorded
- [ ] Fleet side note only (Option B): root VERSION stays 1.13.0 until its own green sweep justifies 1.14.0; cross-link release notes
- [ ] heart/, gamedev/, godot-knowledge-db/ declarations tracked as follow-up issues (not silently dropped)

## 4. Rollback paths

| Step | Rollback |
|---|---|
| Tag pushed, downloads low | Delete tag + release assets; worker still serves prior facts until redeploy |
| Facts synced, worker deployed | `workers:deploy` of previous revision; revert fact-sync commit (byte-exact, derived files only) |
| Site pages wrong | Pages workflows redeploy from `main`; revert the docs commit |
| Fleet-side gate change regretted | Revert commit restores prior gate behavior; incidents ledger records the window |

## 5. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| daedalus CI flake returns post-fix | Medium | L030 makes failures readable; isolate via retry-pattern lesson L-series; keep gate timeout headroom |
| Auto-merge stamps unhealthy main again | Medium | Operator policy on Poseidon (blocker #3); until then, verify post-merge push runs manually |
| Dual-writer race corrupts release clone | Low-Medium | Single lease before any write (Phase S); hooks block foreign live locks |
| "STABLE" overclaim violates truth boundaries | Medium | Written justification + operator sign-off (Phase S); keep compatibility notes explicit |
| Unmeasured digest advertised | Low | Runbook step order enforced; sync-release-facts tests fail drift |
| Paid dependency sneaks into v3 | Low | Dependency-review workflow (fail-on-severity: moderate) + manual diff review of package.json in release PR |

## 6. Open operator decisions

1. Confirm Option B (Eidovara v3.0.0 headline; fleet line unchanged).
2. Poseidon auto-merge policy: wait-for-green vs fast-lane (guarantee #5 tension).
3. "STABLE" label sign-off after reading the justification drafted in Phase S.
4. Disposition of `gamedev/`, `godot-knowledge-db/`, `heart/` declarations.
5. Whether PR #44 ships inside this release window or after.
