// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH self-learning loop.
 *
 * Turns what the kernel already observes - incident ledgers, design-audit
 * history, tool usage - into durable, evidence-backed facts, and lets the
 * operator teach facts directly. Everything is local (.operator/, gitignored),
 * atomic, and bounded; observed facts expire when their signal goes quiet
 * while operator-taught facts persist until explicitly removed.
 *
 * Nothing here invents: every observed fact cites its evidence count and
 * refreshes only while sweeps keep confirming it.
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const LEARNINGS_PATH = path.join('.operator', 'thoth_learnings.json');
const TOOLUSE_PATH = path.join('.operator', 'thoth_tooluse.json');

const OBSERVED_KEEP = 40;
const TAUGHT_KEEP = 100;
const TOP_TOOLS = 5;
const STALE_DAYS = 14;

function learningsFile(root) {
  return path.join(root, LEARNINGS_PATH);
}

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function statisticsMedian(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[mid]
    : Math.round(((sorted[mid - 1] + sorted[mid]) / 2) * 10) / 10;
}

function atomicWriteJson(file, value) {
  mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify(value, null, 1));
  renameSync(tmp, file);
}

export function loadLearnings(root) {
  const data = readJson(learningsFile(root)) || {};
  return {
    observed: Array.isArray(data.observed) ? data.observed : [],
    taught: Array.isArray(data.taught) ? data.taught : [],
  };
}

function saveLearnings(root, learnings) {
  atomicWriteJson(learningsFile(root), {
    savedAt: new Date().toISOString(),
    observed: learnings.observed,
    taught: learnings.taught,
  });
}

/* ---------------------------------------------------------------- usage */

function loadToolUse(root) {
  const data = readJson(path.join(root, TOOLUSE_PATH));
  return data && typeof data === 'object' && !Array.isArray(data) ? data : {};
}

/** Best-effort usage counter; never throws (learning must not break ops). */
export function recordToolUse(root, toolName) {
  try {
    const counts = loadToolUse(root);
    counts[toolName] = (counts[toolName] || 0) + 1;
    const trimmed = Object.fromEntries(
      Object.entries(counts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 20)
    );
    atomicWriteJson(path.join(root, TOOLUSE_PATH), trimmed);
  } catch {
    /* counters are advisory */
  }
}

/* ------------------------------------------------------- observation */

/**
 * Reconcile fresh signals into durable facts.
 *   incidentsReport : incidents() output from federation.js
 *   ledger          : reconcileIncidents() output (mttr samples included)
 *   auditHistory    : optional [{ at, counts }] series from the design watch
 * Returns { learned, refreshed, expired } so callers can report honestly.
 */
