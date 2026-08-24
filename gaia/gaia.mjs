// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * GAIA - ecosystem health kernel.
 *
 * The pantheon:
 *   THOTH  operator kernel        (project---soul) - fleet federation, incidents, MTTR
 *   MIND   suite daemon           (osrs-unified)   - network sweeps, patrol, releases
 *   VENUS  desktop companion      (assistant)      - human interface, voice, automation
 *   GAIA   THIS KERNEL            - watches the whole organism as one system
 *
 * GAIA collects vitals from every member (git sync state, commit age,
 * CI verdicts via gh, MIND network posture, daemon freshness, THOTH
 * incident ledger), scores each system 0-100, keeps a bounded pulse
 * history for trend detection, and raises severity-ranked alerts.
 *
 * Offline-first and fail-open-to-empty: a missing signal lowers nothing
 * by itself - it is reported as unknown, never guessed.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

export const GAIA_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)));
const HISTORY_DIR = path.join(GAIA_ROOT, 'runs');
const ALERTS_PATH = path.join(HISTORY_DIR, 'gaia_alerts.jsonl');
const HISTORY_CAP = 60;

// ---------- shared io ----------

export function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function writeAtomic(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, typeof data === 'string' ? data : JSON.stringify(data, null, 1));
  fs.renameSync(tmp, file);
}

function ageSec(file) {
  try {
    return Math.round((Date.now() - fs.statSync(file).mtimeMs) / 1000);
  } catch {
    return null;
  }
}

// ---------- discovery ----------

export function discoverSystems(workspaceRoot = path.dirname(GAIA_ROOT)) {
  const systems = [];
  const consider = (dir, name) => {
    // A member system is either a git repo or a MIND-managed suite
    // (absorbed suites lose their .git but keep their heartbeat).
    const isRepo = fs.existsSync(path.join(dir, '.git'));
    const isMind = fs.existsSync(path.join(dir, '.mind_state.json'));
    if (isRepo || isMind) systems.push({ name, dir, repo: isRepo });
  };
  let entries = [];
  try {
    entries = fs.readdirSync(workspaceRoot, { withFileTypes: true });
  } catch {
    return systems;
  }
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    if (entry.name === 'node_modules' || entry.name === 'gaia') continue;
    consider(path.join(workspaceRoot, entry.name), entry.name);
  }
  consider(workspaceRoot, 'workspace');
  return systems.sort((a, b) => a.name.localeCompare(b.name));
}

// ---------- vitals collectors ----------

function gitVitals(dir) {
  const env = {};
  for (const [k, v] of Object.entries(process.env))
    if (!k.startsWith('GIT_')) env[k] = v;
  const run = (...args) => {
    try {
      return execFileSync('git', args, { cwd: dir, encoding: 'utf8', env }).trim();
    } catch {
      return null;
    }
  };
  const branch = run('rev-parse', '--abbrev-ref', 'HEAD') ?? '(unknown)';
  const porcelain = run('status', '--porcelain');
  const dirty = porcelain ? porcelain.split('\n').filter(Boolean).length : null;
  run('fetch', '--quiet', '--all');
  const ahead = Number(run('rev-list', '--count', '@{upstream}..HEAD')) || 0;
  const behind = Number(run('rev-list', '--count', 'HEAD..@{upstream}')) || 0;
  const lastTs = Number(run('log', '-1', '--format=%ct')) * 1000;
  return {
    branch,
    synced: ahead === 0 && behind === 0,
    diverged: ahead > 0 && behind > 0,
    behind,
    ahead,
    dirty: Number.isFinite(dirty) ? dirty : null,
    lastCommitAgeDays: lastTs ? Math.round((Date.now() - lastTs) / 86_400_000) : null,
  };
}

/** MIND network posture (osrs-unified convention). */
function netVitals(dir) {
  const file = path.join(dir, 'runs', 'net_report.json');
  if (!fs.existsSync(file)) return null;
  const report = readJson(file);
  if (!report?.endpoints) return null;
  return {
    healthy: report.healthy ?? 0,
    degraded: report.degraded ?? 0,
    down: (report.endpoints.filter(e => e.status === 'down')).map(e => e.name),
    offlineMode: report.healthy === 0,
    checkedAgeSec: ageSec(file),
  };
}

/** MindState heartbeat freshness: daemon loops touch .mind_state.json,
 *  while one-shot commands write runs/mind_status.json. Either counts as alive. */
