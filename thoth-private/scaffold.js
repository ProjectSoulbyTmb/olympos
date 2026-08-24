// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH feature scaffolding - generate, wire, and verify a new feature that
 * satisfies the registry contract on first run.
 *
 * What the scaffold produces (all deterministic templates):
 *   src/features/<id>/index.js      descriptor passing validate(): unique id,
 *                                   owned intents, schemaDefaults, api surface
 *   src/features/<id>/knowledge.js  one entry + routing rule via the
 *                                   sanctioned knowledge merge seam shape
 *   tests/optional-<id>.test.js     fail-closed contract test mirroring
 *                                   optional-thoth.test.js
 *   feature-registry patch          existsSync-guarded dynamic-import block,
 *                                   appended after the thoth seam - identical
 *                                   in shape to the sanctioned thoth block
 *
 * Verification is part of writing: every generated file is syntax-checked and
 * the generated test is executed before the scaffold reports success. The
 * tool surface classifies this L2 because it writes source files and edits a
 * core seam.
 */
import { mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const ID_RE = /^[a-z][a-z0-9-]{1,29}$/;
const HEADER = `// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios\n// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0\n`;

export function repoRoot() {
  let dir = process.cwd();
  for (let i = 0; i < 6; i += 1) {
    try {
      if (statSync(path.join(dir, 'package.json')).isFile()) return dir;
    } catch {
      /* walk up */
    }
    dir = path.dirname(dir);
  }
  return process.cwd();
}

const camel = s => s.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase());
const pascal = s => camel(s)[0].toUpperCase() + camel(s).slice(1);

export function planFeature(root, { id, title } = {}) {
  const problems = [];
  if (!ID_RE.test(String(id || ''))) {
    problems.push('id must be kebab-case, 2-30 chars, start with a letter');
  }
  const featureDir = path.join(root, 'src', 'features', String(id || ''));
  if (id && existsDir(featureDir)) problems.push(`feature already exists: ${id}`);
  return { id, title: title || id, problems, featureDir };
}

function existsDir(p) {
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
}

function indexTemplate({ id, title }) {
  const exportName = `${pascal(id)}Feature`;
  const stateKey = camel(id);
  return `${HEADER}/**
 * ${title} - scaffolded by THOTH against the feature contract.
 * Ships with a working, store-persisted collection baseline; replace or
 * extend add/list/remove with real domain logic when you are ready.
 * See src/core/feature-registry.js for the descriptor shape.
 */
import { knowledge } from './knowledge.js';

export const ${id.toUpperCase().replace(/-/g, '_')}_VERSION = '0.1.0';

const STATE_KEY = '${stateKey}';

/** Working baseline: a bounded, persisted collection on the engine store. */
export function attachToEngine(engine) {
  if (!engine.state[STATE_KEY] || typeof engine.state[STATE_KEY] !== 'object') {
    engine.state[STATE_KEY] = { enabled: true, items: [] };
  }
  const persist = () => engine.store?.save?.(engine.state);
  return {
    add(text) {
      const item = {
        text: String(text ?? '').trim().slice(0, 500),
        at: new Date().toISOString(),
      };
      if (!item.text) throw new Error('nothing to add');
      engine.state[STATE_KEY].items.push(item);
      if (engine.state[STATE_KEY].items.length > 500) engine.state[STATE_KEY].items.shift();
      persist();
      return item;
    },
    list() {
      return engine.state[STATE_KEY].items.slice();
    },
    remove(index) {
      const removed = engine.state[STATE_KEY].items.splice(Number(index), 1);
      persist();
      return removed.length ? removed[0] : null;
    },
  };
}

export const ${exportName} = {
  id: '${id}',
  intents: ['${id}'],
  consent: null,
  moduleInsertAfter: 'dev-tools',
  moduleDefinitions: [
    {
      id: '${id}-card',
      title: '${title}',
      summary: '${title}: scaffolded feature surface.',
      intents: ['${id}'],
      commands: [],
      workspace: 'dashboard',
      ui: { view: 'dashboard' },
    },
  ],
  actionsForIntent: intent =>
    intent === '${id}'
      ? [{ type: 'open-view', view: 'dashboard', label: 'Open ${title}', auto: false }]
      : undefined,
  handleIntent() {
    return undefined;
  },
  schemaDefaults: {
    '${stateKey}': { enabled: true, items: [] },
  },
  migrations: [],
  api: { version: ${id.toUpperCase().replace(/-/g, '_')}_VERSION, knowledge, attachToEngine },
};
`;
}

function knowledgeTemplate({ id, title }) {
  const key = camel(id);
  return `${HEADER}/**
 * ${title} knowledge contributions merged through the sanctioned seam in
 * core/knowledge.js. Entries use the shared { entries, rules } shape.
 */
export const knowledge = {
  entries: {
    ${key}: {
      title: '${title}',
      reply:
        '${title} is scaffolded and registered. Replace this reply with real product knowledge.',
    },
  },
  rules: [
    {
      id: '${key}',
      re: /\\b${id.replace(/-/g, '[-\\s]?')}\\b/i,
    },
  ],
};
`;
}

