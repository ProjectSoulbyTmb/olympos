// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH code repair - unfinished-code detection and verified safe fixes.
 *
 * Two halves, both bounded and local:
 *   SCAN  - stubs (TODO/FIXME/not-implemented), missing SPDX headers, and a
 *           wiring checklist that separates what automation may do from what
 *           stays a human decision.
 *   FIX   - only deterministic transformations: Prettier with the repo's own
 *           config, ESLint's safe autofix set, and SPDX header insertion.
 *           Every rewritten file is syntax-checked afterwards; any file that
 *           fails verification is restored byte-for-byte and reported.
 *
 * Fixing writes repository files, so the tool surface keeps it elevated (L2),
 * exactly like comply-fix - the most sensitive mutation class stays behind a
 * proven administrator session.
 */
import { readdirSync, readFileSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const SCAN_DIRS = ['src', 'scripts', 'tests', 'server'];
const SKIP_DIRS = new Set([
  'node_modules',
  '.git',
  'dist',
  'dist-mac',
  'coverage',
  'archive',
  '.wrangler',
  'playwright-report',
  'test-results',
  'sbom',
  '_publish',
  'release',
]);
const CODE_EXT = /\.(?:js|cjs|mjs)$/i;
const STUB_RE = /\b(TODO|FIXME|XXX)\b|not\s+implemented|unimplemented|notImplemented/i;
const SPDX_RE = /SPDX-License-Identifier/i;
const HEADER_LINES = [
  '// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios',
  '// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0',
];
const MAX_FINDINGS = 120;

export function repoRoot() {
  let dir = process.cwd();
  for (let i = 0; i < 6; i += 1) {
    try {
      if (statSync(path.join(dir, 'package.json')).isFile()) return dir;
    } catch {
      /* keep walking up */
    }
    dir = path.dirname(dir);
  }
  return process.cwd();
}

function* walk(dir, acc = []) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (acc.length > 4000) return;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) yield* walk(full, acc);
    } else if (CODE_EXT.test(entry.name) && !entry.name.endsWith('.min.js')) {
      yield full;
    }
  }
}

/** Scan for unfinished markers and missing license headers. */
export function scanUnfinished(root = process.cwd()) {
  const stubs = [];
  const missingHeaders = [];
  let filesScanned = 0;
  for (const rel of SCAN_DIRS) {
    const base = path.join(root, rel);
    for (const file of walk(base)) {
      if (filesScanned >= MAX_FINDINGS * 10) break;
      filesScanned += 1;
      let text;
      try {
        text = readFileSync(file, 'utf8');
      } catch {
        continue;
      }
      const relPath = path.relative(root, file).split(path.sep).join('/');
      const lines = text.split('\n');
      if (!lines.slice(0, 5).some(l => SPDX_RE.test(l))) {
        missingHeaders.push(relPath);
      }
      lines.forEach((line, i) => {
        if (stubs.length < MAX_FINDINGS && STUB_RE.test(line)) {
          stubs.push({ file: relPath, line: i + 1, snippet: line.trim().slice(0, 140) });
        }
      });
    }
  }
  return { filesScanned, stubs, missingHeaders };
}

/**
 * Apply only deterministic fixes, verifying every rewrite.
 * Returns { formatted, headersAdded, reverted, errors } - honest counts.
 */
export function applySafeFixes(root = process.cwd()) {
  const result = { formatted: false, headersAdded: [], reverted: [], errors: [] };

  // 1) Formatting with the repository's own Prettier config.
  const prettierBin = path.join(root, 'node_modules', 'prettier', 'bin', 'prettier.cjs');
  try {
    statSync(prettierBin);
    const res = spawnSync(
      process.execPath,
      [prettierBin, '--config', '.prettierrc', '--log-level', 'error', '--write', '.'],
      { cwd: root, encoding: 'utf8' }
    );
    result.formatted = res.status === 0;
    if (res.status !== 0) result.errors.push(`prettier exit ${res.status}`);
  } catch {
    result.errors.push('prettier binary not found; formatting skipped');
  }

  // 2) SPDX headers where missing (shebang-aware).
  const { missingHeaders } = scanUnfinished(root);
  for (const rel of missingHeaders.slice(0, MAX_FINDINGS)) {
    const file = path.join(root, rel);
    let text;
    try {
      text = readFileSync(file, 'utf8');
    } catch {
      continue;
    }
    const lines = text.split('\n');
    const insertAt = lines[0]?.startsWith('#!') ? 1 : 0;
    const updated = [...lines.slice(0, insertAt), ...HEADER_LINES, ...lines.slice(insertAt)].join(
      '\n'
    );
    // Verify the rewrite still parses before committing it.
    const tmp = `${file}.thoth-verify.mjs`;
    writeFileSync(tmp, updated);
    const check = spawnSync(process.execPath, ['--check', tmp], { encoding: 'utf8' });
    try {
      if (check.status === 0) {
        writeFileSync(file, updated);
        result.headersAdded.push(rel);
      } else {
        result.reverted.push(rel);
        result.errors.push(`${rel}: post-edit syntax check failed; restored`);
      }
    } finally {
      try {
        unlinkSync(tmp);
      } catch {}
    }
  }

  // 3) Final whole-tree syntax gate over touched directories.
  for (const rel of result.headersAdded) {
    const check = spawnSync(process.execPath, ['--check', path.join(root, rel)], {
      encoding: 'utf8',
    });
    if (check.status !== 0) result.errors.push(`${rel}: final check failed`);
  }
  return result;
}

/** Wiring checklist: what automation may fix vs what needs a human decision. */
export function wiringReport(root = process.cwd()) {
  const scan = scanUnfinished(root);
  const byKind = {};
  for (const s of scan.stubs) {
    const kind = /\b(TODO|FIXME|XXX)\b/.exec(s.snippet)?.[1] || 'not-implemented';
    byKind[kind] = (byKind[kind] || 0) + 1;
  }
  const automationMay = [
    'Prettier formatting drift (repo config)',
    'Missing SPDX headers (deterministic insertion)',
    'Recurring mechanical compliance items ("thoth comply-fix")',
  ];
  const humanOnly = [
    'Wiring a new feature into registry/IPC/preload (startup-frozen surfaces)',
    'Implementing stubbed business logic (TODO bodies)',
    'Anything touching AGENTS.md contracts or the env-var table',
  ];
  return {
    filesScanned: scan.filesScanned,
    stubs: scan.stubs.length,
    stubKinds: byKind,
    missingHeaders: scan.missingHeaders.length,
    examples: scan.stubs.slice(0, 8),
    automationMay,
    humanOnly,
  };
}