function mindVitals(dir) {
  const ages = [
    ageSec(path.join(dir, '.mind_state.json')),
    ageSec(path.join(dir, 'runs', 'mind_status.json')),
  ].filter(a => a !== null);
  if (!ages.length) return null;
  const age = Math.min(...ages);
  return { present: true, fresh: age < FRESH_MAX_SEC, ageSec: age };
}
const FRESH_MAX_SEC = 30 * 60;

/** THOTH incident ledger (Eidovara convention). */
function thothVitals(dir) {
  const ledger = readJson(path.join(dir, '.operator', 'fleet_incidents.json'));
  if (!ledger) return null;
  return { openIncidents: ledger.open?.length ?? 0 };
}

/** Venus lane liveness (assistant convention): archived envelopes exist. */
function venusVitals(dir) {
  const lane = path.join(dir, '.operator', 'venus_bus', 'archive');
  if (!fs.existsSync(lane)) return null;
  try {
    const count = fs.readdirSync(lane).filter(n => n.endsWith('.json')).length;
    return { archivedReplies: count };
  } catch {
    return null;
  }
}

/** Host disk headroom for the system's drive (expansion vital). */
export function diskVitals(dir) {
  if (typeof fs.statfsSync !== 'function') return null;
  try {
    const s = fs.statfsSync(dir);
    const freePct = Math.round((s.bfree / s.blocks) * 100);
    return { freePct, freeGb: Math.round((s.bfree * s.bsize) / 2 ** 30) };
  } catch {
    return null;
  }
}

function ciVitals(dir) {
  try {
    const out = execFileSync('gh', ['run', 'list', '--limit', '1', '--json',
      'conclusion,status'], { cwd: dir, encoding: 'utf8', timeout: 20_000 });
    const runs = JSON.parse(out);
    return runs?.[0]?.conclusion ?? runs?.[0]?.status ?? null;
  } catch {
    return null; // gh absent or unauthenticated -> unknown, not failure
  }
}

/** Collect every vital for one system. Never throws. */
export function collectVitals(system, { withCi = false } = {}) {
  const vitals = { name: system.name, dir: system.dir };
  try {
    Object.assign(vitals,
      system.repo === false ? { repo: false } : gitVitals(system.dir));
  } catch {
    vitals.gitError = true;
  }
  vitals.net = netVitals(system.dir);
  vitals.mind = mindVitals(system.dir);
  vitals.thoth = thothVitals(system.dir);
  vitals.venus = venusVitals(system.dir);
  vitals.disk = diskVitals(system.dir);
  vitals.ci = withCi ? ciVitals(system.dir) : null;
  return vitals;
}

// ---------- scoring (pure) ----------

export function scoreSystem(vitals) {
  let score = 100;
  const reasons = [];
  if (vitals.gitError) return { score: 0, band: 'critical', reasons: ['git unreadable'] };
  const repoTracked = vitals.repo !== false && vitals.branch;
  if (!repoTracked) { /* non-git member: scored on its runtime vitals only */ }
  else if (vitals.diverged) { score -= 25; reasons.push('diverged from origin'); }
  else if (!vitals.synced) { score -= 10; reasons.push(`not synced (${vitals.ahead}A/${vitals.behind}B)`); }
  if ((vitals.dirty ?? 0) > 0) { score -= Math.min(vitals.dirty, 10); reasons.push(`${vitals.dirty} dirty`); }
  if (repoTracked && (vitals.lastCommitAgeDays ?? 0) > 90) { score -= 10; reasons.push(`dormant ${vitals.lastCommitAgeDays}d`); }
  else if (repoTracked && (vitals.lastCommitAgeDays ?? 0) > 30) { score -= 5; reasons.push(`quiet ${vitals.lastCommitAgeDays}d`); }
  if (vitals.ci === 'failure') { score -= 20; reasons.push('CI failing'); }
  if (vitals.net) {
    if (vitals.net.offlineMode) { score -= 30; reasons.push('network offline mode'); }
    score -= 8 * vitals.net.down.length;
    if (vitals.net.down.length) reasons.push(`endpoints down: ${vitals.net.down.join(',')}`);
    if (vitals.net.degraded > 0) { score -= 4 * vitals.net.degraded; reasons.push(`${vitals.net.degraded} degraded`); }
  }
  if (vitals.mind && vitals.mind.fresh === false) { score -= 5; reasons.push(`mind stale ${Math.round((vitals.mind.ageSec ?? 0) / 60)}m`); }
  if (vitals.disk && vitals.disk.freePct < 5) { score -= 15; reasons.push(`disk ${vitals.disk.freePct}% free`); }
  else if (vitals.disk && vitals.disk.freePct < 10) { score -= 8; reasons.push(`disk ${vitals.disk.freePct}% free`); }
  if ((vitals.thoth?.openIncidents ?? 0) > 0) { score -= 16 * vitals.thoth.openIncidents; reasons.push(`${vitals.thoth.openIncidents} open incident(s)`); }
  score = Math.max(0, Math.min(100, score));
  const band = score >= 85 ? 'healthy' : score >= 60 ? 'watch' : score >= 35 ? 'unwell' : 'critical';
  return { score, band, reasons };
}

