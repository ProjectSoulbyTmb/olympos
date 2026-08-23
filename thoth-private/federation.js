// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH fleet federation.
 *
 * The operator kernel already supervises one clone at a time; this module
 * promotes it to fleet supervisor over every sibling system it can see:
 *   - MIND-managed systems expose runs/net_report.json (+ .mind_state.json)
 *   - git-bearing systems expose .git
 *   - node systems expose package.json
 *
 * Everything here is read-only, bounded, and fail-open-to-empty: a missing
 * file or unreadable sibling degrades that system's entry, never the sweep.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SKIP_DIRS = new Set([
  'node_modules', '.git', 'dist', 'dist-mac', 'archive', '.wrangler',
  'playwright-report', 'test-results', 'sbom', '_publish', 'release',
]);
const MAX_SYSTEMS = 24;
const FRESH_MS = 30 * 60 * 1000;

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function ageSeconds(file) {
  try {
    return Math.round((Date.now() - statSync(file).mtimeMs) / 1000);
  } catch {
    return null;
  }
}

/** Sibling directories worth looking at (bounded, deterministic order). */
export function discoverSystems(root) {
  const parent = path.dirname(root);
  let names;
  try {
    names = readdirSync(parent).filter(name => {
      if (name.startsWith('.') || SKIP_DIRS.has(name)) return false;
      const full = path.join(parent, name);
      try {
        return statSync(full).isDirectory();
      } catch {
        return false;
      }
    });
  } catch {
    return [];
  }
  const systems = [{ name: path.basename(root), dir: root, self: true }];
  for (const name of names.slice(0, MAX_SYSTEMS)) {
    const dir = path.join(parent, name);
    if (dir === root) continue;
    systems.push({ name, dir, self: false });
  }
  return systems;
}

function classifySystem(dir) {
  const kinds = [];
  if (existsSync(path.join(dir, '.git'))) kinds.push('git');
  if (existsSync(path.join(dir, '.mind_state.json'))) kinds.push('mind');
  if (existsSync(path.join(dir, 'package.json'))) kinds.push('node');
  return kinds;
}

function netSummary(dir) {
  const reportPath = path.join(dir, 'runs', 'net_report.json');
  if (!existsSync(reportPath)) return null;
  const report = readJson(reportPath);
  if (!report || !Array.isArray(report.endpoints)) return null;
  const down = report.endpoints.filter(e => e.status === 'down');
  return {
    healthy: report.healthy ?? null,
    degraded: report.degraded ?? 0,
    down: down.length || (report.down ?? 0),
    offlineMode: report.healthy === 0 && report.endpoints.length > 0,
    downNames: down.map(e => e.name).slice(0, 5),
    checkedAgeSec: ageSeconds(reportPath),
  };
}

function mindSummary(dir) {
  const statePath = path.join(dir, '.mind_state.json');
  if (!existsSync(statePath)) return null;
  const state = readJson(statePath) || {};
  return {
    lastEventAgeSec: ageSeconds(statePath),
    fresh: ageSeconds(statePath) !== null && ageSeconds(statePath) < FRESH_MS,
    lastRole: state.last_patrol ? 'patrol' : null,
  };
}

/** One rollup entry per discovered system. */
export function systemEntry(system) {
  const entry = { name: system.name, self: !!system.self,
                  kinds: classifySystem(system.dir) };
  entry.net = entry.kinds.includes('mind') ? netSummary(system.dir) : null;
  entry.mind = entry.net ? mindSummary(system.dir) : null;
  const pkg = readJson(path.join(system.dir, 'package.json'));
  entry.version = pkg?.version ?? null;
  entry.attention = [];
  if (entry.net) {
    if (entry.net.offlineMode)
      entry.attention.push('offline mode - network automation deferred');
    else if (entry.net.down > 0)
      entry.attention.push(`${entry.net.down} endpoint(s) down: `
        + entry.net.downNames.join(', '));
    else if (entry.net.degraded > 0)
      entry.attention.push(`${entry.net.degraded} degraded`);
  }
  if (entry.mind && entry.mind.fresh === false)
    entry.attention.push('mind daemon stale (>30m)');
  return entry;
}

/** Fleet-wide rollup across all sibling systems. */
export function fleetStatus(root) {
  const systems = discoverSystems(root).map(systemEntry);
  const attention = systems.filter(s => s.attention.length > 0);
  return {
    at: new Date().toISOString(),
    systems: systems.length,
    managed: systems.filter(s => s.kinds.includes('mind')).length,
    attention: attention.length,
    entries: systems,
  };
}

