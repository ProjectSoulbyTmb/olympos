// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH private operator kernel.
 *
 * Canonical source lives in ../thoth-private; this installed copy is
 * intentionally untracked (see .gitignore and feature-registry.js). The
 * kernel attaches to the public engine surface only - no core imports beyond
 * release facts and network-governance status snapshots.
 *
 * Tool classes at the process boundary:
 *   L0  read-only, always allowed while the master switch is on
 *   L1  mutating but workspace-scoped; requires a standing grant (renderer
 *       can hold these through the admin panel)
 *   L2  elevated/destructive; NEVER grantable from the renderer. Runs only
 *       when the main process proves an administrator session for that call.
 */
import { buildTools } from './tools.js';

const GRANTABLE_CLASSES = new Set(['L0', 'L1']);
const COMMAND_PREFIX = /^(?:thoth|\/thoth|\/t|operator)\b[\s:,-]*/i;

function emptyState() {
  return {
    masterEnabled: true,
    grants: {},
    adminMode: false,
    adminUsage: [],
    creative: { ideas: [], drafts: [], themes: [], appliedTheme: null },
  };
}

function coerceState(raw) {
  const state = raw && typeof raw === 'object' ? raw : {};
  if (typeof state.masterEnabled !== 'boolean') state.masterEnabled = true;
  if (!state.grants || typeof state.grants !== 'object' || Array.isArray(state.grants)) {
    state.grants = {};
  }
  for (const key of Object.keys(state.grants)) {
    if (!GRANTABLE_CLASSES.has(state.grants[key])) delete state.grants[key];
  }
  return state;
}

