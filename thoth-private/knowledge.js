// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH knowledge contributions merged through the sanctioned seam in
 * core/knowledge.js. Entries use the same { title, reply, actions? } shape
 * as the hand-written product knowledge; rules route phrasing to them.
 */
export const knowledge = {
  entries: {
    thoth: {
      title: 'THOTH operator console',
      reply:
        'THOTH is the private local operator kernel attached to this installation. It can inspect status, run doctor checks, manage memories, backups, scratchpad, focus sessions, and widgets - all on this PC. Read-only commands are always available; workspace-mutating commands need a standing grant from the administrator panel; destructive commands (restore, forget, reset) only run inside an authorized administrator session. Say "thoth help" for the full command list. THOTH is software, not a consciousness claim.',
    },
    thothGrants: {
      title: 'THOTH grants',
      reply:
        'THOTH tools are classed at the process boundary: L0 read-only runs freely, L1 needs a standing grant ("thoth grant <tool> L1" from the administrator panel), and L2 elevated tools are never granted - they require an authorized administrator session for every call. Revoke any standing grant at any time; grants live in your local profile and nothing is sent anywhere.',
    },
    thothDesign: {
      title: 'THOTH continuous design loop',
      reply:
        'THOTH keeps the architecture honest on three cadences: every push runs scripts/design-scan.mjs in CI, a 6-hour scheduled workflow re-runs it, and locally "thoth watch on" audits every 30 minutes into your profile. It tracks import cycles, registry-seam violations, environment-variable drift against AGENTS.md, missing license headers, and oversized hotspot files. "thoth next" turns findings into a severity-ranked plan; goal documents (AGENTS.md, both roadmaps) anchor every judgment. All analysis is local.',
    },
    thothSafety: {
      title: 'THOTH autonomy guardrails',
      reply:
        'THOTH acts autonomously only inside hard rails: before restore or reset it takes an automatic safety backup (throttled to one per five minutes) and refuses to proceed if that backup fails; watch-mode audits never transmit anything; destructive tools stay L2 admin-per-call forever; and the master switch freezes everything except an administrator resume. Autonomy means diligence, not initiative outside scope.',
    },
    thothTools: {
      title: 'THOTH toolbox',
      reply:
        'Beyond status and doctor, THOTH operates your workspace: remember/forget memory edits, scratchpad capture, focus sessions, backups and restores, mood mixes, widget pinning, palette lookups, last-reply explanations, repo git posture (branch/status/log, read-only), fleet rollup with incident memory and self-learning, the continuous design loop, compliance scanning, and the proposal lane. Say "thoth help <tool>" for exact usage; classes tell you what needs a grant or an administrator.',
    },
    thothAiBridge: {
      title: 'Local model bridge',
      reply:
        'THOTH can see your local model bridge on loopback: "thoth ai" lists installed models and "thoth ai loaded" shows what is in memory right now. This is read-only visibility over the same service that powers Soul conversations - model weights and prompts never leave this PC.',
    },
    thothTrends: {
      title: 'Design trends and regressions',
      reply:
        '"thoth trends" charts finding totals across watch ticks with best-ever tracking, and "thoth regress" compares the last audit against the previous one by category. The watch loop adapts its cadence to trouble - faster polling while findings are high, quieter once things calm down - and announces regressions the moment high-severity findings appear.',
    },
    thothCode: {
      title: 'Advanced codebase knowledge',
      reply:
        'THOTH indexes this repository live: "thoth code explain <file>" reports zone, size, exports and whether the file is startup-frozen; "thoth code find <symbol>" locates exports across first-party modules; "thoth code conventions" summarizes the AGENTS.md contract. Proposals cite these facts - THOTH never invents repository structure.',
    },
    thothAdmin: {
      title: 'Session-scoped elevation',
      reply:
        'Administrators can arm session-scoped elevation so elevated operations run without per-call confirmation - but arming requires an active administrator authorization, every elevated run takes an automatic safety backup first, each use is persisted and relay-audited, and the mode dies with the admin session. Outside that window nothing changes: destructive tools stay refused.',
    },
    thothFleet: {
      title: 'Fleet federation and incident memory',
      reply:
        '"thoth fleet" rolls up every sibling system this kernel can see (MIND-managed, git-bearing, node) with network posture and attention flags - read-only, bounded to 24 systems, all local. "thoth incidents" correlates only what needs action, most urgent first, and persists each condition as a stable-id ledger entry that stays open across sweeps, auto-closes when a sweep comes back clean, and banks MTTR minutes on close. "thoth incidents --all" adds resolved history with median/worst MTTR so reliability becomes a measured metric instead of tribal memory.',
    },
    thothCreative: {
      title: 'Proposal lane',
      reply:
        'THOTH can propose autonomously through "thoth ideate" (severity-ranked ideas grounded in live audits and goal documents), "thoth changelog" (drafts from actual git history), and accessible theme palettes - while every application of a proposal stays behind an explicit human gate. Generators synthesize only local, verifiable inputs; nothing is invented beyond what the repository shows. "thoth creations" lists what the proposal lane has produced.',
    },
    thothCompliance: {
      title: 'Compliance scanning',
      reply:
        '"thoth compliance" scans this repository against standing standards: supply-chain integrity, privacy egress, CSP posture, accessibility, and safety copy. Findings are severity-ranked with file citations, and "thoth comply-fix" applies only the mechanical subset - anything judgment-shaped is reported for a human. The scanner reads your tree; it never phones home.',
    },
    thothLearn: {
      title: 'Self-learning loop',
      reply:
        'THOTH learns automatically from what its sweeps already see: every incidents/fleet sweep and audit tick reconciles durable facts into a local ledger - which systems run fragile, which finding categories have gone chronic, your median fleet MTTR, and the tools you rely on most. Each fact carries an evidence count; observed facts expire after about two weeks of silence. You can add permanent knowledge with "thoth teach <fact>", review everything with "thoth learn", or remove taught facts with "thoth unteach <text>". All of it stays in .operator/ on this PC.',
    },
    thothWisdom: {
      title: 'Operational wisdom and guided remediation',
      reply:
        'THOTH carries an advanced knowledge layer: a workspace topology map ("thoth topology" - supervised systems, integration seams, verified environment facts like the local model endpoint and sync directions), incident playbooks matched by signature, and an escalation policy that fixes what automation may do per severity. When incidents fire, the sweep names the matching playbooks, and "thoth advise" prints diagnosis plus step-by-step remediation marked [auto-ok], [L0]/[L1], or [human]. "thoth advise --apply" executes only the first step your standing grants allow - one action per call, never chaining mutations, never touching elevated or human-gated steps. Standing L1 is live on every grantable tool, so nearly everything runs promptless; restore and reset alone stay administrator-proven per call. Automation depth equals your grants; judgment stays with you.',
    },
    thothAuto: {
      title: 'Autonomic loop',
      reply:
        '"thoth auto on" starts the autonomic heartbeat: every 15 minutes (configurable 5-240) it sweeps the fleet, reconciles incident memory, refreshes learned facts, matches playbooks, and applies at most ONE action your standing grants already permit - then reports through the console feed. "thoth auto tick" runs one cycle on demand; "thoth auto off" stops it; the master switch pauses everything exactly as with manual commands. It never chains actions across ticks into a plan you have not seen, never touches elevated tools, and every decision lands in your local profile.',
    },
    thothRepair: {
      title: 'Automatic code repair and unfinished-code wiring',
      reply:
        'THOTH scans first-party code for unfinished markers (TODO/FIXME/not-implemented) and missing license headers ("thoth repair", read-only), and reports a wiring checklist separating what automation may fix from what needs your decision ("thoth wire"). "thoth repair-fix" applies only deterministic repairs - Prettier with the repository config and SPDX header insertion - and syntax-verifies every rewritten file, restoring any that fail before they ever reach git. Because it writes source files it is elevated (L2): run it from an administrator session or with session elevation armed. Implementing stubbed logic and wiring new features into startup-frozen surfaces stay human-only by contract.',
    },
    thothScaffold: {
      title: 'Feature scaffolding',
      reply:
        '"thoth scaffold <id> [title]" plans a brand-new feature against the registry contract - descriptor, knowledge entry, fail-closed contract test, and a guarded dynamic-import seam in feature-registry.js. Add --write inside an administrator session to generate, wire, and verify for real: every generated file is syntax-checked and the generated contract test is executed before success is reported. Global answer-surface merging of new feature knowledge stays a one-line human seam in core/knowledge.js by design.',
    },
    thothScribe: {
      title: 'Auto Scribe documentation service',
      reply:
        '"Auto Scribe" is THOTH\'s automated documentation service, covering every system the fleet sweep can see - apps, repositories, and the website docs. "thoth scribe" (read-only) inventories all first-party Markdown and audits it against machine-checked facts: unknown "thoth <command>" references and broken relative document links. "thoth scribe-write" (needs an L1 standing grant) performs the full document rewrite: it regenerates .operator/auto-scribe/<system>.md digests plus a _fleet.md index purely from verified facts - identity, scripts, documents, network posture, topology roles, and the live command registry - and applies exactly one mechanical fix class: relinking a broken link when a unique same-basename target exists. Prose is never improvised; historical version mentions stay untouched. The autonomic loop spends idle ticks on scribe-write while its grant is live.',
    },
    thothEngineDoctrine: {
      title: 'RSPS engine doctrine (RuneSource / Hyperion)',
      reply:
        'Our RSPS engine follows the distilled laws of RuneSource and Hyperion, recorded in osrs-llm-agent/knowledge/engine_principles.md with citations: single-writer mutable state serialized on the server lock, parallelism reserved for read-only work, cached per-tick state blocks, bounded queues everywhere, a slow-handler watchdog, atomic off-hot-path saves, and simplicity as the performance feature. Applied 2026-08: chat/presence/channel mutations hardened under the single-writer lock, chat feed bounded, watchdog added. Engine PRs that violate these rules are rejected citing that file.',
    },
    thothCompanionDoctrine: {
      title: 'Companion doctrine (Mate-Engine)',
      reply:
        "Eidovara's companion layer follows lessons distilled from Mate-Engine in docs/COMPANION_DOCTRINE.md: resource budgets track the asset (companion looks are capped at 8 MiB / 4096 px and refused with a fallback if oversized), smooth presence respects the reduced-motion preset, chat runs local-first through the loopback model provider with offline fallback, extension goes through the single feature-registry seam, and every bundled asset carries a license notice. Deliberately not adopted: a full VRM pipeline, multi-avatar sync, Discord Rich Presence, and paid exclusives - each documented with reasons.",
    },
    thothAdultWellness: {
      title: 'Adult wellness and control',
      reply:
        'Adult capability ships with matched controls: Private session mode suppresses taste-record writes at the main-process choke point while on; a configurable session limit reports elapsed minutes and remaining headroom through "thoth adult"; and Ctrl+Shift+X is an instant panic exit that pauses media, closes the adult session, and returns to the dashboard. All of it stays local, revocable, and behind the existing triple gate.',
    },
  },
  rules: [
    // Specific lanes first; the bare "thoth" catch-all stays last so a
    // phrase like "thoth fleet" routes to its lane, not this generic card.
    {
      id: 'thothGrants',
      re: /\b(thoth\s+(?:grant|grants|permission|permissions|classes?)|L[012]\s+(?:grant|class|tool))\b/i,
    },
    {
      id: 'thothDesign',
      re: /\b(design\s+(?:loop|audit|scan|watch)|architecture\s+(?:scan|audit)|continuous\s+design)\b/i,
    },
    {
      id: 'thothSafety',
      re: /\b(safety\s+backup|autonomy|guardrails?|auto(?:matic)?\s+backup)\b/i,
    },
    {
      id: 'thothTools',
      re: /\b(toolbox|what\s+can\s+thoth\s+do|thoth\s+(?:commands?|tools?))\b/i,
    },
    {
      id: 'thothAiBridge',
      re: /\b(thoth\s+(?:ai|models?|bridge)|local\s+model\s+bridge|ollama\s+(?:models?|status))\b/i,
    },
    {
      id: 'thothTrends',
      re: /\b(design\s+trends?|finding\s+history|architecture\s+regress(?:ion)?)\b/i,
    },
    {
      id: 'thothCode',
      re: /\b(thoth\s+code|code\s+(?:explain|find)|conventions)\b/i,
    },
    {
      id: 'thothAdultWellness',
      re: /\b(adult\s+(?:wellness|private|session\s+limit|panic)|private\s+session\s+mode)\b/i,
    },
    {
      id: 'thothAdmin',
      re: /\b(session[- ]scoped|admin\s+mode|elevation\s+mode|break[- ]glass)\b/i,
    },
    {
      id: 'thothFleet',
      re: /\b(fleet|incident[sz]?|mttr|mean\s+time|sibling\s+systems?|cross[- ]system)\b/i,
    },
    {
      id: 'thothCreative',
      re: /\b(ideate|proposals?|idea\s+list|changelog\s+draft|creations?|theme\s+palette)\b/i,
    },
    {
      id: 'thothCompliance',
      re: /\b(compliance|comply[- ]fix|standards?\s+scan|supply[- ]chain\s+scan|privacy\s+egress)\b/i,
    },
    {
      id: 'thothLearn',
      re: /\b(self[- ]learn|thoth\s+(?:learn|teach|unteach)|teach(?:ing)?\s+thoth|what\s+(?:have\s+you\s+)?learned)\b/i,
    },
    {
      id: 'thothWisdom',
      re: /\b(playbooks?|advise|remediation|topology|escalation|runbooks?|guided\s+fix)\b/i,
    },
    {
      id: 'thothAuto',
      re: /\b(autonomic|self[- ]driving|auto(?:matic)?\s+(?:mode|loop|pilot|tick)|thoth\s+auto)\b/i,
    },
    {
      id: 'thothRepair',
      re: /\b(auto[- ]fix|self[- ]heal|repair|unfinished|stub[s]?|missing\s+headers?)\b/i,
    },
    {
      id: 'thothScaffold',
      re: /\b(scaffold(ing)?|generate\s+a\s+feature|new\s+feature\s+wire)\b/i,
    },
    {
      id: 'thothScribe',
      re: /\b(auto[\s-]?scribe|scribe(?:-write)?|document(?:ation)?\s+(?:rewrite|regenerat\w*|drift|service)|(?:docs?|documents?|markdown)\s+(?:rewrit\w+|regenerat\w+|drift))\b/i,
    },
    {
      id: 'thothEngineDoctrine',
      re: /\b(runesource|hyperion|317|engine\s+(?:doctrine|principles?|laws?)|tick\s+budget)\b/i,
    },
    {
      id: 'thothCompanionDoctrine',
      re: /\b(mate[- ]?engine|desktop\s+mate|vrm|companion\s+(?:doctrine|engine|(?:\w+\s+){0,2}budget)|texture\s+(?:size|budget))\b/i,
    },
    {
      id: 'thoth',
      re: /\b(thoth|operator\s+console|operator\s+kernel)\b/i,
    },
  ],
};
