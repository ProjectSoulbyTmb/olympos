import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  scoreSystem, discoverSystems, detectRegressions, freshAlerts, advise,
  planFixes, applyFix, diskVitals, trend,
} from '../gaia.mjs';

test('scoreSystem: fully healthy repo scores 100', () => {
  const { score, band } = scoreSystem({
    branch: 'main', synced: true, diverged: false, behind: 0, ahead: 0,
    dirty: 0, lastCommitAgeDays: 1,
  });
  assert.equal(score, 100);
  assert.equal(band, 'healthy');
});

test('scoreSystem: penalties accumulate and clamp to the floor', () => {
  const base = {
    branch: 'main', synced: false, diverged: true, behind: 9, ahead: 2,
    dirty: 25, lastCommitAgeDays: 120,
    net: { healthy: 0, degraded: 0, down: ['a', 'b'], offlineMode: true },
    mind: { fresh: false, ageSec: 7200 },
    thoth: { openIncidents: 3 },
  };
  const { score, band } = scoreSystem(base);
  assert.equal(score, 0);
  assert.equal(band, 'critical');

  const mid = scoreSystem({ ...base, diverged: false, synced: true,
                            dirty: 0, lastCommitAgeDays: 5,
                            net: null, mind: null,
                            thoth: { openIncidents: 1 } });
  assert.equal(mid.score, 84, `one open incident should land at 84, got ${mid.score}`);
  assert.equal(mid.band, 'watch');
});

test('scoreSystem: CI failure costs 20 points and is reported', () => {
  const ok = scoreSystem({ branch: 'main', synced: true, diverged: false,
                           behind: 0, dirty: 0, lastCommitAgeDays: 1, ci: 'success' });
  const bad = scoreSystem({ branch: 'main', synced: true, diverged: false,
                            behind: 0, dirty: 0, lastCommitAgeDays: 1, ci: 'failure' });
  assert.equal(ok.score - bad.score, 20);
  assert.ok(bad.reasons.some(r => /CI failing/.test(r)));
});

test('discoverSystems finds git-bearing siblings and skips noise', () => {
  const ws = fs.mkdtempSync(path.join(os.tmpdir(), 'gaia-ws-'));
  for (const name of ['alpha', 'beta', 'node_modules', '.hidden']) {
    fs.mkdirSync(path.join(ws, name), { recursive: true });
  }
  fs.mkdirSync(path.join(ws, 'alpha', '.git'), { recursive: true });
  fs.writeFileSync(path.join(ws, 'beta', 'file.txt'), 'no .git here');
  // GAIA's own folder must never appear as a system.
  const gaiaDir = path.join(ws, 'gaia');
  fs.mkdirSync(path.join(gaiaDir, '.git'), { recursive: true });

  const found = discoverSystems(ws).map(s => s.name);
  assert.deepEqual(found, ['alpha']);
  for (const d of [ws]) fs.rmSync(d, { recursive: true, force: true });
});

test('detectRegressions: flags score drops >=10 and band slides only', () => {
  const current = { composite: 80, systems: [
    { name: 'dropper', score: 60, band: 'watch' },
    { name: 'slider', score: 92, band: 'unwell' },
    { name: 'steady', score: 90, band: 'healthy' },
    { name: 'newcomer', score: 0, band: 'critical' },
    { name: 'nudge', score: 84, band: 'healthy' },
  ] };
  const previous = { composite: 88, systems: [
    { name: 'dropper', score: 75, band: 'watch' },
    { name: 'slider', score: 95, band: 'watch' },
    { name: 'steady', score: 90, band: 'healthy' },
    { name: 'gone', score: 50, band: 'watch' },
    { name: 'nudge', score: 88, band: 'healthy' },
  ] };
  const regs = detectRegressions(current, previous);
  assert.deepEqual(regs.map(r => r.system).sort(), ['dropper', 'slider']);
});

test('detectRegressions: sharp score drop and composite drop are caught', () => {
  const current = { composite: 70, systems: [
    { name: 'a', score: 60, band: 'watch' },
  ] };
  const previous = { composite: 88, systems: [
    { name: 'a', score: 75, band: 'watch' },
  ] };
  const regs = detectRegressions(current, previous);
  assert.ok(regs.some(r => r.system === 'a' && /score 75->60/.test(r.reasons.join('; '))));
  assert.ok(regs.some(r => r.system === 'ecosystem' && /composite 88->70/.test(r.reasons[0])));
});

test('detectRegressions: no previous history means no regressions', () => {
  assert.deepEqual(detectRegressions({ composite: 1, systems: [{ name: 'x', score: 1, band: 'critical' }] }, null), []);
});

test('freshAlerts: suppresses identical alerts inside cooldown window', () => {
  const now = Date.now();
  const alert = { severity: 'warning', system: 'thoth', reasons: ['mind stale'] };
  const recentLedger = `${JSON.stringify({ at: new Date(now - 5 * 60_000).toISOString(), ...alert })}\n`;
  assert.deepEqual(freshAlerts([alert], recentLedger, now), []);

  const oldLedger = `${JSON.stringify({ at: new Date(now - 2 * 60_60_000).toISOString(), ...alert })}\n`;
  assert.deepEqual(freshAlerts([alert], oldLedger, now), [alert]);

  const otherAlert = { ...alert, system: 'assistant' };
  assert.deepEqual(freshAlerts([otherAlert], recentLedger, now), [otherAlert]);
  assert.deepEqual(freshAlerts([alert], '', now), [alert]);

  const corrupt = 'not json at all\n';
  assert.deepEqual(freshAlerts([alert], corrupt, now), [alert]);
});