export function attachToEngine(engine, { relay } = {}) {
  const tools = buildTools();
  const byName = new Map(tools.map(tool => [tool.name, tool]));

  if (!engine.state.thoth || typeof engine.state.thoth !== 'object') {
    engine.state.thoth = emptyState();
  }
  const thothState = coerceState(engine.state.thoth);
  thothState.attachedAt = Date.now();
  if (!thothState.creative || typeof thothState.creative !== 'object') {
    thothState.creative = { ideas: [], drafts: [], themes: [], appliedTheme: null };
  }
  engine.state.thoth = thothState;

  const persist = () => engine.store.save(engine.state);

  const emit = (type, payload) => {
    try {
      relay?.emit(type, payload);
    } catch {
      /* relay failures never block kernel work */
    }
  };

  // Autonomy: before any elevated destructive tool runs, take a safety
  // backup (throttled) so an admin mistake is always reversible locally.
  const DESTRUCTIVE = new Set(['restore', 'reset']);
  const SAFETY_BACKUP_COOLDOWN_MS = 5 * 60 * 1000;
  async function safetyBackup(toolName) {
    if (!DESTRUCTIVE.has(toolName)) return null;
    const last = thothState.lastSafetyBackupAt || 0;
    if (Date.now() - last < SAFETY_BACKUP_COOLDOWN_MS) {
      return { skipped: true, reason: 'recent safety backup exists' };
    }
    let name;
    try {
      const created = engine.createBackup();
      name = typeof created === 'string' ? created : created?.name || 'auto-safety';
    } catch (err) {
      return { failed: true, reason: String(err?.message || err).slice(0, 120) };
    }
    thothState.lastSafetyBackupAt = Date.now();
    return { created: name };
  }

  function grantedClass(name) {
    return thothState.grants[name] || null;
  }

  function effectiveClass(tool) {
    // L2 is per-call elevated only; standing grants top out at L1.
    return tool.klass === 'L2' ? null : grantedClass(tool.name) || (tool.klass === 'L0' ? 'L0' : null);
  }

  const kernel = {
    get state() {
      return thothState;
    },

    get relay() {
      return relay || null;
    },

    listTools() {
      return tools.map(tool => ({
        name: tool.name,
        klass: tool.klass,
        summary: tool.summary,
        usage: tool.usage,
        granted: effectiveClass(tool),
      }));
    },

    meta() {
      return {
        attachedAt: thothState.attachedAt,
        masterEnabled: thothState.masterEnabled !== false,
        grants: { ...thothState.grants },
        adminMode: Boolean(thothState.adminMode),
        adminUsageCount: (thothState.adminUsage || []).length,
        watch: Boolean(thothState.design?.watch),
        lastAuditAt: thothState.design?.lastAudit?.at || null,
        findings: thothState.design?.lastAudit ? thothState.design.lastAudit.counts : null,
        lastSafetyBackupAt: thothState.lastSafetyBackupAt || null,
      };
    },

    attachRelay(relay) {
      try {
        relay?.bindKernel(kernel);
        relay?.emit('attached', { tools: tools.length });
      } catch {
        /* optional */
      }
      return kernel;
    },

    /* Break-glass autonomy: administrators may arm session-scoped elevation
       so L2 operations run without per-call confirmation. Arming requires an
       admin-authorized context; disarming is always allowed; usage stays
       persisted + relay-audited. */
    setAdminMode(on, { adminAuthorized } = {}) {
      if (on && !adminAuthorized) {
        return { ok: false, error: 'admin-required' };
      }
      thothState.adminMode = Boolean(on);
      if (!on) {
        thothState.adminMode = false;
      }
      persist();
      emit('admin-mode', { on: thothState.adminMode });
      return { ok: true, adminMode: thothState.adminMode };
    },

    matchInvocation(text) {
      const raw = String(text || '').trim();
      const stripped = raw.replace(COMMAND_PREFIX, '');
      if (!stripped || stripped === raw) return null;
      const parts = stripped.split(/\s+/).filter(Boolean);
      if (!parts.length) return null;
      const name = parts[0].toLowerCase().replace(/[?!.]+$/, '');
      if (!byName.has(name)) return null;
      return { tool: name, args: parts.slice(1).join(' ') };
    },

    async handleCommand(parsed, ctx = {}) {
      const adminAuthorized = ctx.adminAuthorized === true;
      const replyOf = text => ({ ok: true, reply: String(text).slice(0, 2000) });

      if (parsed?.tool === 'master') {
        if (!adminAuthorized) {
          return replyOf('The master switch is administrator-only (Ctrl+A, away from text fields).');
        }
        const arg = String(parsed.args || '').toLowerCase();
        const enable = ['on', 'enable', 'true', 'resume'].includes(arg);
        const disable = ['off', 'disable', 'false', 'pause'].includes(arg);
        if (!enable && !disable) {
          return replyOf(`Master is ${thothState.masterEnabled ? 'ON' : 'OFF'}. Use "thoth master on|off".`);
        }
        thothState.masterEnabled = enable;
        persist();
        return replyOf(`THOTH master ${enable ? 'enabled' : 'disabled'}.`);
      }

      if (!thothState.masterEnabled) {
        return {
          ok: false,
          error: 'master-disabled',
          reply: 'THOTH is paused. An administrator can resume it with "thoth master on".',
        };
      }

      const tool = byName.get(parsed?.tool);
      if (!tool) return kernel.handleCommand({ tool: 'help', args: '' }, ctx);

      if (tool.klass === 'L2') {
        // Session-scoped elevation: an administrator may arm THOTH so L2
        // tools run for the duration of THIS admin session without per-call
        // confirmation. Every such run is still safety-backed and relay-
        // audited, and the mode dies with the admin session.
        if (!adminAuthorized && !thothState.adminMode) {
          return {
            ok: false,
            error: 'elevated-required',
            reply: `"${tool.name}" is elevated-only. Re-run it from an authorized administrator session.`,
          };
        }
        const safety = await safetyBackup(tool.name);
        if (safety?.failed) {
          return {
            ok: false,
            error: 'safety-backup-failed',
            reply: `Refusing "${tool.name}": automatic safety backup failed (${safety.reason}).`,
          };
        }
      } else if (!effectiveClass(tool)) {
        return {
          ok: false,
          error: 'grant-required',
          reply:
            `"${tool.name}" needs a standing grant first. ` +
            `Ask the administrator panel for: thoth grant ${tool.name} ${tool.klass}.`,
        };
      }

      try {
        const out = await tool.run(engine, parsed.args ?? '', { adminAuthorized }, byName, kernel);
        persist();
        const result =
          typeof out === 'string'
            ? replyOf(out)
            : { ok: true, data: out?.data, reply: String(out.reply ?? '').slice(0, 2000) };
        const elevated = tool.klass === 'L2';
        if (elevated && thothState.adminMode) {
          thothState.adminUsage = [
            { tool: tool.name, at: Date.now() },
            ...(thothState.adminUsage || []),
          ].slice(0, 25);
          persist();
        }
        emit('command', {
          tool: tool.name,
          ok: result.ok,
          klass: tool.klass,
          elevated: elevated && (thothState.adminMode || adminAuthorized),
        });
        return result;
      } catch (err) {
        emit('command', { tool: tool.name, ok: false, error: true, klass: tool.klass });
        return {
          ok: false,
          error: 'tool-failed',
          reply: `"${tool.name}" failed honestly: ${String(err?.message || err).slice(0, 160)}`,
        };
      }
    },

    grant(toolName, klass) {
      const tool = byName.get(String(toolName || '').toLowerCase());
      if (!tool) throw new Error(`unknown tool: ${toolName}`);
      if (klass === null) {
        delete thothState.grants[tool.name];
        persist();
        emit('grant', { tool: tool.name, granted: null });
        return { tool: tool.name, granted: null };
      }
      const wanted = String(klass || '').toUpperCase();
      if (!GRANTABLE_CLASSES.has(wanted)) throw new Error(`class not grantable: ${klass}`);
      if (tool.klass === 'L2') throw new Error(`${tool.name} is elevated-only and can never be granted`);
      if (wanted !== 'L0' && wanted !== 'L1') throw new Error(`bad class: ${klass}`);
      if (tool.klass === 'L1' && wanted === 'L0') throw new Error(`${tool.name} requires L1`);
      thothState.grants[tool.name] = wanted;
      persist();
      emit('grant', { tool: tool.name, granted: wanted });
      return { tool: tool.name, granted: wanted };
    },
  };

  // Safety-backup autonomy announcements ride the same relay.
  const originalHandleCommand = kernel.handleCommand.bind(kernel);
  kernel.handleCommand = async (parsed, ctx) => {
    const result = await originalHandleCommand(parsed, ctx);
    if (
      result.ok &&
      parsed?.tool &&
      DESTRUCTIVE.has(parsed.tool) &&
      thothState.lastSafetyBackupAt
    ) {
      emit('safety', {
        tool: parsed.tool,
        at: new Date(thothState.lastSafetyBackupAt).toISOString(),
      });
    }
    return result;
  };

  return kernel;
}