// ---------- regression, alert hygiene, advice (pure) ----------

const BAND_RANK = { healthy: 0, watch: 1, unwell: 2, critical: 3 };
const REGRESSION_DROP = 10;
const ALERT_COOLDOWN_MS = 60 * 60_000;

const signatureOf = a =>
  `${a.severity}:${a.system}:${[...a.reasons].sort().join('|')}`;

/** Flag systems whose score dropped sharply or slid a band since last pulse. */
export function detectRegressions(report, previous) {
  if (!previous?.systems?.length) return [];
  const out = [];
  const prevByName = new Map(previous.systems.map(s => [s.name, s]));
  for (const s of report.systems) {
    const p = prevByName.get(s.name);
    if (!p) continue;
    const slid = (BAND_RANK[s.band] ?? 0) > (BAND_RANK[p.band] ?? 0);
    if (slid || p.score - s.score >= REGRESSION_DROP)
      out.push({ severity: 'regression', system: s.name,
                 reasons: [`score ${p.score}->${s.score}`, `band ${p.band}->${s.band}`] });
  }
  if (report.composite != null && previous.composite != null &&
      previous.composite - report.composite >= REGRESSION_DROP)
    out.push({ severity: 'regression', system: 'ecosystem',
               reasons: [`composite ${previous.composite}->${report.composite}`] });
  return out;
}

/** Suppress ledger repeats inside the cooldown so watch mode stays quiet. */
export function freshAlerts(alerts, ledgerText, now = Date.now()) {
  const lastSeen = new Map();
  for (const line of String(ledgerText ?? '').split('\n')) {
    if (!line.trim()) continue;
    try {
      const e = JSON.parse(line);
      lastSeen.set(signatureOf(e), Date.parse(e.at));
    } catch { /* skip corrupt ledger line */ }
  }
  return alerts.filter(a => {
    const at = lastSeen.get(signatureOf(a));
    return at == null || now - at >= ALERT_COOLDOWN_MS;
  });
}

/** Concrete next actions for one scored system; empty array means nothing to do. */
export function advise(v) {
  const steps = [];
  if (v.gitError) return ['inspect repository access - git unreadable'];
  if (v.repo !== false && v.branch) {
    if (v.diverged) steps.push('git pull --rebase, resolve, then push (diverged)');
    else if (v.behind > 0) steps.push(`git pull --ff-only (${v.behind} behind)`);
    else if (v.ahead > 0) steps.push(`git push (${v.ahead} ahead)`);
    if ((v.dirty ?? 0) > 0) steps.push(`commit or stash ${v.dirty} pending change(s)`);
  }
  if ((v.lastCommitAgeDays ?? 0) > 90) steps.push(`dormant ${v.lastCommitAgeDays}d - archive or revive`);
  else if ((v.lastCommitAgeDays ?? 0) > 30) steps.push(`quiet ${v.lastCommitAgeDays}d - review roadmap`);
  if (v.ci === 'failure') steps.push('triage CI: gh run view --log-failed');
  if (v.net) {
    if (v.net.offlineMode) steps.push('network offline - restore connectivity / rerun MIND sweep');
    else if (v.net.down.length) steps.push(`restore endpoints: ${v.net.down.join(', ')}`);
  }
  if (v.mind?.fresh === false)
    steps.push(`MIND heartbeat stale ${Math.round((v.mind.ageSec ?? 0) / 60_000)}m - restart daemon`);
  if (v.disk && v.disk.freePct < 10) steps.push(`free disk space (${v.disk.freePct}% free, ${v.disk.freeGb}GB)`);
  if ((v.thoth?.openIncidents ?? 0) > 0)
    steps.push(`close ${v.thoth.openIncidents} THOTH incident(s)`);
  return steps;
}

// ---------- remediation (safe actions only) ----------

