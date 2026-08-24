// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH creative generators.
 *
 * The creative lane lets the kernel PROPOSE autonomously - ideas, changelog
 * drafts, accessible theme palettes - while every application of a proposal
 * stays behind an explicit human gate. Generators synthesize only local,
 * verifiable inputs (audit reports, goal documents, git history); nothing is
 * invented beyond what the repository shows.
 */
import fs from 'node:fs';
import path from 'node:path';

const GOAL_DOCS = [
  ['AGENTS', 'AGENTS.md'],
  ['Error-prevention roadmap', 'docs/ERROR_PREVENTION_ROADMAP.md'],
  ['V2 release roadmap', 'docs/V2_RELEASE_ROADMAP.md'],
];

function repoRoot() {
  let dir = process.cwd();
  for (let i = 0; i < 6; i += 1) {
    if (fs.existsSync(path.join(dir, 'package.json'))) return dir;
    dir = path.dirname(dir);
  }
  return process.cwd();
}

export function deriveIdeas(auditReport) {
  const ideas = [];
  const byCat = auditReport?.counts?.byCategory || {};

  const hotspots = (auditReport?.findings || []).filter(f => f.category === 'hotspot');
  if (hotspots.length) {
    const worst = hotspots[hotspots.length - 1];
    ideas.push({
      id: `split-${path.basename(worst.file, '.js')}`,
      title: `Split hotspot ${path.basename(worst.file)}`,
      body: `${worst.file} carries the largest review burden. Extract its most cohesive section into a sibling module behind the existing registry seam, keeping the public API identical so tests hold.`,
      severityHint: 'refactor',
    });
  }

  for (const f of (auditReport?.findings || []).filter(x => x.category === 'env').slice(0, 2)) {
    const varName = f.message.match(/EIDOVARA_[A-Z0-9_]+/)?.[0]?.toLowerCase() || 'var';
    ideas.push({
      id: `declare-env-${varName}`,
      title: `Document ${f.message.match(/EIDOVARA_[A-Z0-9_]+/)?.[0]} in AGENTS.md`,
      body: `${f.file} reads this variable but the environment contract table never declared it. Add a row describing who sets it and packaged behavior, honoring AGENTS.md rule 5.`,
      severityHint: 'docs',
    });
  }

  if (byCat.cycle) {
    ideas.push({
      id: 'break-seam-cycle',
      title: 'Break the feature-seam cycle band',
      body: `${byCat.cycle} import cycle(s) route through feature-registry. Introduce a leaf module for the shared constant(s) both sides need - the same move that fixed uid/schema previously - then re-run "thoth design".`,
      severityHint: 'architecture',
    });
  }

  const staleGoal = GOAL_DOCS.find(([, rel]) => {
    try {
      return Date.now() - fs.statSync(path.join(repoRoot(), rel)).mtimeMs > 30 * 86400_000;
    } catch {
      return false;
    }
  });
  if (staleGoal) {
    ideas.push({
      id: 'refresh-goal-doc',
      title: `Refresh ${staleGoal[1]}`,
      body: 'This goal document has not changed in over 30 days while the codebase moved. Reconcile phases with shipped reality so THOTH keeps aligning to current intent.',
      severityHint: 'governance',
    });
  }
  return ideas.slice(0, 5);
}

const TYPE_ORDER = { feat: 0, fix: 1, perf: 2, docs: 3, chore: 4 };

export function draftChangelogFromGit(logText, versionLabel = 'Unreleased') {
  const lines = String(logText || '')
    .split('\n')
    .map(l => l.trim())
    .filter(Boolean);
  const groups = {};
  for (const line of lines) {
    const m = line.match(/^([a-f0-9]+)\s+(\w+)(?:\([^)]*\))?!?:\s+(.+)$/i);
    if (!m) continue;
    const type = m[2].toLowerCase();
    const bucket = Object.keys(TYPE_ORDER).find(k => type.startsWith(k)) || 'chore';
    (groups[bucket] ||= []).push(
      `- ${m[3].replace(/^\w/, c => c.toUpperCase())} (${m[1].slice(0, 7)})`
    );
  }
  const ordered = Object.keys(groups).sort((a, b) => TYPE_ORDER[a] - TYPE_ORDER[b]);
  if (!ordered.length) return null;
  const out = [`## ${versionLabel} draft`, ''];
  for (const bucket of ordered) {
    out.push(`### ${bucket}`, ...groups[bucket].slice(0, 12), '');
  }
  return out.join('\n').trim();
}

/* Accessible palette derivation: HSL rotate around the action hue with
   WCAG-checked ink choice per surface step. */
function hslToHex(h, s, l) {
  s /= 100;
  l /= 100;
  const k = n => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = n => {
    const c = l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return Math.round(255 * c)
      .toString(16)
      .padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}

function bestInk(surfaceHex) {
  const l = luminance(surfaceHex);
  return l > 0.18 ? '#101210' : '#f7faf7';
}

export function buildTheme(name, baseHue = 145) {
  const surfaces = [hslToHex(baseHue, 14, 7), hslToHex(baseHue, 13, 10), hslToHex(baseHue, 12, 14)];
  const accent = hslToHex(baseHue, 62, 45);
  const ink1 = bestInk(surfaces[0]);
  const css = [
    '/* THOTH generated theme - apply through Settings > theme */',
    ':root {',
    `  --canvas: ${surfaces[0]};`,
    `  --surface-1: ${surfaces[1]};`,
    `  --surface-2: ${surfaces[2]};`,
    `  --surface-3: ${hslToHex(baseHue, 11, 19)};`,
    `  --accent-action: ${accent};`,
    `  --ink-1: ${ink1};`,
    `  --ink-2: ${bestInk(surfaces[2])};`,
    '}',
  ].join('\n');
  return { name, baseHue, css, accent };
}
