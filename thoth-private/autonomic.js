// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH autonomic loop - one heartbeat over the sanctioned rails.
 *
 * Every tick runs the full observe -> learn -> match -> act chain:
 *   1. fleet sweep + incident reconciliation (federation.js)
 *   2. learning reconciliation (learn.js)
 *   3. playbook matching (wisdom.js)
 *   4. at most ONE permitted action - a step whose tool holds an active
 *      class right now (L0 always, L1 via live standing grant). Elevated
 *      and human-marked steps are never executed by the loop.
 *   5. idle ticks (no playbook action) hand their one permitted action to
 *      AUTO SCRIBE (scribe-write, L1) so documentation stays truthful.
 *
 * The loop honors the master switch exactly like manual invocation, emits
 * every decision through the relay, and is bounded: one action per tick,
 * no chaining, no improvisation beyond matched playbooks.
 */
import { incidents, reconcileIncidents } from './federation.js';
import { observeFromSweeps } from './learn.js';
import { adviseFor } from './wisdom.js';

const DEFAULT_INTERVAL_MIN = 15;
const MIN_INTERVAL_MIN = 5;

/** Live timers per engine so stopAuto can cancel a pending tick cleanly. */
const timers = new WeakMap();

function ensureAutoState(engine) {
  const thoth = engine.state.thoth || (engine.state.thoth = {});
  if (!thoth.auto || typeof thoth.auto !== 'object') {
    thoth.auto = {
      enabled: false,
      intervalMin: DEFAULT_INTERVAL_MIN,
      lastTickAt: null,
      lastAction: null,
      ticks: 0,
    };
  }
  return thoth.auto;
}

function normalizeInterval(value) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return DEFAULT_INTERVAL_MIN;
  return Math.max(MIN_INTERVAL_MIN, Math.min(240, n));
}

/** One full observe -> learn -> match -> act cycle. Pure-ish and testable. */
export async function runTick(engine, kernel, { relay } = {}) {
  const auto = ensureAutoState(engine);
  if (engine.state.thoth?.masterEnabled === false) {
    return { skipped: 'master-disabled', at: new Date().toISOString() };
  }
  const emit = (type, payload) => {
    try {
      relay?.emit(type, payload);
    } catch {
      /* relay failures never block the loop */
    }
  };

  const report = incidents(process.cwd());
  const ledger = reconcileIncidents(process.cwd(), report);
  const history = engine.state.thoth?.design?.lastAudit?.history;
  const learning = observeFromSweeps(process.cwd(), {
    incidentsReport: report,
    ledger,
    auditHistory: Array.isArray(history) ? history : [],
  });
  const matches = adviseFor(report);

  let action = null;
  const granted = new Map((kernel?.listTools() || []).map(tool => [tool.name, tool.granted]));
  if (matches.length) {
    outer: for (const { playbook } of matches) {
      for (const step of playbook.steps) {
        const toolName = /"thoth\s+(\w+)/.exec(step.text)?.[1];
        if (step.human || !toolName || !granted.get(toolName)) continue;
        const result = await kernel.handleCommand({ tool: toolName, args: '' }, {});
        action = {
          playbook: playbook.id,
          tool: toolName,
          ok: result.ok === true,
          reply: String(result.reply ?? '').slice(0, 300),
        };
        break outer;
      }
    }
  }
  // Idle-tick rail: when no playbook needs this tick's single permitted
  // action, AUTO SCRIBE may spend it - keeping every digest and doc link
  // truthful - but only while its standing grant is live. Same one-action
  // bound, same grant depth as everything else.
  if (!action && granted.get('scribe-write')) {
    try {
      const result = await kernel.handleCommand({ tool: 'scribe-write', args: '' }, {});
      if (result.ok) {
        action = {
          playbook: 'auto-scribe',
          tool: 'scribe-write',
          ok: true,
          reply: String(result.reply ?? '').slice(0, 300),
        };
      }
    } catch {
      /* scribe failures never break the tick */
    }
  }

  auto.lastTickAt = new Date().toISOString();
  auto.ticks += 1;
  auto.lastAction = action;
  try {
    engine.store.save(engine.state);
  } catch {
    /* persistence is best-effort inside the tick */
  }

  const summary = {
    at: auto.lastTickAt,
    incidents: report.count,
    learned: learning.learned,
    refreshed: learning.refreshed.length,
    playbooks: matches.map(m => m.playbook.id),
    action,
  };
  emit('autonomic', {
    ...summary,
    announce: Boolean(action) || report.count > 0,
    text: action
      ? `Autonomic tick: applied ${action.playbook} step (${action.tool}).`
      : report.count > 0
        ? `Autonomic tick: ${report.count} incident(s) observed; no permitted action needed.`
        : 'Autonomic tick: fleet quiet.',
  });
  return summary;
}

export function startAuto(engine, kernel, { relay, intervalMin } = {}) {
  const auto = ensureAutoState(engine);
  if (auto.enabled && timers.has(engine)) return false;
  auto.enabled = true;
  if (intervalMin) auto.intervalMin = normalizeInterval(intervalMin);
  const delay = auto.intervalMin * 60 * 1000;

  const schedule = () => {
    const timer = setTimeout(async () => {
      try {
        await runTick(engine, kernel, { relay });
      } catch {
        /* honest silence until next tick */
      } finally {
        if (ensureAutoState(engine).enabled) schedule();
      }
    }, delay);
    timer.unref?.();
    timers.set(engine, timer);
  };
  schedule();
  return true;
}

export function stopAuto(engine) {
  const auto = ensureAutoState(engine);
  const was = auto.enabled;
  auto.enabled = false;
  const timer = timers.get(engine);
  if (timer) {
    clearTimeout(timer);
    timers.delete(engine);
  }
  return was;
}

export function autoStatus(engine) {
  const auto = ensureAutoState(engine);
  return { ...auto };
}
