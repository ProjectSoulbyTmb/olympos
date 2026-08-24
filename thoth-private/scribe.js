// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH AUTO SCRIBE - the automated documentation service.
 *
 * Two bounded, deterministic halves covering every system the fleet sweep
 * can see (apps, repositories, website docs):
 *
 *   AUDIT (read-only)  - inventories first-party Markdown everywhere and
 *     verifies it against machine-checked facts: unknown "thoth <command>"
 *     references and broken relative document links. Report-only; prose is
 *     never rewritten by heuristic.
 *
 *   REWRITE (mutating) - performs the full document rewrite: regenerates
 *     `.operator/auto-scribe/<system>.md` digests plus a `_fleet.md` index
 *     from verified facts ONLY (identity, scripts, documents, network
 *     posture, topology roles, command registry), and applies exactly one
 *     class of mechanical fix: relinking a broken doc link when a unique
 *     same-basename target exists. Historical version mentions stay
 *     untouched - scribe corrects structure and generates truth; it does
 *     not improvise prose.
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { discoverSystems, systemEntry } from './federation.js';
import { FACTS, TOPOLOGY } from './wisdom.js';

export const SCRIBE_VERSION = '3.3.0';

const SKIP_DIRS = new Set([
  'node_modules',
  '.git',
  'dist',
  'dist-mac',
  'archive',
  '.wrangler',
  'playwright-report',
  'test-results',
  'sbom',
  '_publish',
  'release',
  'coverage',
  '__pycache__',
]);
const DOC_EXT = /\.md$/i;
const MAX_DOCS = 300;
const MAX_PER_SYSTEM = 120;
const MAX_BYTES = 400_000;
const MAX_DEPTH = 6;

// Kernel-surface words that are not registry tools but legitimately follow
// "thoth" in documentation (master is gate-handled; grant/revoke are panel
// actions). Anything else unknown is drift.
const COMMAND_ALLOWLIST = new Set(['grant', 'revoke', 'master']);
const MD_LINK_RE = /\[[^\]]*\]\(([^)\s]+\.md)\)/g;
const THOTH_CMD_RE = /\bthoth\s+:?([a-z][a-z0-9-]*)/gi;

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

/** Locate the kernel folder (installed inside the supervised repo or the
 *  canonical sibling) so audits verify against the live tool registry. */
export function kernelDir(root = process.cwd()) {
  const candidates = [
    path.join(root, 'src', 'features', 'thoth'),
    path.join(path.dirname(root), 'thoth-private'),
    path.join(root, 'thoth-private'),
  ];
  return candidates.find(dir => existsSync(path.join(dir, 'tools.js'))) || null;
}

export function thothVersion(root = process.cwd()) {
  const dir = kernelDir(root);
  if (!dir) return null;
  try {
    const m = /export const THOTH_VERSION = '([\d.]+)'/.exec(
      readFileSync(path.join(dir, 'index.js'), 'utf8')
    );
    return m ? m[1] : null;
  } catch {
    return null;
  }
}

/** The live command registry, parsed straight from tools.js. */
export function toolRegistry(root = process.cwd()) {
  const dir = kernelDir(root);
  if (!dir) return [];
  try {
    const text = readFileSync(path.join(dir, 'tools.js'), 'utf8');
    const tools = [];
    const re = /\n\s+name: '([a-z][a-z0-9-]*)',\n\s+klass: '(L[012])',/g;
    let m;
    while ((m = re.exec(text))) tools.push({ name: m[1], klass: m[2] });
    return tools;
  } catch {
    return [];
  }
}

function* walkDocs(dir, acc, budget) {
  if (budget.left <= 0 || acc.depth > MAX_DEPTH) return;
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (budget.left <= 0) return;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name.startsWith('.') || SKIP_DIRS.has(entry.name)) continue;
      acc.depth += 1;
      yield* walkDocs(full, acc, budget);
      acc.depth -= 1;
    } else if (DOC_EXT.test(entry.name)) {
      try {
        if (statSync(full).size > MAX_BYTES) continue;
      } catch {
        continue;
      }
      budget.left -= 1;
      yield full;
    }
  }
}

