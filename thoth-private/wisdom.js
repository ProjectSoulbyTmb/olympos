// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH operational wisdom - the advanced knowledge layer.
 *
 * Structured, verified facts about THIS workspace's topology, incident
 * playbooks keyed by signature, and the escalation policy that decides what
 * automation may do on its own. Everything here was derived from the actual
 * tree and contracts (AGENTS.md, scripts/, CHANGELOG) - never invented - so
 * proposals and auto-remediation can cite real paths, commands, and gates.
 */

/** Verified environment facts. Each is checked against the live machine. */
export const FACTS = {
  soulProvider: {
    endpoint: 'http://127.0.0.1:11434',
    service: 'Ollama /api/chat',
    models: ['gemma3:4b', 'llama3.2:3b'],
    config: '%APPDATA%\\eidovara\\settings.json (safeStorage-encrypted)',
    note: 'provider=local; engine falls back to offline automatically if the service is down.',
  },
  canonicalSync: {
    source: '../thoth-private (canonical, untracked)',
    installed: 'src/features/thoth (gitignored, pulled at postinstall)',
    commands: 'npm run thoth:status | thoth:sync (pull) | thoth:push',
    direction:
      'edit canonical -> prettier with repo .prettierrc -> sync pull. Pulling without pushing local fixes first reverts them.',
  },
  writerLanes: {
    lock: 'node scripts/session-guard.cjs claim|status|release',
    lease: 'node scripts/lane.cjs init <name>|status --all|release',
    lockdir: 'eidovara.lockDir git config points all clones at one shared lane',
    rule: 'one writer lane per shared lockdir; mirrors are read-only by hook',
  },
  scheduledTasks: [
    'Eidovara VULCAN Auto (~30m guarded sweeps)',
    'EidovaraThothWatchdog',
    'Eidovara Git Bundle Backup',
  ],
  startupFrozen: [
    'src/electron/main.js',
    'src/renderer/index.html',
    'src/renderer/renderer.js',
    'src/electron/preload.cjs',
    'src/core/guards/index.js',
  ],
  qualityGates: ['npm run lint', 'npm test', 'npm run check', 'npm run format:check'],
  artifacts: {
    fleetLedger: '.operator/fleet_incidents.json',
    learnings: '.operator/thoth_learnings.json',
    toolUse: '.operator/thoth_tooluse.json',
    growthAudit: '.operator/growth_audit.jsonl',
    consentPolicy: 'standards/consent-policy.json',
  },
};

/** Workspace topology: systems THOTH supervises or integrates with. */
export const TOPOLOGY = [
  {
    name: 'project---soul',
    role: 'Eidovara desktop workspace (Electron/TS) - the supervised repo itself',
    seams: [
      'feature-registry self-registers src/features/thoth',
      'knowledge merge seam in core/knowledge.js',
    ],
    managed: true,
  },
  {
    name: 'thoth-private',
    role: 'THOTH canonical kernel source (this package)',
    seams: ['thoth-sync pull/push mirror', 'guard-invariants contract checks'],
    managed: true,
  },
  {
    name: 'MIND-managed siblings',
    role: 'systems exposing .mind_state.json + runs/net_report.json',
    seams: [
      'federation.js discovery',
      'venus-link drain accepts THOTH repair requests through consent gates',
    ],
    managed: true,
  },
  {
    name: 'VENUS assistant',
    role: 'desktop assistant kernel wired to Eidovara by a command pump',
    seams: ['THOTH <-> VENUS pump (core/thoth-bridge.js side)'],
    managed: false,
  },
  {
    name: 'eidovara.org + api.eidovara.org',
    role: 'public site (Cloudflare Pages serving docs/) and status/config Worker',
    seams: [
      '/health /v1/config /v1/status heartbeat after 18+',
      'GitHub Releases update checks with SHA-256 verify',
    ],
    managed: false,
  },
];

/**
 * Incident playbooks. match() runs against each incident's joined text
 * (system + items). Steps marked klass L0/L1 may be applied by advise
 * --apply when the matching standing grant exists; text-only steps are
 * guidance for a human.
 */
