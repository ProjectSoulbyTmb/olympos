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
        'Beyond status and doctor, THOTH operates your workspace: remember/forget memory edits, scratchpad capture, focus sessions, backups and restores, mood mixes, widget pinning, palette lookups, last-reply explanations, repo git posture (branch/status/log, read-only), and the continuous design loop. Say "thoth help <tool>" for exact usage; classes tell you what needs a grant or an administrator.',
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
  },
  rules: [
    {
      id: 'thoth',
      re: /\b(thoth|operator\s+console|operator\s+kernel)\b/i,
    },
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
      id: 'thothAdmin',
      re: /\b(session[- ]scoped|admin\s+mode|elevation\s+mode|break[- ]glass)\b/i,
    },
  ],
};
