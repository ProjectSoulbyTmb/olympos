// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH continuous-design subsystem.
 *
 * Bridges the tracked scanner (scripts/design-scan.mjs) into the operator
 * console: on-demand audits, a persistent watch loop, goal tracking against
 * AGENTS.md / ERROR_PREVENTION_ROADMAP.md, and a deterministic "what next"
 * advisor. All analysis is local; nothing is transmitted.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const AUDIT_INTERVAL_MS = 30 * 60 * 1000;
const GOAL_DOCS = ['AGENTS.md', 'docs/ERROR_PREVENTION_ROADMAP.md', 'docs/V2_RELEASE_ROADMAP.md'];
const PRIORITY = ['cycle', 'seam', 'env', 'spdx', 'hotspot'];

function repoRoot() {
  // Installed copy lives at <root>/src/features/thoth; anchor on the
  // package.json that owns this module graph.
  let dir = path.dirname(fileURLToPath(import.meta.url));
  for (let i = 0; i < 6; i += 1) {
    if (fs.existsSync(path.join(dir, 'package.json'))) return dir;
    dir = path.dirname(dir);
  }
  return process.cwd();
}

async function scanner() {
  const url = new URL(
    `file:///${repoRoot().split(path.sep).join('/')}/scripts/design-scan.mjs`
  );
  return import(url.href);
}

export async function auditNow(engine, relay) {
  const mod = await scanner();
  const report = mod.scanRepo({ root: repoRoot() });
  const design = ensureDesignState(engine);
  const prev = design.lastAudit;
  const fingerprint = new Set(
    report.findings.map(f => `${f.category}|${f.file.split(path.sep).join('/')}|${f.message}`)
  );
  const prevFingerprint = new Set(
    (prev?.top || []).map(f => `${f.category}|${f.file}|${f.message}`)
  );
  let newCount = 0;
  for (const key of fingerprint) if (!prevFingerprint.has(key)) newCount += 1;
  design.lastAudit = {
    at: report.generatedAt,
    filesScanned: report.filesScanned,
    modules: report.modules,
    edges: report.edges,
    counts: report.counts,
    newCount,
    resolvedCount: prev ? Math.max(0, totalFindings(prev) - totalFindings(report)) : 0,
    top: report.findings.slice(0, 25).map(f => ({
      category: f.category,
      severity: f.severity,
      file: f.file.split(path.sep).join('/'),
      message: f.message,
    })),
    history: [
      ...(design.lastAudit?.history || []),
      { at: report.generatedAt, total: totalFindings(report), newCount },
    ].slice(-10),
  };
  engine.store.save(engine.state);
  const high = report.findings.filter(f => f.severity === 'high').length;
  relay?.emit('design', {
    total: totalFindings(report),
    newCount,
    resolvedCount: 0,
    high,
    byCategory: report.counts.byCategory,
    announce: newCount > 0 || high > 0,
    text:
      `Design audit: ${report.findings.length} findings` +
      (newCount ? `, ${newCount} new` : '') +
      (high ? `, ${high} high severity` : ''),
  });
  return { report, stored: design.lastAudit };
}

function totalFindings(snapshotOrReport) {
  const byCat = snapshotOrReport?.counts?.byCategory;
  return byCat ? Object.values(byCat).reduce((a, b) => a + b, 0) : 0;
}

function ensureDesignState(engine) {
  if (!engine.state.thoth || typeof engine.state.thoth !== 'object') engine.state.thoth = {};
  if (!engine.state.thoth.design || typeof engine.state.thoth.design !== 'object') {
    engine.state.thoth.design = { watch: false, lastAudit: null };
  }
  return engine.state.thoth.design;
}

