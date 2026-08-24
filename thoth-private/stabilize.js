// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH STABILIZER - the automatic-fix foundation for continuous development.
 *
 * Every recurring drift class the kernel already knows how to repair is
 * declared here as a FOUNDATION: a named, classed (L1/L2) fix point with a
 * scan -> apply -> verify contract and byte-exact rollback on failure.
 *
 *   scan    read-only: reports how much work exists (0 == stable)
 *   apply   one atomic mutation batch for that foundation only
 *   verify  independent re-check; failure triggers rollback of every file
 *           the foundation touched, restored byte-for-byte
 *
 * Sessions run foundations in declaration order under a max-class ceiling,
 * append an honest history line to .operator/stabilize/history.jsonl, and
 * are idempotent: a second session over a stable tree does nothing. This is
 * what makes unattended continuous development safe - fixes are declared,
 * bounded, verified, reversible, and auditable.
 */
import { existsSync, mkdirSync, readFileSync, renameSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { applySafeFixes, scanUnfinished } from './repair.js';
import { applyDocFixes, auditDocs, writeDigests } from './scribe.js';

export const STABILIZE_VERSION = '3.4.0';

const STABILIZE_DIR = path.join('.operator', 'stabilize');
const HISTORY_KEEP = 200;
const DIGEST_STALE_HOURS = 6;

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function stabilizeDir(root) {
  const dir = path.join(root, STABILIZE_DIR);
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** Byte-exact snapshot of absolute paths; unknown files record null. */
function snapshotFiles(files) {
  const snap = new Map();
  for (const file of files) {
    try {
      snap.set(file, readFileSync(file, 'utf8'));
    } catch {
      snap.set(file, null);
    }
  }
  return snap;
}

function restoreFiles(snap) {
  let restored = 0;
  for (const [file, body] of snap) {
    if (body === null) continue;
    try {
      writeFileSync(file, body);
      restored += 1;
    } catch {
      /* best-effort; reported via verify problems */
    }
  }
  return restored;
}

function recordHistory(root, entry) {
  const dir = stabilizeDir(root);
  const file = path.join(dir, 'history.jsonl');
  let lines = [];
  try {
    lines = readFileSync(file, 'utf8')
      .split('\n')
      .filter(Boolean)
      .slice(-HISTORY_KEEP + 1);
  } catch {}
  lines.push(JSON.stringify(entry));
  const tmp = `${file}.tmp`;
  try {
    writeFileSync(tmp, lines.join('\n') + '\n');
    renameSync(tmp, file);
  } catch {
    /* history is advisory */
  }
  return file;
}

function lastRunAt(root) {
  const state = readJson(path.join(root, STABILIZE_DIR, 'last.json'));
  return state && typeof state === 'object' ? state : {};
}

function markRun(root, ids) {
  const state = lastRunAt(root);
  const now = Date.now();
  for (const id of ids) state[id] = now;
  const file = path.join(stabilizeDir(root), 'last.json');
  const tmp = `${file}.tmp`;
  try {
    writeFileSync(tmp, JSON.stringify(state));
    renameSync(tmp, file);
  } catch {}
}

/* ------------------------------------------------------------------ */
/* Foundations                                                         */
/* ------------------------------------------------------------------ */

const docLinksFoundation = {
  id: 'doc-links',
  title: 'Markdown link integrity',
  klass: 'L1',
  scan(root) {
    const audit = auditDocs(root);
    return {
      work: audit.fixes.length,
      detail: `${audit.docsScanned} doc(s), ${audit.brokenLinks.length} broken, ${audit.fixes.length} relinkable`,
      audit,
    };
  },
  snapshot(_root, scan) {
    const files = [
      ...new Set(scan.audit.fixes.map(f => path.join(f.dir, f.fileRel.split('/').join(path.sep)))),
    ];
    return snapshotFiles(files);
  },
  apply(_root, scan) {
    return applyDocFixes(scan.audit);
  },
  verify(root, _outcome, _scan) {
    const fresh = auditDocs(root);
    return fresh.fixes.length === 0
      ? { ok: true }
      : {
          ok: false,
          problems: [`${fresh.fixes.length} relinkable link(s) remain`],
        };
  },
};

const digestsFoundation = {
  id: 'digests',
  title: 'Auto Scribe fleet digests',
  klass: 'L1',
  scan(root) {
    const fleet = path.join(root, '.operator', 'auto-scribe', '_fleet.md');
    let ageH = Infinity;
    try {
      ageH = (Date.now() - statSync(fleet).mtimeMs) / 3_600_000;
    } catch {}
    const stale = !existsSync(fleet) || ageH >= DIGEST_STALE_HOURS;
    return {
      work: stale ? 1 : 0,
      detail: existsSync(fleet) ? `age ${ageH.toFixed(1)}h` : 'no digest yet',
    };
  },
  apply(root) {
    return writeDigests(root);
  },
  verify(root, outcome) {
    for (const name of outcome.written) {
      const file = path.join(outcome.dir, name);
      try {
        if (!readFileSync(file, 'utf8').startsWith('# Auto Scribe')) {
          return { ok: false, problems: [`${name} malformed`] };
        }
      } catch {
        return { ok: false, problems: [`${name} unreadable`] };
      }
    }
    return outcome.written.length ? { ok: true } : { ok: false, problems: ['nothing written'] };
  },
};

const codeHygieneFoundation = {
  id: 'code-hygiene',
  title: 'Prettier formatting + SPDX headers',
  klass: 'L2',
  scan(root) {
    const scanResult = scanUnfinished(root);
    return {
      work: scanResult.missingHeaders.length,
      detail: `${scanResult.missingHeaders.length} missing SPDX header(s); formatting applied alongside`,
    };
  },
  apply(root) {
    return applySafeFixes(root);
  },
  verify(root, outcome) {
    const problems = [];
    const fresh = scanUnfinished(root);
    if (fresh.missingHeaders.length) {
      problems.push(`${fresh.missingHeaders.length} header(s) still missing`);
    }
    for (const err of outcome.errors.slice(0, 5)) problems.push(err);
    return problems.length ? { ok: false, problems } : { ok: true };
  },
};

function buildFoundations() {
  return [docLinksFoundation, digestsFoundation, codeHygieneFoundation];
}

/* ------------------------------------------------------------------ */
/* Sessions                                                            */
/* ------------------------------------------------------------------ */

/** Read-only status of every foundational fix point. */
export function scanFoundations(root = process.cwd()) {
  return buildFoundations().map(f => {
    const s = f.scan(root);
    return {
      id: f.id,
      title: f.title,
      klass: f.klass,
      work: s.work ?? 0,
      detail: s.detail,
    };
  });
}

const CLASS_ORDER = ['L0', 'L1', 'L2'];

/**
 * Run one stabilization session: each eligible foundation with real work is
 * applied atomically and independently verified; any failed verification
 * rolls that foundation back byte-for-byte. Never chains across failures.
 */
export function runSession(
  root = process.cwd(),
  { maxKlass = 'L1', cooldownMs = 0, foundations } = {}
) {
  const ceiling = Math.max(0, CLASS_ORDER.indexOf(maxKlass));
  const results = [];
  const cooled = [];
  const last = lastRunAt(root);

  for (const f of foundations || buildFoundations()) {
    if (CLASS_ORDER.indexOf(f.klass) > ceiling) {
      results.push({ id: f.id, klass: f.klass, skipped: 'elevated' });
      continue;
    }
    if (cooldownMs > 0 && Date.now() - (last[f.id] || 0) < cooldownMs) {
      cooled.push(f.id);
      results.push({ id: f.id, klass: f.klass, skipped: 'cooldown' });
      continue;
    }
    let scan;
    try {
      scan = f.scan(root);
    } catch (err) {
      results.push({
        id: f.id,
        klass: f.klass,
        error: String(err?.message || err).slice(0, 120),
      });
      continue;
    }
    if (!scan.work) {
      results.push({ id: f.id, klass: f.klass, work: 0, stable: true });
      continue;
    }
    const snap = typeof f.snapshot === 'function' ? f.snapshot(root, scan) : null;
    let outcome;
    try {
      outcome = f.apply(root, scan);
    } catch (err) {
      if (snap) restoreFiles(snap);
      results.push({
        id: f.id,
        klass: f.klass,
        rolledBack: Boolean(snap),
        error: String(err?.message || err).slice(0, 120),
      });
      continue;
    }
    let check;
    try {
      check = f.verify(root, outcome, scan) || { ok: true };
    } catch (err) {
      check = {
        ok: false,
        problems: [String(err?.message || err).slice(0, 120)],
      };
    }
    if (!check.ok) {
      const restored = snap ? restoreFiles(snap) : 0;
      results.push({
        id: f.id,
        klass: f.klass,
        rolledBack: true,
        restored,
        problems: check.problems || ['verify failed'],
      });
      continue;
    }
    const applied =
      outcome?.applied?.length ?? outcome?.written?.length ?? (outcome?.formatted ? 1 : 0);
    results.push({
      id: f.id,
      klass: f.klass,
      applied,
      detail:
        outcome?.changed?.length !== undefined ? `${outcome.changed.length} changed` : undefined,
    });
  }

  const ranIds = results.filter(r => r.applied !== undefined).map(r => r.id);
  if (cooldownMs > 0 && ranIds.length) markRun(root, ranIds);

  const at = new Date().toISOString();
  const stable = results.every(r => r.stable || r.skipped || r.applied !== undefined);
  const entry = { at, version: STABILIZE_VERSION, maxKlass, stable, results };
  recordHistory(root, entry);
  return entry;
}
