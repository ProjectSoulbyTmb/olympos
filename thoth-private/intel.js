// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH advanced coding knowledge - a live index of THIS repository.
 *
 * Everything here is derived from the actual tree on disk (never from
 * memory or invention): per-file facts, export maps, seam classification,
 * the AGENTS.md convention contract, and a symbol finder. Powers
 * "thoth code *" tools so proposals cite real files and real rules.
 */
import fs from 'node:fs';
import path from 'node:path';

const SKIP_DIRS = new Set(['node_modules', 'dist', 'dist-mac', '.git', 'coverage', '_publish', 'playwright-report', 'test-results']);
const FROZEN = [
  'src/electron/main.js',
  'src/renderer/index.html',
  'src/renderer/renderer.js',
  'src/electron/preload.cjs',
  'src/core/guards/index.js',
];

function repoRoot() {
  let dir = process.cwd();
  for (let i = 0; i < 6; i += 1) {
    if (fs.existsSync(path.join(dir, 'package.json'))) return dir;
    dir = path.dirname(dir);
  }
  return process.cwd();
}

function listSource(root, rel = 'src', out = []) {
  const abs = path.join(root, rel);
  let entries;
  try {
    entries = fs.readdirSync(abs, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    if (e.isDirectory()) {
      if (!SKIP_DIRS.has(e.name)) listSource(root, path.join(rel, e.name), out);
    } else if (/\.(js|mjs|cjs)$/.test(e.name)) {
      out.push(path.join(rel, e.name));
    }
  }
  return out;
}

let cache = null;
export function buildIndex(root = repoRoot(), force = false) {
  if (cache && !force) return cache;
  const files = listSource(root);
  const index = { root, files: [], exports: new Map() };
  for (const rel of files) {
    const norm = rel.split(path.sep).join('/');
    let text;
    try {
      text = fs.readFileSync(path.join(root, rel), 'utf8');
    } catch {
      continue;
    }
    const lines = text.split('\n').length;
    const namedExports = [...text.matchAll(/export\s+(?:async\s+)?(?:function|const|class|let)\s+([A-Za-z0-9_$]+)/g)].map(m => m[1]);
    const frozen = FROZEN.includes(norm);
    const zone = norm.startsWith('src/core/')
      ? 'core'
      : norm.startsWith('src/features/')
        ? 'feature'
        : norm.startsWith('src/providers/')
          ? 'provider'
          : norm.startsWith('src/electron/')
            ? 'electron'
            : norm.startsWith('src/renderer/')
              ? 'renderer'
              : 'other';
    index.files.push({ file: norm, lines, namedExports, frozen, zone });
    for (const name of namedExports) {
      if (!index.exports.has(name)) index.exports.set(name, []);
      index.exports.get(name).push(norm);
    }
  }
  cache = index;
  return index;
}

export function explainFile(target) {
  const want = String(target || '').split(path.sep).join('/').toLowerCase();
  const index = buildIndex();
  const entry =
    index.files.find(f => f.file.toLowerCase().endsWith(want)) ||
    index.files.find(f => f.file.toLowerCase().includes(want));
  if (!entry) return `No first-party file matches "${target}".`;
  const facts = [
    `${entry.file} (${entry.zone} zone, ${entry.lines} lines${entry.frozen ? ', STARTUP-FROZEN - boot-smoke required' : ''})`,
    entry.namedExports.length ? `exports: ${entry.namedExports.join(', ')}` : 'no named exports',
  ];
  if (entry.zone === 'core') facts.push('core zone: may import providers/other core only; feature access goes through the registry seam.');
  if (entry.zone === 'feature') facts.push('feature zone: registers via src/core/feature-registry.js; may import core modules.');
  return facts.join('\n');
}

export function findSymbol(symbol) {
  const name = String(symbol || '').trim();
  if (!name) return 'Usage: thoth code find <symbol>';
  const index = buildIndex();
  const hits = [];
  for (const [exportName, paths] of index.exports) {
    if (exportName.toLowerCase().includes(name.toLowerCase())) {
      hits.push(`export ${exportName} -> ${paths.join(', ')}`);
    }
  }
  for (const f of index.files) {
    if (f.file.toLowerCase().includes(name.toLowerCase()) && !hits.some(h => h.includes(f.file))) {
      hits.push(`file ${f.file}`);
    }
  }
  return hits.length ? `Symbol matches:\n${hits.slice(0, 12).map(h => `- ${h}`).join('\n')}` : `No export or file matches "${name}".`;
}

export function conventions() {
  const agentsPath = path.join(repoRoot(), 'AGENTS.md');
  let text;
  try {
    text = fs.readFileSync(agentsPath, 'utf8');
  } catch {
    return 'AGENTS.md unavailable.';
  }
  const rules = text
    .split('\n')
    .filter(l => /^#{1,3}\s+\d/.test(l) || /^-\s+\*\*/.test(l))
    .map(l => l.replace(/^#+\s*/, '').replace(/^-\s*/, '').replace(/\*\*/g, '').trim())
    .slice(0, 14);
  return ['Convention contract (AGENTS.md):', ...rules.map(r => `- ${r}`)].join('\n');
}