function runGit(dir, ...args) {
  try {
    return { ok: true, out: execFileSync('git', args, { cwd: dir, encoding: 'utf8' }).trim() };
  } catch (e) {
    return { ok: false, err: String(e?.stderr ?? e?.message ?? e).trim() };
  }
}

/** Auto-remediable steps for one system. Diverged/dirty trees are never touched. */
export function planFixes(v) {
  const plan = [];
  if (v.gitError || v.repo === false || !v.branch) return plan;
  if (!v.diverged && v.behind > 0) plan.push({ kind: 'git', args: ['pull', '--ff-only'], label: `git pull --ff-only (${v.behind} behind)` });
  if (!v.diverged && v.ahead > 0 && v.dirty === 0) plan.push({ kind: 'git', args: ['push'], label: `git push (${v.ahead} ahead)` });
  if (v.mind?.fresh === false && fs.existsSync(path.join(v.dir, 'mind', 'daemon.py')))
    plan.push({ kind: 'mind', label: 'MIND patrol refresh (mind/daemon.py status)' });
  return plan;
}

/** Execute a system's fix plan; dryRun=true only reports intent. Never throws. */
export function applyFix(v, { dryRun = true } = {}) {
  return planFixes(v).map(step => {
    if (dryRun) return { ...step, result: 'planned' };
    if (step.kind === 'git') {
      const r = runGit(v.dir, ...step.args);
      return { ...step, result: r.ok ? 'done' : 'failed', detail: r.ok ? r.out : r.err };
    }
    if (step.kind === 'mind') {
      try {
        const out = execFileSync('python', [path.join(v.dir, 'mind', 'daemon.py'), 'status'],
          { cwd: v.dir, encoding: 'utf8', timeout: 120_000 });
        return { ...step, result: 'done', detail: out.split('\n')[0] };
      } catch (e) {
        return { ...step, result: 'failed', detail: String(e?.stderr ?? e?.message ?? e).trim() };
      }
    }
    return { ...step, result: 'skipped' };
  });
}

// ---------- pulse ----------

export function pulse({ withCi = false, workspaceRoot, previous = null } = {}) {
  const systems = discoverSystems(workspaceRoot).map(s => collectVitals(s, { withCi }));
  const scored = systems.map(v => ({ ...v, ...scoreSystem(v) }));
  const composite = scored.length
    ? Math.round(scored.reduce((sum, s) => sum + s.score, 0) / scored.length)
    : null;
  const alerts = [];
  for (const s of scored) {
    if (s.band === 'critical' || s.band === 'unwell')
      alerts.push({ severity: s.band === 'critical' ? 'critical' : 'warning',
                    system: s.name, reasons: s.reasons });
  }
  alerts.push(...detectRegressions({ composite, systems: scored }, previous));
  return { at: new Date().toISOString(), composite, systems: scored, alerts };
}

export function savePulse(report) {
  const stamp = report.at.replace(/[:.]/g, '-');
  writeAtomic(path.join(HISTORY_DIR, `pulse-${stamp}.json`), report);
  writeAtomic(path.join(HISTORY_DIR, 'pulse_latest.json'), report);
  const history = fs.readdirSync(HISTORY_DIR)
    .filter(f => f.startsWith('pulse-2') && f.endsWith('.json'))
    .sort();
  while (history.length > HISTORY_CAP) fs.unlinkSync(path.join(HISTORY_DIR, history.shift()));
  let ledgerText = '';
  try { ledgerText = fs.readFileSync(ALERTS_PATH, 'utf8'); } catch { /* first run */ }
  for (const alert of freshAlerts(report.alerts, ledgerText)) {
    fs.appendFileSync(ALERTS_PATH,
      `${JSON.stringify({ at: report.at, ...alert })}\n`);
  }
}

export function trend(limit = 10) {
  const files = fs.readdirSync(HISTORY_DIR)
    .filter(f => f.startsWith('pulse-2') && f.endsWith('.json'))
    .sort()
    .slice(-limit);
  return files.map(f => {
    const r = readJson(path.join(HISTORY_DIR, f));
    return r ? { at: r.at, composite: r.composite } : null;
  }).filter(Boolean);
}

// ---------- cli ----------