/** Nested application manifests inside one system (bounded, deterministic). */
function discoverApps(systemDir, { excludeRoot = false } = {}) {
  const apps = [];
  const walk = (dir, depth) => {
    if (depth > 4 || apps.length >= 20) return;
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (apps.length >= 20) return;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name.startsWith('.') || SKIP_DIRS.has(entry.name)) continue;
        walk(full, depth + 1);
      } else if (entry.name === 'package.json') {
        const relDir = path.relative(systemDir, dir).split(path.sep).join('/');
        if (excludeRoot && relDir === '') continue;
        const pkg = readJson(full);
        if (!pkg?.name) continue;
        apps.push({
          dir: relDir || '.',
          name: String(pkg.name),
          version: typeof pkg.version === 'string' ? pkg.version : null,
          description: typeof pkg.description === 'string' ? pkg.description : null,
          main: typeof pkg.main === 'string' ? pkg.main : null,
          scripts: Object.keys(pkg.scripts || {}).sort(),
        });
      }
    }
  };
  walk(systemDir, 0);
  apps.sort((a, b) => a.dir.localeCompare(b.dir));
  return apps;
}

/** Verified facts for one discovered system. Read-only, fail-open. */
function systemFacts(system) {
  const entry = systemEntry(system);
  const facts = {
    name: entry.name,
    self: entry.self,
    dir: system.dir,
    kinds: entry.kinds,
    attention: entry.attention,
    net: entry.net,
    version: entry.version ?? null,
    description: null,
    license: null,
    repository: null,
    main: null,
    scripts: [],
    docs: [],
    apps: [],
    role: TOPOLOGY.find(t => t.name === entry.name)?.role || null,
  };
  const pkg = readJson(path.join(system.dir, 'package.json'));
  if (pkg) {
    facts.description = typeof pkg.description === 'string' ? pkg.description : null;
    facts.license = typeof pkg.license === 'string' ? pkg.license : null;
    facts.main = typeof pkg.main === 'string' ? pkg.main : null;
    facts.repository =
      typeof pkg.repository === 'string'
        ? pkg.repository
        : typeof pkg.repository?.url === 'string'
          ? pkg.repository.url
          : null;
    facts.scripts = Object.keys(pkg.scripts || {}).sort();
  }
  const budget = { left: MAX_PER_SYSTEM };
  for (const file of walkDocs(system.dir, { depth: 0 }, budget)) {
    let bytes = 0;
    try {
      bytes = statSync(file).size;
    } catch {}
    facts.docs.push({
      file: path.relative(system.dir, file).split(path.sep).join('/'),
      bytes,
    });
  }
  facts.apps = discoverApps(system.dir, { excludeRoot: Boolean(pkg) });
  return facts;
}

/**
 * Fleet-wide verified inventory: every system the sweep can see with app,
 * repository, document, network, and topology facts - plus the live THOTH
 * registry and environment facts. This is the input both audit and rewrite
 * render from, so they can never disagree.
 */
export function scribeInventory(root = process.cwd()) {
  const systems = discoverSystems(root)
    .slice(0, 24)
    .map(systemFacts)
    .sort((a, b) => Number(b.self) - Number(a.self) || a.name.localeCompare(b.name));
  return {
    at: new Date().toISOString(),
    generator: `auto-scribe v${SCRIBE_VERSION}`,
    thothVersion: thothVersion(root),
    tools: toolRegistry(root),
    environment: {
      soulProvider: FACTS.soulProvider.endpoint,
      models: FACTS.soulProvider.models,
      scheduledTasks: FACTS.scheduledTasks,
      artifacts: FACTS.artifacts,
    },
    systems,
  };
}

