import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { scoreSystem, discoverSystems } from '../gaia.mjs';

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