function render(report) {
  const lines = [`GAIA pulse @ ${report.at} — ecosystem composite: ${report.composite}/100`];
  for (const s of report.systems) {
    const identity = s.repo === false
      ? '(mind-managed)'
      : `${s.branch ?? '?'} ${s.synced ? 'synced' : `ahead=${s.ahead} behind=${s.behind}`}`;
    lines.push(`  ${String(s.name).padEnd(18)} ${s.score}/100 [${s.band}] `
      + identity
      + (s.net ? ` net:${s.net.healthy}✓/${s.net.down.length}✗` : '')
      + (s.reasons.length ? `  — ${s.reasons.join('; ')}` : ''));
  }
  if (report.alerts.length) {
    lines.push('ALERTS:');
    for (const a of report.alerts)
      lines.push(`  [${a.severity}] ${a.system}: ${a.reasons.join('; ')}`);
  }
  return lines.join('\n');
}

function renderDoctor(report) {
  const lines = [`GAIA doctor @ ${report.at} — remediation plan`];
  let anyStep = false;
  for (const s of report.systems) {
    const steps = advise(s);
    lines.push(`  ${String(s.name).padEnd(18)} ${s.score}/100 [${s.band}]`);
    if (!steps.length) { lines.push('    nothing to do'); continue; }
    anyStep = true;
    for (const step of steps) lines.push(`    -> ${step}`);
  }
  if (!anyStep) lines.push('ecosystem clean - no action required');
  return lines.join('\n');
}

function renderFix(fixMap, applied) {
  const lines = [`GAIA fix — safe auto-remediation: ${applied ? 'APPLIED' : 'PLAN (dry-run; pass --execute to apply)'}`];
  for (const [name, steps] of Object.entries(fixMap)) {
    if (!steps.length) continue;
    lines.push(`  ${name}:`);
    for (const s of steps)
      lines.push(`    [${s.result}] ${s.label}${s.detail ? `  (${String(s.detail).split('\n')[0]})` : ''}`);
  }
  const total = Object.values(fixMap).reduce((n, v) => n + v.length, 0);
  if (!total) lines.push('  nothing auto-fixable - run doctor for manual guidance');
  return lines.join('\n');
}

function renderTrend(entries) {
  if (!entries.length) return 'GAIA trend: no history yet';
  return ['GAIA trend:',
    ...entries.map(e => `  ${e.at}  ${String(e.composite ?? '?').padStart(3)}/100`),
    `  ${entries.map(e => e.composite ?? '?').join(' → ')}`].join('\n');
}

async function main() {
  const args = process.argv.slice(2);
  const cmd = args.find(a => !a.startsWith('-')) || 'pulse';
  const watch = args.includes('--watch');
  const everyMs = Math.max(60_000,
    (Number(args.find(a => /^--every/.test(a))?.split('=')[1]?.replace(/\D/g, '')) || 15) * 60_000);
  const withCi = args.includes('--ci');
  const asJson = args.includes('--json');
  const execute = args.includes('--execute');
  const withFix = args.includes('--fix');

  do {
    if (cmd === 'trend') {
      const entries = trend(20);
      console.log(asJson ? JSON.stringify(entries, null, 1) : renderTrend(entries));
      break;
    }
    if (cmd === 'fix') {
      const systems = discoverSystems().map(s => collectVitals(s));
      const fixMap = Object.fromEntries(systems.map(v => [v.name, applyFix(v, { dryRun: !execute })]));
      console.log(asJson ? JSON.stringify(fixMap, null, 1) : renderFix(fixMap, execute));
      break;
    }
    const previous = readJson(path.join(HISTORY_DIR, 'pulse_latest.json'));
    const report = pulse({ withCi, previous });
    savePulse(report);
    if (cmd === 'doctor') {
      console.log(asJson
        ? JSON.stringify(report.systems.map(s =>
            ({ name: s.name, score: s.score, band: s.band, advice: advise(s) })), null, 1)
        : renderDoctor(report));
    } else {
      console.log(asJson ? JSON.stringify(report, null, 1) : render(report));
    }
    if (withFix && execute) {
      const fixMap = Object.fromEntries(report.systems.map(v => [v.name, applyFix(v, { dryRun: false })]));
      const touched = Object.entries(fixMap).filter(([, steps]) => steps.length);
      if (touched.length)
        console.log('autofix: ' + touched.map(([n, steps]) =>
          `${n}(${steps.map(s => `${s.result}:${s.label}`).join(', ')})`).join(' | '));
    }
    if (!asJson) console.log(`trend: ${trend(5).map(t => t.composite).join(' → ')}`);
    if (!watch) break;
    await new Promise(r => setTimeout(r, everyMs));
  } while (watch);
}

const invokedDirectly =
  process.argv[1] && import.meta.url.endsWith(path.basename(process.argv[1]));
if (invokedDirectly) main();