export function startWatch(engine, relay) {
  const design = ensureDesignState(engine);
  if (design.watch) return false;
  design.watch = true;
  let timer = null;
  // Adaptive cadence: trouble gets attention faster, calm gets quiet.
  const nextDelay = () => {
    const total = totalFindings(design.lastAudit || {});
    if (total >= 10) return 15 * 60 * 1000;
    if (total <= 3) return 45 * 60 * 1000;
    return AUDIT_INTERVAL_MS;
  };
  const tick = async () => {
    try {
      if (engine.state.thoth?.masterEnabled !== false) {
        const before = totalFindings(design.lastAudit || {});
        await auditNow(engine, relay);
        const after = totalFindings(design.lastAudit || {});
        // Compliance rides the same cadence (standards/rules.json).
        try {
          const { scanCompliance } = await import(
            new URL(`file:///${repoRoot().split(path.sep).join('/')}/scripts/compliance-scan.mjs`).href
          );
          const crep = scanCompliance({ fix: false });
          engine.state.thoth.compliance = {
            at: crep.generatedAt,
            counts: crep.counts,
            findings: crep.findings.slice(0, 25),
          };
          engine.store.save(engine.state);
          relay?.emit('compliance', {
            total: crep.findings.length,
            bySeverity: crep.counts,
            announce: (crep.counts.high || 0) > 0,
            text: `Compliance scan: ${crep.findings.length} finding(s).`,
          });
        } catch {
          /* compliance is advisory; design loop continues */
        }
        // Regression watchdog: findings rising with high-severity present.
        const byCategory = design.lastAudit?.counts?.byCategory || {};
        const highs = (byCategory.cycle || 0) + (byCategory.seam || 0);
        if (after > before && highs > 0) {
          relay?.emit('regression', {
            before,
            after,
            high: highs,
            announce: true,
            text: `Architecture regression: findings rose ${before} to ${after} with ${highs} high-severity.`,
          });
        }
      }
    } catch {
      /* honest silence: findings surface on next successful tick */
    } finally {
      if (design.watch) {
        timer = setTimeout(tick, nextDelay());
        timer.unref?.();
      }
    }
  };
  setTimeout(tick, 15_000).unref?.();
  return true;
}

export function trends(stored) {
  const series = stored?.history || [];
  if (series.length < 2) {
    return 'Not enough audit history for trends yet (need 2+ watch ticks).';
  }
  const points = series.slice(-8).map(h => `${h.at.slice(11, 16)} ${h.total}`);
  const first = series[Math.max(0, series.length - 8)].total;
  const last = series[series.length - 1].total;
  const best = Math.min(...series.map(h => h.total));
  const direction = last < first ? 'improving' : last > first ? 'degrading' : 'flat';
  return [
    `Findings trend (${direction}): ${points.join(' -> ')}`,
    `Best-ever total: ${best}. Current: ${last}.`,
  ].join('\n');
}

export function regressionReport(stored) {
  if (!stored?.lastAudit && !stored?.history) return 'No audits recorded yet.';
  const history = stored.history || [];
  const last = stored.lastAudit;
  const prev = history.length >= 2 ? history[history.length - 2] : null;
  const newCount = last?.newCount ?? 0;
  const lines = [`Last audit ${last?.at || 'n/a'}: ${totalFindings(last || {})} findings (${newCount} new).`];
  if (prev) lines.push(`Previous tick: ${prev.total}. Delta: ${totalFindings(last || {}) - prev.total}.`);
  const byCat = last?.counts?.byCategory || {};
  for (const cat of PRIORITY) {
    if (byCat[cat]) lines.push(`  ${cat}: ${byCat[cat]}`);
  }
  return lines.join('\n');
}

export function stopWatch(engine) {
  const design = ensureDesignState(engine);
  const was = design.watch;
  design.watch = false;
  return was;
}

export function goalsStatus() {
  const root = repoRoot();
  return GOAL_DOCS.map(rel => ({
    goal: rel
      .replace(/\.md$/, '')
      .replace(/^docs\//, '')
      .replace(/_/g, ' '),
    doc: rel,
    present: fs.existsSync(path.join(root, rel)),
  }));
}

export function nextActions(stored) {
  if (!stored?.top?.length) {
    return [
      'No open design findings. Next architectural leverage:',
      '- shrink the largest hotspot file(s) flagged in past audits',
      '- keep ERROR_PREVENTION_ROADMAP phases moving; re-check docs',
    ].join('\n');
  }
  const deltaLine =
    stored.newCount !== undefined
      ? `Since previous audit: ${stored.newCount} new, ${stored.resolvedCount ?? '?'} resolved. Trend: ${stored.history
          ?.slice(-5)
          .map(h => h.total)
          .join(' â†’ ')}`
      : '';
  const byCat = new Map();
  for (const f of stored.top) {
    if (!byCat.has(f.category)) byCat.set(f.category, []);
    byCat.get(f.category).push(f);
  }
  const lines = ['Priority queue (severity-ordered):'];
  if (deltaLine) lines.splice(1, 0, deltaLine);
  for (const cat of PRIORITY) {
    const items = byCat.get(cat);
    if (!items) continue;
    lines.push(`${cat.toUpperCase()} (${items.length}):`);
    for (const f of items.slice(0, 3)) lines.push(`  - ${f.file}: ${f.message}`);
  }
  return lines.join('\n');
}