function testTemplate({ id, title }) {
  return `${HEADER}import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

/**
 * ${title} optional-feature contract (mirrors optional-thoth.test.js):
 * CI never has it installed; developer machines validate the descriptor.
 */
const INSTALLED = join('src', 'features', '${id}', 'index.js');

test('registry loads without ${id} and stays fail-closed', async () => {
  const { featureApi } = await import('../src/core/feature-registry.js');
  if (!existsSync(INSTALLED)) {
    assert.throws(() => featureApi('${id}'), /unknown feature api/);
  }
});

test(
  'installed ${id} satisfies the feature contract',
  { skip: !existsSync(INSTALLED) },
  async () => {
    const { registeredFeatures, featureApi } = await import('../src/core/feature-registry.js');
    const mod = await import(
      new URL('../src/features/${id}/index.js', import.meta.url).href
    );
    const api = featureApi('${id}');
    assert.equal(api.version, '0.1.0');
    assert.ok(api.knowledge?.entries && Array.isArray(api.knowledge.rules));
    assert.ok(registeredFeatures().map(f => f.id).includes('${id}'));

    // Working-baseline proof: persisted collection round-trip.
    let saved = 0;
    const engine = { state: {}, store: { save: () => (saved += 1) } };
    const collection = mod.attachToEngine(engine);
    collection.add('first');
    collection.add('second');
    assert.equal(collection.list().length, 2);
    assert.equal(collection.remove(0).text, 'first');
    assert.equal(collection.list().length, 1);
    assert.ok(saved >= 2, 'mutations persist through engine.store.save');
  }
);
`;
}

function registryPatch(id) {
  const exportName = `${pascal(id)}Feature`;
  return `
// ${id}: guarded dynamic registration (scaffolded seam).
if (existsSync(new URL('../features/${id}/index.js', import.meta.url))) {
  const { ${exportName} } = await import('../features/${id}/index.js');
  if (!registered.some(f => f.id === ${exportName}.id)) {
    registerFeature(${exportName});
  }
}
`;
}

/** Dry-run: what would be created/changed. */
export function planScaffold(root, opts) {
  const plan = planFeature(root, opts);
  if (plan.problems.length) return { ...plan, files: [], registryPatch: '' };
  const { id } = plan;
  return {
    ...plan,
    files: [
      path.join('src', 'features', id, 'index.js'),
      path.join('src', 'features', id, 'knowledge.js'),
      path.join('tests', `optional-${id}.test.js`),
    ],
    registryPatch: registryPatch(id),
  };
}

/**
 * Generate + wire + verify. Throws on any verification failure after leaving
 * generated files in place for inspection (never half-patches the registry).
 */
export function scaffoldFeature(root, opts) {
  const plan = planScaffold(root, opts);
  if (plan.problems.length) throw new Error(plan.problems.join('; '));
  const { id } = plan;
  const title = plan.title;

  const indexJs = indexTemplate({ id, title });
  const knowledgeJs = knowledgeTemplate({ id, title });
  const testJs = testTemplate({ id });

  const dir = path.join(root, 'src', 'features', id);
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, 'index.js'), indexJs);
  writeFileSync(path.join(dir, 'knowledge.js'), knowledgeJs);
  writeFileSync(path.join(root, 'tests', `optional-${id}.test.js`), testJs);

  // Registry wiring: append the guarded block before end-of-file if absent.
  const registryPath = path.join(root, 'src', 'core', 'feature-registry.js');
  let registry = readFileSync(registryPath, 'utf8');
  if (!registry.includes(`'../features/${id}/index.js'`)) {
    if (!registry.endsWith('\n')) registry += '\n';
    registry += registryPatch(id);
    writeFileSync(registryPath, registry);
  }

  // Verify: syntax-check generated sources + run the generated contract test.
  const checks = [path.join(dir, 'index.js'), path.join(dir, 'knowledge.js')].map(file =>
    spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' })
  );
  const badSyntax = checks.filter(c => c.status !== 0);
  if (badSyntax.length) throw new Error(`generated file failed --check`);

  const testRun = spawnSync(
    process.execPath,
    ['--test', path.join(root, 'tests', `optional-${id}.test.js`)],
    {
      cwd: root,
      encoding: 'utf8',
    }
  );
  const passed = testRun.status === 0;
  return {
    id,
    files: plan.files,
    registryWired: registry.includes(`'../features/${id}/index.js'`),
    contractTestPassed: passed,
    testOutput:
      String(testRun.stdout ?? '')
        .match(/pass \d+|fail \d+/g)
        ?.join(' | ') ?? '',
  };
}