export function observeFromSweeps(root, { incidentsReport, ledger, auditHistory } = {}) {
  const learnings = loadLearnings(root);
  const now = new Date().toISOString();
  const seen = new Set();
  let learned = 0;
  const refreshed = [];

  // Standalone callers can omit the reconciled ledger; recover its signal
  // from the persisted file so MTTR learning never depends on call order.
  if (!ledger) {
    const raw = readJson(path.join(root, '.operator', 'fleet_incidents.json'));
    if (raw && Array.isArray(raw.resolved)) {
      const samples = raw.resolved.map(r => r.mttrMinutes).filter(Number.isFinite);
      ledger = samples.length
        ? {
            resolved: raw.resolved,
            mttr: {
              count: samples.length,
              medianMinutes: statisticsMedian(samples),
              worstMinutes: Math.max(...samples),
            },
          }
        : null;
    }
  }

  const upsert = fact => {
    const existing = learnings.observed.find(f => f.id === fact.id);
    if (existing) {
      existing.evidence += 1;
      existing.lastSeen = now;
      existing.statement = fact.statement;
      refreshed.push(fact.subject);
    } else {
      learnings.observed.push({ ...fact, opened: now, lastSeen: now });
      learned += 1;
    }
    seen.add(fact.id);
  };

  // Fragility: systems with open incidents or banked MTTR history.
  for (const incident of incidentsReport?.incidents || []) {
    upsert({
      id: `fragility:${incident.system}`,
      kind: 'fragility',
      subject: incident.system,
      statement: `${incident.system} currently needs attention (${incident.severity}): ${incident.items[0] ?? 'unspecified'}.`,
      severity: incident.severity,
      evidence: 1,
    });
  }
  if (ledger?.mttr?.count >= 2) {
    const worst = [...(ledger.resolved || [])].sort(
      (a, b) => (b.mttrMinutes || 0) - (a.mttrMinutes || 0)
    )[0];
    if (worst) {
      upsert({
        id: 'fleet:mttr-profile',
        kind: 'reliability',
        subject: 'fleet',
        statement: `Fleet MTTR profile: median ${ledger.mttr.medianMinutes}m across ${ledger.mttr.count} resolved incidents; slowest was ${worst.system} (${worst.mttrMinutes}m).`,
        evidence: ledger.mttr.count,
      });
    }
  }

  // Chronic categories: present in every one of the last few audits.
  const recent = (auditHistory || []).filter(h => h && h.counts).slice(-3);
  if (recent.length === 3) {
    const keys = new Set();
    for (const run of recent) {
      for (const key of Object.keys(run.counts)) {
        if ((run.counts[key] || 0) > 0) keys.add(key);
      }
    }
    for (const key of keys) {
      if (recent.every(run => (run.counts[key] || 0) > 0)) {
        upsert({
          id: `chronic:${key}`,
          kind: 'chronic',
          subject: key,
          statement: `"${key}" findings have recurred in ${recent.length} consecutive audits - treat as chronic, not transient.`,
          evidence: recent.length,
        });
      }
    }
  }

  // Usage focus: most-used tools become a lightweight preference fact.
  const use = loadToolUse(root);
  const top = Object.entries(use)
    .sort((a, b) => b[1] - a[1])
    .slice(0, TOP_TOOLS)
    .filter(([, n]) => n >= 3);
  if (top.length) {
    upsert({
      id: 'usage:focus-tools',
      kind: 'usage',
      subject: top.map(([name]) => name).join(', '),
      statement: `Most-relied-on tools: ${top.map(([n, c]) => `${n}(${c})`).join(', ')}.`,
      evidence: top.reduce((sum, [, c]) => sum + c, 0),
    });
  }

  // Expire observed facts whose signal has gone quiet.
  const cutoff = Date.now() - STALE_DAYS * 24 * 60 * 60 * 1000;
  const before = learnings.observed.length;
  learnings.observed = learnings.observed.filter(f => {
    if (seen.has(f.id)) return true;
    return Date.parse(f.lastSeen || f.opened || now) > cutoff;
  });
  const expired = before - learnings.observed.length;

  // Bound + persist.
  learnings.observed = learnings.observed.slice(-OBSERVED_KEEP);
  learnings.taught = learnings.taught.slice(-TAUGHT_KEEP);
  try {
    saveLearnings(root, learnings);
  } catch {
    /* best-effort like the incident ledger */
  }
  return { learned, refreshed, expired };
}

/* ------------------------------------------------------------ operator */

/** Operator-taught facts are explicit knowledge: persisted, never auto-expired. */
export function teach(root, text) {
  const statement = String(text || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 300);
  if (!statement) throw new Error('nothing to teach');
  const learnings = loadLearnings(root);
  const now = new Date().toISOString();
  const id = `taught:${statement
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .slice(0, 48)}`;
  const existing = learnings.taught.find(f => f.id === id);
  if (existing) {
    existing.lastSeen = now;
    existing.evidence += 1;
  } else {
    learnings.taught.push({
      id,
      kind: 'operator',
      subject: 'operator',
      statement,
      evidence: 1,
      opened: now,
      lastSeen: now,
    });
  }
  learnings.taught = learnings.taught.slice(-TAUGHT_KEEP);
  saveLearnings(root, learnings);
  return learnings.taught.find(f => f.id === id);
}

export function unteach(root, query) {
  const needle = String(query || '')
    .toLowerCase()
    .trim();
  const learnings = loadLearnings(root);
  const kept = learnings.taught.filter(f => !f.statement.toLowerCase().includes(needle));
  const removed = learnings.taught.length - kept.length;
  learnings.taught = kept;
  saveLearnings(root, learnings);
  return removed;
}

/** Bounded human-readable digest of everything THOTH currently knows. */
export function summarize(root, { limit = 10 } = {}) {
  const learnings = loadLearnings(root);
  const lines = [];
  for (const f of learnings.taught.slice(-limit)) {
    lines.push(`[taught] ${f.statement}`);
  }
  for (const f of learnings.observed.slice(-limit)) {
    lines.push(`[${f.kind}] ${f.statement} (seen ${f.evidence}x)`);
  }
  return {
    count: learnings.taught.length + learnings.observed.length,
    text: lines.length
      ? lines.join('\n')
      : 'Nothing learned yet. Sweeps will teach me, or say "thoth teach <fact>".',
  };
}