/** Audit every first-party Markdown document across self + siblings. */
export function auditDocs(root = process.cwd()) {
  const inv = scribeInventory(root);
  const knownCommands = new Set([
    ...inv.tools.map(t => t.name),
    ...COMMAND_ALLOWLIST,
  ]);
  const allDocPaths = new Set();
  for (const system of inv.systems) {
    for (const doc of system.docs) {
      allDocPaths.add(path.join(system.dir, doc.file.split('/').join(path.sep)));
    }
  }

  const unknownCommands = [];
  const brokenLinks = [];
  const fixes = [];
  let docsScanned = 0;

  for (const system of inv.systems) {
    const systemBasenames = new Map();
    for (const doc of system.docs) {
      const base = path.basename(doc.file).toLowerCase();
      if (!systemBasenames.has(base)) systemBasenames.set(base, doc.file);
      else systemBasenames.set(base, null); // ambiguous target: no mechanical fix
    }
    for (const doc of system.docs) {
      if (docsScanned >= MAX_DOCS) break;
      const file = path.join(system.dir, doc.file.split('/').join(path.sep));
      let text;
      try {
        text = readFileSync(file, 'utf8');
      } catch {
        continue;
      }
      docsScanned += 1;
      const lines = text.split('\n');
      lines.forEach((line, i) => {
        THOTH_CMD_RE.lastIndex = 0;
        let m;
        while ((m = THOTH_CMD_RE.exec(line))) {
          const word = m[1].toLowerCase();
          const next = line[m.index + m[0].length];
          if (next === '<' || next === '|') continue; // placeholder syntax
          if (!knownCommands.has(word)) {
            unknownCommands.push({
              kind: 'unknown-command',
              file: `${system.name}/${doc.file}`,
              line: i + 1,
              detail: `"thoth ${word}" is not in the live registry`,
            });
          }
        }
        MD_LINK_RE.lastIndex = 0;
        while ((m = MD_LINK_RE.exec(line))) {
          const raw = m[1];
          if (/^[a-z]+:/i.test(raw) || raw.startsWith('#')) continue;
          const target = path.resolve(path.dirname(file), raw.split('/').join(path.sep));
          if (allDocPaths.has(target) || existsSync(target)) continue;
          const unique = systemBasenames.get(path.basename(raw).toLowerCase());
          const record = {
            kind: 'broken-link',
            file: `${system.name}/${doc.file}`,
            line: i + 1,
            detail: `"${raw}" does not resolve`,
            fix: unique
              ? {
                  system: system.name,
                  dir: system.dir,
                  fileRel: doc.file,
                  find: `(${raw})`,
                  to: unique,
                }
              : null,
          };
          brokenLinks.push(record);
          if (record.fix) fixes.push(record.fix);
        }
      });
    }
  }

  return {
    at: inv.at,
    docsScanned,
    systems: inv.systems.length,
    unknownCommands,
    brokenLinks,
    fixes,
  };
}

/**
 * Apply the audit's unambiguous mechanical fixes: a broken link is relinked
 * only when exactly one same-basename document exists in the same system.
 * Exact-string replacement, applied only on a single occurrence.
 */
export function applyDocFixes(audit) {
  const applied = [];
  const skipped = [];
  for (const fix of audit.fixes.slice(0, 50)) {
    const file = path.join(fix.dir, fix.fileRel.split('/').join(path.sep));
    let text;
    try {
      text = readFileSync(file, 'utf8');
    } catch {
      skipped.push(fix.fileRel);
      continue;
    }
    if (!existsSync(path.join(fix.dir, fix.to.split('/').join(path.sep)))) {
      skipped.push(fix.fileRel);
      continue;
    }
    const targetAbs = path.join(fix.dir, fix.to.split('/').join(path.sep));
    let rel = path.relative(path.dirname(file), targetAbs).split(path.sep).join('/');
    if (!rel.startsWith('.')) rel = `./${rel}`;
    const find = fix.find;
    if (text.split(find).length !== 2) {
      skipped.push(fix.fileRel); // zero or multiple occurrences: refuse
      continue;
    }
    try {
      writeFileSync(file, text.replace(find, `(${rel})`));
      applied.push(`${fix.fileRel}: ${find} -> (${rel})`);
    } catch {
      skipped.push(fix.fileRel);
    }
  }
  return { applied, skipped };
}

