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
  let entries = [];
  try {
    entries = fs.readdirSync(workspaceRoot, { withFileTypes: true });
  } catch {
    return systems;
  }
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    if (entry.name === 'node_modules' || entry.name === 'gaia') continue;
    const dir = path.join(workspaceRoot, entry.name);
    // A member system is either a git repo or a MIND-managed suite
    // (absorbed suites lose their .git but keep their heartbeat).
    const isRepo = fs.existsSync(path.join(dir, '.git'));
    const isMind = fs.existsSync(path.join(dir, '.mind_state.json'));
    if (!isRepo && !isMind) continue;
    systems.push({ name: entry.name, dir, repo: isRepo });
  }
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
  const dirty = Number(
    run('status', '--porcelain').split('\n').filter(Boolean).length
  );
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

/** MindState heartbeat freshness. */
function mindVitals(dir) {
  const file = path.join(dir, '.mind_state.json');
  if (!fs.existsSync(file)) return null;
  const age = ageSec(file);
  return { present: true, fresh: age !== null && age < FRESH_MAX_SEC, ageSec: age };
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
  if ((vitals.thoth?.openIncidents ?? 0) > 0) { score -= 16 * vitals.thoth.openIncidents; reasons.push(`${vitals.thoth.openIncidents} open incident(s)`); }
  score = Math.max(0, Math.min(100, score));
  const band = score >= 85 ? 'healthy' : score >= 60 ? 'watch' : score >= 35 ? 'unwell' : 'critical';
  return { score, band, reasons };
}

// ---------- pulse ----------

export function pulse({ withCi = false, workspaceRoot } = {}) {
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
  for (const alert of report.alerts) {
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

async function main() {
  const args = process.argv.slice(2);
  const cmd = args.find(a => !a.startsWith('-')) || 'pulse';
  const watch = args.includes('--watch');
  const everyMs = Math.max(60_000,
    (Number(args.find(a => /^--every/.test(a))?.split('=')[1]?.replace(/\D/g, '')) || 15) * 60_000);
  const withCi = args.includes('--ci');

  do {
    const report = pulse({ withCi });
    savePulse(report);
    console.log(render(report));
    console.log(`trend: ${trend(5).map(t => t.composite).join(' → ')}`);
    if (cmd === 'score' || cmd === 'status' || !watch) break;
    await new Promise(r => setTimeout(r, everyMs));
  } while (watch);
}

const invokedDirectly =
  process.argv[1] && import.meta.url.endsWith(path.basename(process.argv[1]));
if (invokedDirectly) main();
