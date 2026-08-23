// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH feature descriptor. Self-registers through core/feature-registry.js
 * when this folder exists on disk; the app runs identically without it.
 *
 * The kernel is an operator surface, not a personality: it never claims
 * intents that belong to other features and only exposes its own "thoth"
 * intent plus a dashboard module for discoverability.
 */
import { attachToEngine } from './kernel.js';
import { knowledge } from './knowledge.js';
import { createRelay } from './relay.js';

export const THOTH_VERSION = '2.7.0';

export const thothFeature = {
  id: 'thoth',
  intents: ['thoth'],
  consent: null,
  moduleInsertAfter: 'dev-tools',
  moduleDefinitions: [
    {
      id: 'thoth-console',
      title: 'THOTH console',
      summary: `Private local operator kernel v${THOTH_VERSION}: doctor, grants, backups, focus, memory tools.`,
      intents: ['thoth'],
      commands: ['thoth help', 'thoth status', 'thoth doctor', 'thoth backups'],
      workspace: 'dashboard',
      ui: { view: 'dashboard' },
    },
  ],
  actionsForIntent: intent =>
    intent === 'thoth'
      ? [{ type: 'open-view', view: 'dashboard', label: 'Open dashboard console', auto: false }]
      : undefined,
  handleIntent({ intent }) {
    if (intent !== 'thoth') return undefined;
    // Conversation phrasing falls through to the same parser the IPC uses so
    // chat and operator surface can never drift apart.
    return undefined;
  },
  schemaDefaults: {
    thoth: { masterEnabled: true, grants: {} },
  },
  migrations: [],
  api: {
    version: THOTH_VERSION,
    attachToEngine,
    createRelay,
    knowledge,
  },
};