const bytes = n => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`);

function renderSystem(facts) {
  const lines = [
    `# Auto Scribe - ${facts.name}`,
    '',
    `_Generated ${facts.at} by THOTH ${facts.generator}. Every fact below was verified locally; nothing is invented._`,
    '',
    '## Identity',
    `- kinds: ${facts.kinds.join(' + ') || 'unknown'}`,
    `- version: ${facts.version || '(no package.json)'}`,
    `- description: ${facts.description || '(none)'}`,
    `- license: ${facts.license || '(unspecified)'}`,
    `- repository: ${facts.repository || '(none)'}`,
    `- main entry: ${facts.main || '(none)'}`,
    facts.role ? `- topology role: ${facts.role}` : null,
    '',
    `## Scripts (${facts.scripts.length})`,
    facts.scripts.length ? facts.scripts.map(s => `- ${s}`).join('\n') : '(none)',
    '',
    `## Documents (${facts.docs.length})`,
    facts.docs.length
      ? facts.docs.map(d => `- ${d.file} (${bytes(d.bytes)})`).join('\n')
      : '(none)',
  ];
  if (facts.net) {
    lines.push(
      '',
      '## Network posture',
      `- healthy: ${facts.net.healthy ?? '?'} | degraded: ${facts.net.degraded ?? 0} | down: ${facts.net.down}`,
      facts.net.downNames.length ? `- down endpoints: ${facts.net.downNames.join(', ')}` : null,
      `- offline mode: ${facts.net.offlineMode ? 'YES' : 'no'}`
    );
  }
  lines.push(
    '',
    '## Attention',
    facts.attention.length ? facts.attention.map(a => `- ${a}`).join('\n') : '(none)',
    ''
  );
  return lines.filter(l => l !== null).join('\n');
}

function renderFleet(inv) {
  const totalDocs = inv.systems.reduce((sum, s) => sum + s.docs.length, 0);
  const rows = inv.tools.map(t => `| \`${t.name}\` | ${t.klass} |`).join('\n');
  return [
    '# Auto Scribe - fleet index',
    '',
    `_Generated ${inv.at} by THOTH ${inv.generator}. Verified local facts only._`,
    '',
    `Systems: ${inv.systems.length} | documents inventoried: ${totalDocs} | THOTH kernel v${inv.thothVersion || '?'}`,
    '',
    '## Systems',
    inv.systems
      .map(s => {
        const flag = s.attention.length ? ' !' : '';
        const ver = s.version ? ` v${s.version}` : '';
        return `- [${s.name}${flag}](${encodeURIComponent(s.name)}.md)${ver} - ${
          s.description || s.kinds.join('+') || 'unknown'
        }`;
      })
      .join('\n'),
    '',
    `## THOTH command registry (${inv.tools.length})`,
    '| command | class |',
    '| ------- | ----- |',
    rows,
    '',
    '## Environment facts',
    `- soul provider: ${inv.environment.soulProvider} (${inv.environment.models.join(', ')})`,
    `- scheduled tasks: ${inv.environment.scheduledTasks.join(' | ')}`,
    `- learning artifacts: ${Object.values(inv.environment.artifacts).join(', ')}`,
    '',
  ].join('\n');
}

/**
 * The full document rewrite: regenerate every digest + the fleet index from
 * verified inventory. Atomic writes; reports which files changed content.
 */
export function writeDigests(root = process.cwd()) {
  const inv = scribeInventory(root);
  const dir = path.join(root, '.operator', 'auto-scribe');
  mkdirSync(dir, { recursive: true });
  const written = [];
  const changed = [];

  const emit = (name, body) => {
    const file = path.join(dir, name);
    let previous = null;
    try {
      previous = readFileSync(file, 'utf8');
    } catch {}
    if (previous !== body) changed.push(name);
    const tmp = `${file}.tmp`;
    try {
      writeFileSync(tmp, body);
      renameSync(tmp, file);
      written.push(name);
    } catch {
      try {
        if (existsSync(tmp)) renameSync(tmp, file);
      } catch {}
    }
  };

  for (const facts of inv.systems) {
    emit(`${facts.name}.md`, renderSystem({ ...facts, at: inv.at, generator: inv.generator }));
  }
  emit('_fleet.md', renderFleet(inv));

  return { at: inv.at, dir, written, changed };
}