test('advise: maps every failing vital to a concrete action', () => {
  const dirty = advise({ branch: 'main', synced: false, diverged: true,
                         behind: 3, ahead: 2, dirty: 4, ci: 'failure',
                         net: { offlineMode: false, down: ['ge-api'] },
                         mind: { fresh: false, ageSec: 3_600_000 },
                         thoth: { openIncidents: 2 } });
  assert.ok(dirty.some(s => /pull --rebase/.test(s)));
  assert.ok(dirty.some(s => /commit or stash 4/.test(s)));
  assert.ok(dirty.some(s => /gh run view/.test(s)));
  assert.ok(dirty.some(s => /restore endpoints: ge-api/.test(s)));
  assert.ok(dirty.some(s => /MIND heartbeat stale 60m/.test(s)));
  assert.ok(dirty.some(s => /close 2 THOTH incident/.test(s)));

  const aheadOnly = advise({ branch: 'main', synced: false, diverged: false,
                             behind: 0, ahead: 1, dirty: 0 });
  assert.deepEqual(aheadOnly, ['git push (1 ahead)']);

  assert.deepEqual(advise({ gitError: true }), ['inspect repository access - git unreadable']);
  assert.deepEqual(advise({ repo: false, branch: undefined }), []);
});

test('scoreSystem: low disk headroom costs points and is reported', () => {
  const base = { branch: 'main', synced: true, diverged: false,
                 behind: 0, dirty: 0, lastCommitAgeDays: 1 };
  const fine = scoreSystem({ ...base, disk: { freePct: 40, freeGb: 200 } });
  const low = scoreSystem({ ...base, disk: { freePct: 8, freeGb: 30 } });
  const dire = scoreSystem({ ...base, disk: { freePct: 3, freeGb: 10 } });
  assert.equal(fine.score, 100);
  assert.equal(fine.score - low.score, 8);
  assert.equal(low.score - dire.score, 7);
  assert.ok(dire.reasons.some(r => /disk 3% free/.test(r)));
});

test('planFixes: only safe git drift is auto-fixable', () => {
  const behind = planFixes({ repo: true, dir: 'x', branch: 'main', synced: false,
                             diverged: false, behind: 5, ahead: 0 });
  assert.deepEqual(behind.map(s => s.args), [['pull', '--ff-only']]);

  const ahead = planFixes({ repo: true, dir: 'x', branch: 'main', synced: false,
                            diverged: false, behind: 0, ahead: 2, dirty: 0 });
  assert.deepEqual(ahead.map(s => s.args), [['push']]);

  // dirty tree must block push
  const aheadDirty = planFixes({ repo: true, dir: 'x', branch: 'main', synced: false,
                                 diverged: false, behind: 0, ahead: 2, dirty: 3 });
  assert.deepEqual(aheadDirty, []);

  // diverged is never touched
  const diverged = planFixes({ repo: true, dir: 'x', branch: 'main', synced: false,
                               diverged: true, behind: 3, ahead: 3, dirty: 0 });
  assert.deepEqual(diverged, []);

  assert.deepEqual(planFixes({ repo: false }), []);
  assert.deepEqual(planFixes({ gitError: true }), []);
});

test('applyFix: dry-run plans without touching the filesystem state', () => {
  const v = { repo: true, dir: 'nowhere-that-exists', branch: 'main', synced: false,
              diverged: false, behind: 2, ahead: 0 };
  const steps = applyFix(v, { dryRun: true });
  assert.equal(steps.length, 1);
  assert.equal(steps[0].result, 'planned');
});

test('applyFix: failed execution is reported, never thrown', () => {
  const bad = { repo: true, dir: path.join(os.tmpdir(), 'gaia-no-such-dir'),
                branch: 'main', synced: false, diverged: false,
                behind: 2, ahead: 0 };
  const steps = applyFix(bad, { dryRun: false }).filter(s => s.kind === 'git');
  assert.equal(steps.length, 1);
  assert.equal(steps[0].result, 'failed');
});

test('diskVitals: reports sane headroom for a real directory', () => {
  const d = diskVitals(os.tmpdir());
  assert.ok(d && d.freePct >= 0 && d.freePct <= 100, `unexpected ${JSON.stringify(d)}`);
  assert.ok(d.freeGb >= 0);
});

test('trend: missing history directory yields [] instead of crashing', () => {
  assert.deepEqual(trend(5, path.join(os.tmpdir(), 'gaia-no-runs-here')), []);
});

test('freshAlerts: corrupt or missing timestamps never suppress alerts', () => {
  const alert = { severity: 'warning', system: 'x', reasons: ['r'] };
  const ledger =
    `${JSON.stringify({ at: 'not-a-date', severity: 'warning', system: 'x', reasons: ['r'] })}\n` +
    `${JSON.stringify({ severity: 'warning', system: 'x', reasons: ['r'] })}\n`;
  assert.deepEqual(freshAlerts([alert], ledger, Date.now()), [alert]);
});

test('planFixes: unknown dirtiness conservatively blocks auto-push', () => {
  const steps = planFixes({ repo: true, dir: 'x', branch: 'main', synced: false,
                            diverged: false, behind: 0, ahead: 2, dirty: null });
  assert.deepEqual(steps, []);
});

test('scoreSystem: dirty null is treated as unknown, not penalized', () => {
  const { score, reasons } = scoreSystem({ branch: 'main', synced: true, diverged: false,
                                           behind: 0, dirty: null, lastCommitAgeDays: 1 });
  assert.equal(score, 100);
  assert.equal(reasons.length, 0);
});