/** Correlated incidents: only systems needing action, most urgent first. */
export function incidents(root) {
  const fleet = fleetStatus(root);
  const ranked = fleet.entries
    .filter(entry => entry.attention.length > 0)
    .map(entry => ({
      system: entry.name,
      severity: entry.net?.offlineMode ? 'critical'
        : entry.net?.down > 0 ? 'high'
        : entry.kinds.includes('mind') ? 'medium' : 'low',
      items: [...entry.attention],
    }))
    .sort((a, b) => ['critical', 'high', 'medium', 'low'].indexOf(a.severity)
      - ['critical', 'high', 'medium', 'low'].indexOf(b.severity));
  return { at: fleet.at, count: ranked.length, incidents: ranked };
}


/**
 * Persistent incident ledger (.operator/fleet_incidents.json).
 *
 * Incidents get stable ids, stay open across sweeps while the underlying
 * condition holds, auto-close when a sweep comes back clean, and record
 * opened/closed timestamps so MTTR becomes a first-class metric instead of
 * tribal memory. Ledger writes are atomic and bounded (resolved entries
 * trimmed to the most recent 50).
 */
const LEDGER_PATH = path.join('.operator', 'fleet_incidents.json');
const RESOLVED_KEEP = 50;

function ledgerFile(root) {
  return path.join(root, LEDGER_PATH);
}

function loadLedger(root) {
  const data = readJson(ledgerFile(root));
  return {
    open: Array.isArray(data?.open) ? data.open : [],
    resolved: Array.isArray(data?.resolved) ? data.resolved : [],
  };
}

function saveLedger(root, ledger) {
  ledger.resolved = ledger.resolved.slice(-RESOLVED_KEEP);
  const file = ledgerFile(root);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify({ ...ledger, savedAt: new Date().toISOString() }, null, 1));
  fs.renameSync(tmp, file);
}

function fingerprint(system, items) {
  // Stable identity: same system + same first-class condition == same id.
  return `${system}::${items[0] ?? 'unknown'}`.replace(/[^A-Za-z0-9:_-]+/g, '_').slice(0, 80);
}

/** Reconcile a fresh incidents() report against the ledger.
 *  Returns { opened, stillOpen, closed, mttr } - callers surface whatever
 *  they need; nothing here throws on I/O trouble (degrades to no ledger). */
export function reconcileIncidents(root, report) {
  let ledger;
  try {
    ledger = loadLedger(root);
  } catch {
    return { opened: [], stillOpen: [], closed: [], mttr: null };
  }
  const now = new Date().toISOString();
  const reportedIds = new Set();

  for (const incident of report.incidents || []) {
    const id = fingerprint(incident.system, incident.items);
    reportedIds.add(id);
    const existing = ledger.open.find(i => i.id === id);
    if (existing) {
      existing.lastSeen = now;
      existing.items = incident.items;
    } else {
      ledger.open.push({
        id,
        system: incident.system,
        severity: incident.severity,
        items: incident.items,
        opened: now,
        lastSeen: now,
      });
    }
  }

  const stillOpenList = [];
  for (const entry of [...ledger.open]) {
    if (reportedIds.has(entry.id)) {
      stillOpenList.push(entry);
      continue;
    }
    // Condition gone -> close it and bank the MTTR sample.
    const openedMs = Date.parse(entry.opened) || Date.now();
    entry.closed = now;
    entry.mttrMinutes = Math.max(1, Math.round((Date.now() - openedMs) / 60000));
    ledger.resolved.push(entry);
    ledger.open = ledger.open.filter(i => i.id !== entry.id);
  }

  const closedNow = ledger.resolved.slice(-10).map(r => ({
    system: r.system,
    items: r.items,
    mttrMinutes: r.mttrMinutes,
  }));

  try {
    saveLedger(root, ledger);
  } catch {}

  const samples = ledger.resolved.map(r => r.mttrMinutes).filter(Number.isFinite);
  const mttr = samples.length
    ? {
        count: samples.length,
        medianMinutes: statisticsMedian(samples),
        worstMinutes: Math.max(...samples),
      }
    : null;

  return {
    opened: ledger.open.filter(i => i.opened === now),
    stillOpen: stillOpenList,
    recentlyClosed: closedNow,
    mttr,
  };
}

function statisticsMedian(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid]
    : Math.round(((sorted[mid - 1] + sorted[mid]) / 2) * 10) / 10;
}