export const PLAYBOOKS = [
  {
    id: 'endpoint-down',
    match: /\b(endpoints?\s+down|github-api|network\s+automation)\b/i,
    title: 'Fleet endpoint down',
    diagnosis: 'Identify which endpoints fail and how fresh the report is before acting.',
    steps: [
      { text: 'Run "thoth net" for per-endpoint posture and report age.', klass: 'L0' },
      { text: 'Re-run "thoth fleet" after remediation to confirm recovery.', klass: 'L0' },
      {
        text: 'MIND-managed system: queue repair through the venus-link drain (consent-gated).',
        human: true,
      },
      {
        text: 'If the endpoint is a third-party API, verify its public status page yourself.',
        human: true,
      },
    ],
  },
  {
    id: 'offline-mode',
    match: /\boffline\s+mode\b/i,
    title: 'System in offline mode',
    diagnosis:
      'All network endpoints down on a MIND system: network automation defers, local-first work continues.',
    steps: [
      { text: 'Confirm with "thoth net" whether any endpoint recovered.', klass: 'L0' },
      { text: 'Do NOT retry network automation until healthy; keep sweeps local.', human: true },
      { text: 'Check the site status page from a browser once connectivity returns.', human: true },
    ],
  },
  {
    id: 'mind-stale',
    match: /\bmind\s+daemon\s+stale\b/i,
    title: 'MIND daemon stale (>30m)',
    diagnosis: 'The sibling patrol has not written state recently.',
    steps: [
      { text: 'Watch for auto-recovery across two sweeps via "thoth fleet".', klass: 'L0' },
      {
        text: 'Restart the MIND patrol from its own console - outside THOTH scope by design.',
        human: true,
      },
    ],
  },
  {
    id: 'ledger-lag',
    match: /\bledger|fleet_incidents|locked\b/i,
    title: 'Incident ledger write lag',
    diagnosis: 'Ledger writes are best-effort and atomic; locked filesystems lag one sweep.',
    steps: [
      {
        text: 'Ignore unless it persists across three sweeps, then inspect .operator/ manually.',
        klass: 'L0',
      },
    ],
  },
  {
    id: 'style-drift',
    match: /\b(format|prettier|lint|style)\b/i,
    title: 'CI style/format drift',
    diagnosis: 'Formatting debt blocks every gate (seen in practice 2026-08-23).',
    steps: [
      { text: 'npx prettier --write . then npm run format:check', human: true },
      { text: 'Commit through the guarded path; pre-push reruns lint + full tests.', human: true },
    ],
  },
  {
    id: 'version-drift',
    match: /\bversion|mismatch|installer\b/i,
    title: 'Version/source drift',
    diagnosis: 'Source version, site version, Worker version, and advertised installer must agree.',
    steps: [
      {
        text: 'Compare package.json vs docs/knowledge.js INSTALLER_NAME/SHA before any release.',
        klass: 'L0',
      },
      { text: 'Follow docs/RELEASE_CHECKLIST.md end to end.', human: true },
    ],
  },
];

/** Escalation policy: what automation does per severity, no improvisation. */
export const ESCALATION = [
  {
    severity: 'critical',
    automation: 'diagnose (L0) immediately, repeat each sweep',
    human: 'page the operator',
  },
  {
    severity: 'high',
    automation: 'diagnose (L0), apply granted-L1 mechanical fixes only',
    human: 'review at next console visit',
  },
  { severity: 'medium', automation: 'observe; fold into learning facts', human: 'batch review' },
  { severity: 'low', automation: 'log only', human: 'none' },
];

/** Match an incident against playbooks. Returns ranked unique matches. */
export function adviseFor(incidentsReport) {
  const out = [];
  for (const incident of incidentsReport?.incidents || []) {
    const haystack = `${incident.system} ${incident.items.join(' ')}`;
    for (const playbook of PLAYBOOKS) {
      if (playbook.match.test(haystack)) {
        if (!out.some(entry => entry.playbook.id === playbook.id)) {
          out.push({ playbook, incidents: [incident] });
        } else {
          out.find(entry => entry.playbook.id === playbook.id).incidents.push(incident);
        }
      }
    }
  }
  return out;
}
