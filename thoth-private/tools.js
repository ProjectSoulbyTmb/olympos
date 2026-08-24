// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH tool registry. Every handler sticks to the engine's public methods;
 * nothing here reaches into core internals. Handlers return a reply string.
 */
import { execFile } from 'node:child_process';
import path from 'node:path';
import { SOURCE_VERSION, INSTALLER_NAME } from '../../core/release.js';
import {
  auditNow,
  startWatch,
  stopWatch,
  goalsStatus,
  nextActions,
  trends,
  regressionReport,
} from './design.js';
import { deriveIdeas, draftChangelogFromGit, buildTheme } from './creative.js';
import { explainFile, findSymbol, conventions } from './intel.js';
import { fleetStatus, incidents, reconcileIncidents } from './federation.js';
import { observeFromSweeps, summarize, teach, unteach } from './learn.js';
import { ESCALATION, FACTS, TOPOLOGY, adviseFor } from './wisdom.js';
import { autoStatus, runTick, startAuto, stopAuto } from './autonomic.js';
import { applySafeFixes, scanUnfinished, wiringReport } from './repair.js';
import { planScaffold, scaffoldFeature } from './scaffold.js';

async function complianceScanner() {
  const root = process.cwd();
  const url = new URL(`file:///${root.split(path.sep).join('/')}/scripts/compliance-scan.mjs`);
  return import(url.href);
}

const clip = (text, max = 1600) => String(text).slice(0, max);
const list = items => (items.length ? items.map(item => `- ${item}`).join('\n') : '(none)');

function providerKind(engine) {
  const name = engine?.provider?.constructor?.name || 'unknown';
  return name.replace(/Provider$/, '').toLowerCase();
}

function netSummary(engine) {
  const opts = engine?.internetOptions || {};
  return `internet: ${Object.keys(opts).length ? JSON.stringify(opts) : 'defaults'}`;
}

export function buildTools() {
  const tools = [
    {
      name: 'help',
      klass: 'L0',
      summary: 'List THOTH commands and the grant each one needs.',
      usage: 'thoth help [command]',
      run(engine, args, ctx, all) {
        const wanted = String(args || '')
          .toLowerCase()
          .trim();
        if (wanted && wanted !== 'all') {
          const tool = all.get(wanted);
          if (!tool) return `No such command: ${wanted}`;
          return `${tool.name} (${tool.klass}) - ${tool.summary}\nusage: ${tool.usage}`;
        }
        const lines = [...all.values()].map(
          tool => `${tool.name.padEnd(10)} ${tool.klass}  ${tool.summary}`
        );
        return [
          'THOTH operator console - local only, nothing is sent anywhere.',
          'Classes: L0 read-only | L1 needs standing grant | L2 admin-session per call.',
          '',
          ...lines,
          '',
          'Grants: "thoth grant <name> L1" via the admin panel; revoke with "thoth grant <name>" cleared.',
        ].join('\n');
      },
    },
    {
      name: 'status',
      klass: 'L0',
      summary: 'Kernel snapshot: modules, focus, funnel, scratchpad, autonomy posture.',
      usage: 'thoth status',
      run(engine) {
        const raw = engine.kernelStatus();
        let snap;
        try {
          snap = typeof raw === 'string' ? JSON.parse(raw) : raw;
        } catch {
          snap = { kernelStatus: String(raw).slice(0, 200) };
        }
        const grants = Object.values(engine.state.thoth?.grants || {}).filter(
          klass => klass === 'L1'
        ).length;
        const auto = engine.state.thoth?.auto || {};
        return clip(
          JSON.stringify(
            {
              ...(snap && typeof snap === 'object' ? snap : { kernelStatus: snap }),
              autonomy: {
                standingL1Grants: grants,
                autonomicLoop: auto.enabled ? 'ON' : 'OFF',
                lastAutonomicTick: auto.lastTickAt,
                lastAutonomicAction: auto.lastAction
                  ? `${auto.lastAction.playbook} -> ${auto.lastAction.tool}`
                  : null,
              },
            },
            null,
            2
          )
        );
      },
    },
    {
      name: 'version',
      klass: 'L0',
      summary: 'Exact release facts compiled into this installation.',
      usage: 'thoth version',
      run() {
        return `Eidovara source v${SOURCE_VERSION}; installer ${INSTALLER_NAME}. THOTH kernel attached. Local facts only.`;
      },
    },
    {
      name: 'doctor',
      klass: 'L0',
      summary: 'Aggregate health: provider, internet options, backups, memory counts.',
      usage: 'thoth doctor',
      run(engine) {
        const state = engine.snapshot();
        const backups = engine.listBackups();
        const memories = Array.isArray(state.memories) ? state.memories.length : 0;
        const conversations = Array.isArray(state.conversations) ? state.conversations.length : 0;
        return [
          `provider: ${providerKind(engine)}`,
          netSummary(engine),
          `memories: ${memories} | conversations: ${conversations} | backups: ${backups.length}`,
          `scratchpad: ${state.scratchpad ? `${String(state.scratchpad).length} chars` : 'empty'}`,
          `focus: ${state.focusSession ? 'active' : 'idle'}`,
          'store: reachable (this reply proves it)',
        ].join('\n');
      },
    },

    {
      name: 'fleet',
      klass: 'L0',
      summary: 'Fleet rollup: every sibling system MIND or git manages, with network posture.',
      usage: 'thoth fleet',
      run() {
        const fleet = fleetStatus(process.cwd());
        if (!fleet.managed && !fleet.attention) {
          return `Fleet: ${fleet.systems} system(s), none MIND-managed. `;
        }
        const rows = fleet.entries.map(entry => {
          const net = entry.net
            ? `net ${entry.net.healthy ?? '?'} ok / ${entry.net.down} down`
            : entry.kinds.join('+') || 'unknown';
          const flag = entry.attention.length ? ' !' : '';
          return `- ${entry.name}${flag}: ${net}`;
        });
        return [
          `Fleet: ${fleet.systems} systems, ${fleet.managed} MIND-managed, ` +
            `${fleet.attention} need attention.`,
          ...rows,
        ].join('\n');
      },
    },
    {
      name: 'incidents',
      klass: 'L0',
      summary: 'Correlated cross-system incidents with MTTR memory (--all adds resolved).',
      usage: 'thoth incidents [--all]',
      run(engine, args) {
        const showAll = /\b--all\b/.test(String(args || ''));
        const report = incidents(process.cwd());
        const ledger = reconcileIncidents(process.cwd(), report);
        // Automatic learning: every sweep reconciles durable facts.
        try {
          observeFromSweeps(process.cwd(), { incidentsReport: report, ledger });
        } catch {
          /* learning is advisory */
        }
        if (!report.count)
          return (
            'No open incidents across the fleet.' +
            (ledger.mttr
              ? `\nMTTR so far: median ${ledger.mttr.medianMinutes}m ` +
                `over ${ledger.mttr.count} resolved` +
                ` (worst ${ledger.mttr.worstMinutes}m).`
              : '')
          );
        const lines = report.incidents.map(
          incident =>
            `[${incident.severity}] ${incident.system}:\n` +
            incident.items.map(item => `  - ${item}`).join('\n')
        );
        let mttrLine = '';
        if (ledger.mttr)
          mttrLine =
            `\n\nMTTR: median ${ledger.mttr.medianMinutes}m over ` +
            `${ledger.mttr.count} resolved (worst ${ledger.mttr.worstMinutes}m).`;
        let closedLine = '';
        if (showAll && ledger.recentlyClosed.length)
          closedLine =
            '\n\nRecently closed:\n' +
            ledger.recentlyClosed
              .map(r => `  - [resolved ${r.mttrMinutes}m] ${r.system}: ` + r.items.join('; '))
              .join('\n');
        const base = `Incidents (${report.count}):\n${lines.join('\n')}` + mttrLine + closedLine;
        const advice = adviseFor(report);
        const adviceLine = advice.length
          ? `\n\nAdvised playbooks: ${advice
              .map(m => m.playbook.title)
              .join(', ')}. Run "thoth advise --apply" for guided remediation.`
          : '';
        return base + adviceLine;
      },
    },
    {
      name: 'advise',
      klass: 'L0',
      summary:
        'Playbook advice for live incidents; --apply runs the first step your standing grants allow.',
      usage: 'thoth advise [--apply]',
      async run(engine, args, _ctx, _all, kernel) {
        const apply = /--apply\b/.test(String(args || ''));
        const report = incidents(process.cwd());
        const matches = adviseFor(report);
        if (!matches.length) {
          return report.count
            ? `No playbook matches ${report.count} incident(s); judgment required.`
            : 'No open incidents - nothing to advise on.';
        }
        const granted = new Map((kernel?.listTools() || []).map(tool => [tool.name, tool.granted]));
        const blocks = [];
        for (const { playbook } of matches) {
          const lines = [`${playbook.title}:`, `  ${playbook.diagnosis}`];
          for (const step of playbook.steps) {
            const toolName = /"thoth\s+(\w+)/.exec(step.text)?.[1];
            const runnable =
              !step.human && step.klass === 'L0' && toolName && granted.has(toolName);
            const mark = step.human ? '[human]' : runnable ? '[auto-ok]' : `[${step.klass}]`;
            lines.push(`  ${mark} ${step.text}`);
          }
          blocks.push(lines.join('\n'));
        }
        if (apply) {
          for (const { playbook } of matches) {
            for (const step of playbook.steps) {
              const toolName = /"thoth\s+(\w+)/.exec(step.text)?.[1];
              // Sanctioned automation: a step runs only while its tool holds
              // an active class (L0 always, L1 via live standing grant).
              if (step.human || !toolName || !granted.get(toolName)) continue;
              const result = await kernel.handleCommand({ tool: toolName, args: '' }, {});
              return `Applied "${playbook.title}" first permitted step (${toolName}):\n${result.reply}`;
            }
          }
          return 'No auto-runnable step in the matched playbooks - everything needs you.';
        }
        return `${blocks.join('\n\n')}\n\nEscalation: ${ESCALATION.map(
          rule => `${rule.severity}=>${rule.automation.split(';')[0]}`
        ).join('; ')}. Re-run with --apply to execute the first step your grants allow.`;
      },
    },
    {
      name: 'topology',
      klass: 'L0',
      summary: 'Workspace map: supervised systems, integration seams, verified environment facts.',
      usage: 'thoth topology',
      run() {
        const systems = TOPOLOGY.map(
          system => `- ${system.name}${system.managed ? ' (supervised)' : ''}: ${system.role}`
        );
        const facts = [
          `Soul provider: ${FACTS.soulProvider.service} at ${FACTS.soulProvider.endpoint} (${FACTS.soulProvider.models.join(', ')})`,
          `Kernel sync: ${FACTS.canonicalSync.source} -> ${FACTS.canonicalSync.installed}`,
          `Writer lane: ${FACTS.writerLanes.lockdir}`,
          `Scheduled: ${FACTS.scheduledTasks.join(' | ')}`,
          `Learning artifacts: ${Object.values(FACTS.artifacts).join(', ')}`,
        ];
        return `TOPOLOGY\n${systems.join('\n')}\n\nENVIRONMENT\n${facts
          .map(f => `- ${f}`)
          .join('\n')}`;
      },
    },
    {
      name: 'auto',
      klass: 'L1',
      summary: 'Autonomic loop: observe -> learn -> advise -> apply one permitted action per tick.',
      usage: 'thoth auto on|off|status|tick [minutes]',
      async run(engine, args, _ctx, _all, kernel) {
        const parts = String(args || '')
          .toLowerCase()
          .trim()
          .split(/\s+/)
          .filter(Boolean);
        const verb = parts[0] || 'status';
        if (verb === 'on') {
          const started = startAuto(engine, kernel, {
            relay: kernel?.relay,
            intervalMin: parts[1],
          });
          const interval = autoStatus(engine).intervalMin;
          return started
            ? `Autonomic loop enabled (every ${interval} min): fleet sweep, learning, playbook match, at most one permitted action per tick.`
            : 'Autonomic loop is already running.';
        }
        if (verb === 'off') {
          return stopAuto(engine)
            ? 'Autonomic loop disabled. Manual tools stay available.'
            : 'Autonomic loop was already off.';
        }
        if (verb === 'tick') {
          const result = await runTick(engine, kernel, { relay: kernel?.relay });
          return `Tick complete:\n${JSON.stringify(result, null, 2).slice(0, 1200)}`;
        }
        const s = autoStatus(engine);
        return `Autonomic loop: ${s.enabled ? 'ON' : 'OFF'} | every ${s.intervalMin} min | ticks ${s.ticks}${s.lastTickAt ? ` | last ${s.lastTickAt}` : ''}${s.lastAction ? ` | last action ${s.lastAction.playbook} -> ${s.lastAction.tool}` : ''}`;
      },
    },
    {
      name: 'repair',
      klass: 'L0',
      summary: 'Unfinished-code scan; --fix applies verified mechanical repairs (elevated).',
      usage: 'thoth repair [--fix]',
      run(engine, args) {
        if (/\b--fix\b/.test(String(args || ''))) {
          // Elevated path: re-enter through the gate so the class is enforced.
          return {
            reply: 'Use "thoth repair --fix" through an administrator session.',
            data: null,
          };
        }
        const scan = scanUnfinished(process.cwd());
        return (
          `Scan: ${scan.filesScanned} files | stubs ${scan.stubs.length} | missing SPDX headers ${scan.missingHeaders.length}\n` +
          (scan.stubs.length
            ? scan.stubs
                .slice(0, 5)
                .map(s => `- ${s.file}:${s.line}: ${s.snippet}`)
                .join('\n')
            : '- no unfinished markers') +
          `\nApply verified fixes with: thoth repair --fix (administrator session)`
        );
      },
    },
    {
      name: 'repair-fix',
      klass: 'L2',
      summary: 'Apply deterministic code repairs (prettier + SPDX), syntax-verified per file.',
      usage: 'thoth repair-fix',
      run(engine) {
        const result = applySafeFixes(process.cwd());
        engine.store.save(engine.state);
        return [
          `Formatted: ${result.formatted ? 'yes' : 'no'}`,
          `SPDX headers added: ${result.headersAdded.length}${result.headersAdded.length ? ` (${result.headersAdded.slice(0, 6).join(', ')})` : ''}`,
          `Reverted after failed verification: ${result.reverted.length}`,
          result.errors.length ? `Errors: ${result.errors.join(' | ')}` : 'No errors.',
        ].join('\n');
      },
    },
    {
      name: 'wire',
      klass: 'L0',
      summary: 'Wiring checklist: what automation may fix vs what needs a human decision.',
      usage: 'thoth wire',
      run() {
        const r = wiringReport(process.cwd());
        return [
          `Wiring report - ${r.filesScanned} files scanned, ${r.stubs} stub marker(s), ${r.missingHeaders} missing header(s)`,
          r.examples.length
            ? `Examples:\n${r.examples.map(e => `  - ${e.file}:${e.line}`).join('\n')}`
            : '  - clean',
          `Automation may fix: ${r.automationMay.join('; ')}`,
          `Human-only: ${r.humanOnly.join('; ')}`,
        ].join('\n');
      },
    },
    {
      name: 'scaffold',
      klass: 'L2',
      summary: 'Scaffold a contract-complete feature (descriptor, knowledge, test, registry seam).',
      usage: 'thoth scaffold <id> [title] [--write]',
      run(engine, args) {
        const parts = String(args || '').trim();
        const write = /--write\b/.test(parts);
        const cleaned = parts.replace(/--write\b/, '').trim();
        const m =
          /^(?<id>[a-z][a-z0-9-]*)(?:\s+"(?<t1>[^"]+)"|\s+'(?<t2>[^']+)'|\s+(?<t3>.+))?$/.exec(
            cleaned
          );
        if (!m?.groups?.id) {
          return 'Usage: thoth scaffold <id> ["Title"] [--write]. Dry-run by default.';
        }
        const opts = {
          id: m.groups.id,
          title: (m.groups.t1 || m.groups.t2 || m.groups.t3 || '').trim(),
        };
        if (!write) {
          const plan = planScaffold(process.cwd(), opts);
          if (plan.problems.length) return `Cannot scaffold: ${plan.problems.join('; ')}`;
          return [
            `Plan for feature "${plan.id}" (${plan.title}):`,
            ...plan.files.map(f => `  + ${f}`),
            '  ~ src/core/feature-registry.js (guarded dynamic-import seam)',
            'Re-run with --write inside an administrator session to generate, wire, and verify.',
          ].join('\n');
        }
        const result = scaffoldFeature(process.cwd(), opts);
        engine.store.save(engine.state);
        return [
          `Scaffolded "${result.id}" and wired the guarded registry seam.`,
          `Contract test: ${result.contractTestPassed ? 'PASSED' : 'FAILED'} (${result.testOutput})`,
          result.files.map(f => `  + ${f}`).join('\n'),
        ].join('\n');
      },
    },
    {
      name: 'learn',
      klass: 'L0',
      summary: 'What THOTH has learned from sweeps, usage, and your teaching.',
      usage: 'thoth learn',
      run(engine) {
        const history = engine.state.thoth?.design?.lastAudit?.history;
        const result = observeFromSweeps(process.cwd(), {
          incidentsReport: incidents(process.cwd()),
          ledger: undefined,
          auditHistory: Array.isArray(history) ? history : [],
        });
        const digest = summarize(process.cwd());
        let head = `Known facts (${digest.count})`;
        if (result.learned || result.expired || result.refreshed.length) {
          head +=
            ` - this sweep: +${result.learned} new` +
            `, ${result.refreshed.length} refreshed` +
            (result.expired ? `, ${result.expired} expired` : '');
        }
        return `${head}:\n${digest.text}`;
      },
    },
    {
      name: 'teach',
      klass: 'L1',
      summary: 'Teach THOTH a durable fact (persisted until you remove it).',
      usage: 'thoth teach <fact>',
      run(_engine, args) {
        const fact = teach(process.cwd(), args);
        return `Learned permanently: ${fact.statement}`;
      },
    },
    {
      name: 'unteach',
      klass: 'L1',
      summary: 'Remove taught facts matching the given text.',
      usage: 'thoth unteach <text>',
      run(_engine, args) {
        const removed = unteach(process.cwd(), args);
        return removed
          ? `Removed ${removed} taught fact(s).`
          : `No taught fact matches "${clip(args, 80)}".`;
      },
    },
    {
      name: 'net',
      klass: 'L0',
      summary: 'Show the network options this session will honor.',
      usage: 'thoth net',
      run(engine) {
        return `Outbound policy for this session:\n${netSummary(engine)}\nConversations never leave this PC unless you connected a provider yourself.`;
      },
    },
    {
      name: 'search',
      klass: 'L0',
      summary: 'Search the local workspace (modules, notes, memories).',
      usage: 'thoth search <query>',
      run(engine, args) {
        const query = String(args || '').trim();
        if (!query) return 'Give me something to search: "thoth search backup".';
        const hits = engine.searchWorkspace(query) || {};
        const flat = [];
        for (const [key, value] of Object.entries(hits)) {
          const count = Array.isArray(value) ? value.length : value ? 1 : 0;
          if (count) flat.push(`${key}: ${count}`);
        }
        return flat.length
          ? `Workspace hits for "${query}":\n${flat.join('\n')}`
          : `Nothing in the workspace matches "${query}".`;
      },
    },
    {
      name: 'palette',
      klass: 'L0',
      summary: 'Command palette entries, optionally filtered.',
      usage: 'thoth palette [query]',
      run(engine, args) {
        const query = String(args || '').trim();
        const items = engine.paletteItems(query) || [];
        return clip(
          `Palette${query ? ` ~ "${query}"` : ''}:\n${list(items.slice(0, 12).map(i => i.label || i.id || String(i)))}`
        );
      },
    },
    {
      name: 'explain',
      klass: 'L0',
      summary: 'Explain the last assistant reply (routing + knowledge used).',
      usage: 'thoth explain',
      run(engine) {
        try {
          const why = engine.explainLastReply();
          return clip(JSON.stringify(why, null, 2));
        } catch {
          return 'Nothing to explain yet - send a message first.';
        }
      },
    },
    {
      name: 'backups',
      klass: 'L0',
      summary: 'List stored profile backups.',
      usage: 'thoth backups',
      run(engine) {
        const rows = (engine.listBackups() || []).map(b =>
          typeof b === 'string' ? b : `${b.name || b.file} (${b.bytes ?? '?'} bytes)`
        );
        return `Backups:\n${list(rows)}`;
      },
    },
    {
      name: 'remember',
      klass: 'L1',
      summary: 'Save a durable memory into the local profile.',
      usage: 'thoth remember <text>',
      run(engine, args) {
        const text = String(args || '').trim();
        if (!text) return 'Usage: thoth remember <text>';
        engine.remember(text, { source: 'thoth' });
        return `Remembered locally: "${clip(text, 120)}"`;
      },
    },
    {
      name: 'forget',
      klass: 'L2',
      summary: 'Delete matching memories (elevated).',
      usage: 'thoth forget <id-or-text>',
      run(engine, args) {
        const target = String(args || '').trim();
        if (!target) return 'Usage: thoth forget <id-or-text>';
        engine.forget(target);
        return `Forget requested for "${clip(target, 80)}".`;
      },
    },
    {
      name: 'scratch',
      klass: 'L1',
      summary: 'Replace the scratchpad text.',
      usage: 'thoth scratch <text>',
      run(engine, args) {
        const text = String(args || '');
        if (!text.trim()) return 'Usage: thoth scratch <text> ("capture" archives instead)';
        engine.saveScratchpad(text);
        return 'Scratchpad saved.';
      },
    },
    {
      name: 'capture',
      klass: 'L1',
      summary: 'Archive the current scratchpad into memory.',
      usage: 'thoth capture',
      run(engine) {
        engine.captureScratchpad({ source: 'thoth' });
        return 'Scratchpad captured into memory.';
      },
    },
    {
      name: 'focus',
      klass: 'L1',
      summary: 'Start or stop a focus session.',
      usage: 'thoth focus start [minutes] | thoth focus stop',
      run(engine, args) {
        const parts = String(args || '')
          .toLowerCase()
          .split(/\s+/)
          .filter(Boolean);
        const verb = parts[0] || 'start';
        if (verb === 'stop') {
          engine.stopFocusSession();
          return 'Focus session stopped.';
        }
        const minutes = Number(parts[1]) > 0 ? Number(parts[1]) : undefined;
        engine.startFocusSession(minutes ? { minutes } : {});
        return `Focus session started${minutes ? ` for ${minutes} min` : ''}.`;
      },
    },
    {
      name: 'backup',
      klass: 'L1',
      summary: 'Create a profile backup now.',
      usage: 'thoth backup now',
      run(engine, args) {
        if (
          String(args || '')
            .toLowerCase()
            .trim() !== 'now'
        ) {
          return 'Usage: thoth backup now';
        }
        const created = engine.createBackup();
        return `Backup created: ${typeof created === 'string' ? created : created?.name || 'ok'}`;
      },
    },
    {
      name: 'restore',
      klass: 'L2',
      summary: 'Restore a named backup over the live profile (elevated).',
      usage: 'thoth restore <name>',
      run(engine, args) {
        const name = String(args || '').trim();
        if (!name) return 'Usage: thoth restore <name> (see "thoth backups")';
        engine.restoreBackup(name);
        return `Restore completed from "${name}".`;
      },
    },
    {
      name: 'mood',
      klass: 'L1',
      summary: 'Media mix for a mood.',
      usage: 'thoth mood <focus|unwind|...>',
      run(engine, args) {
        const mood = String(args || '')
          .trim()
          .toLowerCase();
        if (!mood) return 'Usage: thoth mood <mood>';
        const mix = engine.moodMix(mood) || [];
        return clip(
          `Mood mix "${mood}":\n${list(mix.slice(0, 8).map(t => t.title || t.name || String(t)))}`
        );
      },
    },
    {
      name: 'pin',
      klass: 'L1',
      summary: 'Pin a workspace widget by id.',
      usage: 'thoth pin <widget-id>',
      run(engine, args) {
        const id = String(args || '').trim();
        if (!id) return 'Usage: thoth pin <widget-id>';
        engine.pinWidget(id);
        return `Widget pinned: ${id}`;
      },
    },
    {
      name: 'unpin',
      klass: 'L1',
      summary: 'Unpin a workspace widget by id.',
      usage: 'thoth unpin <widget-id>',
      run(engine, args) {
        const id = String(args || '').trim();
        if (!id) return 'Usage: thoth unpin <widget-id>';
        engine.unpinWidget(id);
        return `Widget unpinned: ${id}`;
      },
    },
    {
      name: 'reset',
      klass: 'L2',
      summary: 'Reset the whole local profile (elevated, destructive).',
      usage: 'thoth reset confirm',
      run(engine, args) {
        if (
          String(args || '')
            .toLowerCase()
            .trim() !== 'confirm'
        ) {
          return 'This erases the local profile. Run "thoth reset confirm" to proceed.';
        }
        engine.reset();
        return 'Profile reset. THOTH re-attached to the fresh state.';
      },
    },
    {
      name: 'self',
      klass: 'L0',
      summary: 'Kernel self-report: uptime, grants, watch state, safety backups.',
      usage: 'thoth self',
      run(engine, _args, _ctx, all, kernel) {
        const m = kernel.meta();
        const mins = Math.max(1, Math.round((Date.now() - m.attachedAt) / 60000));
        const grantLine = Object.entries(m.grants)
          .map(([t, c]) => `${t}:${c}`)
          .join(', ');
        return [
          `THOTH attached ${mins} min ago | master ${m.masterEnabled ? 'ON' : 'OFF'} | watch ${m.watch ? 'ON' : 'OFF'}`,
          `tools: ${all.size} | standing grants: ${grantLine || '(none)'}`,
          `last design audit: ${m.lastAuditAt || 'never'}`,
          `last auto safety backup: ${m.lastSafetyBackupAt ? new Date(m.lastSafetyBackupAt).toISOString() : 'none'}`,
          'Local-only operator surface; conversations and findings never leave this PC.',
        ].join('\n');
      },
    },
    {
      name: 'memory',
      klass: 'L0',
      summary: 'Memory analytics: counts, age spread, sources.',
      usage: 'thoth memory',
      run(engine) {
        const snap = engine.snapshot();
        const mems = Array.isArray(snap.memories) ? snap.memories : [];
        if (!mems.length) return 'Memory is empty.';
        const times = mems.map(m => m.createdAt || m.at || 0).filter(Boolean);
        const oldest = times.length ? new Date(Math.min(...times)).toISOString().slice(0, 10) : '?';
        const newest = times.length ? new Date(Math.max(...times)).toISOString().slice(0, 10) : '?';
        const sources = {};
        for (const m of mems) {
          const s = m.source || m.opts?.source || 'app';
          sources[s] = (sources[s] || 0) + 1;
        }
        return [
          `memories: ${mems.length} (span ${oldest} to ${newest})`,
          `by source: ${Object.entries(sources)
            .map(([k, v]) => `${k}=${v}`)
            .join(', ')}`,
        ].join('\n');
      },
    },
    {
      name: 'conversations',
      klass: 'L0',
      summary: 'Recent conversation inventory (ids and sizes only).',
      usage: 'thoth conversations [n]',
      run(engine, args) {
        const n = Math.min(Math.max(Number(args) || 5, 1), 20);
        const convos = Array.isArray(engine.snapshot().conversations)
          ? engine.snapshot().conversations
          : [];
        if (!convos.length) return 'No conversations stored yet.';
        const rows = convos.slice(-n).map(c => {
          const turns = Array.isArray(c.messages) ? c.messages.length : (c.turnCount ?? '?');
          return `- ${(c.id || 'id?').slice(0, 12)} turns=${turns}${c.startedAt ? ` at ${new Date(c.startedAt).toISOString().slice(0, 16)}` : ''}`;
        });
        return `Recent conversations (${rows.length}/${convos.length}):\n${rows.join('\n')}`;
      },
    },
    {
      name: 'widgets',
      klass: 'L0',
      summary: 'Current dashboard widget layout order.',
      usage: 'thoth widgets',
      run(engine) {
        const snap = engine.snapshot();
        const order = snap.widgets?.order || snap.widgetOrder || [];
        return order.length
          ? `Widget order:\n${order.map((w, i) => `${i + 1}. ${typeof w === 'string' ? w : w.id || '?'}`).join('\n')}`
          : 'No custom widget order set.';
      },
    },
    {
      name: 'funnel',
      klass: 'L0',
      summary: 'Onboarding funnel progress snapshot.',
      usage: 'thoth funnel',
      run(engine) {
        const f = engine.snapshot().funnel;
        if (!f || typeof f !== 'object') return 'Funnel not started.';
        return `Funnel: ${JSON.stringify(f)}`;
      },
    },
    {
      name: 'repo',
      klass: 'L0',
      summary: 'Local git posture of the connected repository (read-only).',
      usage: 'thoth repo [branch|status|log]',
      run(engine, args) {
        const sub =
          String(args || '')
            .toLowerCase()
            .trim() || 'status';
        const rootGuess = process.cwd();
        const cmds = {
          branch: ['git', ['rev-parse', '--abbrev-ref', 'HEAD']],
          status: ['git', ['status', '--porcelain']],
          log: ['git', ['log', '--oneline', '-5']],
        };
        const entry = cmds[sub];
        if (!entry) return `Unknown repo view "${sub}". Use branch | status | log.`;
        return new Promise(resolve => {
          execFile(
            entry[0],
            entry[1],
            {
              cwd: rootGuess,
              timeout: 8000,
              windowsHide: true,
              maxBuffer: 200_000,
            },
            (err, stdout) => {
              if (err && !stdout) {
                resolve(
                  `git ${sub} unavailable here (${String(err.message).split('\n')[0].slice(0, 60)}).`
                );
                return;
              }
              const out = String(stdout || '').trim();
              if (sub === 'status') {
                resolve(
                  out
                    ? `${out.split('\n').length} uncommitted file(s):\n${out.slice(0, 400)}`
                    : 'Working tree clean.'
                );
                return;
              }
              resolve(out ? out.slice(0, 900) : `(no output)`);
            }
          );
        });
      },
    },
    {
      name: 'code',
      klass: 'L0',
      summary: 'Advanced codebase knowledge: explain files, find symbols, conventions.',
      usage: 'thoth code explain <file> | find <symbol> | conventions',
      run(_engine, args) {
        const raw = String(args || '').trim();
        const [verb, ...rest] = raw.split(/\s+/);
        const target = rest.join(' ');
        if (verb === 'explain' && target) return explainFile(target);
        if ((verb === 'find' || verb === 'symbol') && target) return findSymbol(target);
        if (verb === 'conventions' || !verb) return conventions();
        return `Unknown code view "${verb}". Use explain | find | conventions.`;
      },
    },
    {
      name: 'ideate',
      klass: 'L0',
      summary: 'Generate design proposals from the live audit and goal documents.',
      usage: 'thoth ideate',
      async run(engine, _args, _ctx, _all, kernel) {
        const { report } = await auditNow(engine, kernel?.relay);
        const ideas = deriveIdeas(report).map((idea, i) => ({
          ...idea,
          n: i + 1,
        }));
        const box = engine.state.thoth?.creative;
        if (box) {
          box.ideas = [...ideas.map(i => ({ ...i, at: Date.now() })), ...(box.ideas || [])].slice(
            0,
            20
          );
        }
        engine.store.save(engine.state);
        kernel?.relay?.emit?.('creation', {
          kind: 'ideas',
          count: ideas.length,
        });
        return ideas.length
          ? `Proposals (advisory - nothing applied):\n${ideas.map(i => `${i.n}. [${i.severityHint}] ${i.title}`).join('\n')}\nSay "thoth creations" for full bodies.`
          : 'Clean audit; no proposals warranted. THOTH invents only from evidence.';
      },
    },
    {
      name: 'creations',
      klass: 'L0',
      summary: 'Browse the creative inbox: ideas, drafts, generated themes.',
      usage: 'thoth creations [n]',
      run(engine) {
        const c = engine.state.thoth?.creative || {};
        const parts = [];
        if (c.ideas?.length) {
          parts.push(`Ideas (${c.ideas.length}):`);
          for (const i of c.ideas.slice(0, 3)) parts.push(`  - ${i.title}`);
        }
        if (c.drafts?.length)
          parts.push(
            `Changelog drafts: ${c.drafts.length} (latest ${c.drafts[0]?.at ? new Date(c.drafts[0].at).toISOString().slice(0, 10) : ''})`
          );
        if (c.themes?.length) parts.push(`Themes: ${c.themes.map(t => t.name).join(', ')}`);
        return (
          parts.join('\n') || 'Creative inbox is empty. Try "thoth ideate" or "thoth changelog".'
        );
      },
    },
    {
      name: 'changelog',
      klass: 'L1',
      summary: 'Draft changelog entries from git history since the last tag.',
      usage: 'thoth changelog [n]',
      run(engine, args, _ctx, _all, kernel) {
        const rootGuess = process.cwd();
        const n = Math.min(Math.max(Number(args) || 20, 5), 60);
        return new Promise(resolve => {
          execFile(
            'git',
            ['log', '--oneline', `-n`, String(n)],
            {
              cwd: rootGuess,
              timeout: 8000,
              windowsHide: true,
              maxBuffer: 200_000,
            },
            (err, stdout) => {
              if (err && !stdout) {
                resolve(`Git history unavailable here. Run from a repository clone.`);
                return;
              }
              const draft = draftChangelogFromGit(String(stdout));
              const box = engine.state.thoth?.creative;
              if (draft && box) {
                box.drafts = [{ at: Date.now(), text: draft }, ...(box.drafts || [])].slice(0, 10);
                engine.store.save(engine.state);
                kernel?.relay?.emit?.('creation', { kind: 'changelog' });
              }
              resolve(
                draft
                  ? 'Draft stored in the creative inbox:\n' + draft
                  : 'Nothing changelog-worthy found.'
              );
            }
          );
        });
      },
    },
    {
      name: 'theme',
      klass: 'L0',
      summary: 'Compose an accessible dark theme variant into the creative inbox.',
      usage: 'thoth theme <name> [hue]',
      run(engine, args) {
        const parts = String(args || '')
          .trim()
          .split(/\s+/);
        const name = (parts[0] || '').replace(/[^a-z0-9-]/gi, '');
        const hue = Math.min(Math.max(Number(parts[1]) || 145, 0), 359);
        if (!name) return 'Usage: thoth theme <name> [hue 0-359]';
        const theme = buildTheme(name, hue);
        const c = engine.state.thoth.creative;
        c.themes = [
          { ...theme, at: Date.now() },
          ...(c.themes || []).filter(t => t.name !== name),
        ].slice(0, 8);
        engine.store.save(engine.state);
        return (
          `Theme "${name}" composed (WCAG-checked ink per surface).\n` +
          `Preview/apply it from the THOTH relay panel on the dashboard.`
        );
      },
    },
    {
      name: 'adult',
      klass: 'L0',
      summary: 'Adult session wellness: private mode, elapsed minutes, limit headroom.',
      usage: 'thoth adult [limit <min>|private on|off]',
      async run(engine, args) {
        const raw = String(args || '')
          .toLowerCase()
          .trim();
        const status = await window?.soul?.adultSessionStatus?.();
        const cfg = engine.state.assistant || {};
        void cfg;
        if (raw.startsWith('limit')) {
          return 'Session limits are set in Settings (Adult session limit). THOTH reports; you decide.';
        }
        if (raw.startsWith('private')) {
          return 'Private mode toggles in Settings > Companion (adultPrivateMode). When ON, taste records are suppressed at the main-process choke point.';
        }
        const s = typeof window === 'undefined' ? null : status;
        if (!s) {
          return 'Session telemetry unavailable outside the desktop runtime.';
        }
        return [
          `session ${s.active ? 'ACTIVE' : 'idle'} - ${s.minutes} min elapsed`,
          s.limitMin ? `limit ${s.limitMin} min | remaining ${s.remaining}` : 'no limit set',
          `private mode ${s.privateMode ? 'ON (taste writes suppressed)' : 'OFF'}`,
          s.overLimit ? 'OVER LIMIT - consider a break.' : '',
        ]
          .filter(Boolean)
          .join('\n');
      },
    },
    {
      name: 'master',
      klass: 'L2',
      summary: 'Administrator pause/resume for the whole kernel.',
      usage: 'thoth master on|off',
      run() {
        return 'Handled by the kernel gate directly.';
      },
    },
    {
      name: 'ai',
      klass: 'L0',
      summary: 'Probe the local model bridge (Ollama): version, models, loaded state.',
      usage: 'thoth ai [models|loaded]',
      async run(_engine, args) {
        const view =
          String(args || '')
            .toLowerCase()
            .trim() || 'models';
        const base = 'http://127.0.0.1:11434';
        try {
          if (view === 'loaded') {
            const ps = await (await fetch(`${base}/api/ps`)).json();
            const rows = (ps.models || []).map(
              m => `${m.name} - vram ${(m.size_vram / 1073741824).toFixed(2)} GB`
            );
            return rows.length
              ? `Loaded models:\n${rows.join('\n')}`
              : 'No models loaded right now.';
          }
          const tags = await (await fetch(`${base}/api/tags`)).json();
          const names = (tags.models || []).map(m => m.name);
          return names.length
            ? `Local models:\n${names.map(n => `- ${n}`).join('\n')}`
            : 'Bridge is up but no models are installed.';
        } catch (err) {
          return `Local model bridge unreachable (${String(err.message).split('.')[0]}). Start Ollama and retry.`;
        }
      },
    },
    {
      name: 'sync',
      klass: 'L0',
      summary: 'Dev-only guidance: how to reconcile installed kernel with canonical.',
      usage: 'thoth sync',
      run() {
        return [
          'Kernel sync is a repository command (audited path):',
          '  npm run thoth:sync    canonical -> installed',
          '  npm run thoth:push    installed -> canonical',
          'Packaged installs ship the kernel already current; no runtime sync needed.',
        ].join('\n');
      },
    },
    {
      name: 'trends',
      klass: 'L0',
      summary: 'Design findings over time: direction, best-ever, recent series.',
      usage: 'thoth trends',
      run(engine) {
        const d = engine.state.thoth?.design || {};
        return trends({ ...d.lastAudit, history: d.lastAudit?.history });
      },
    },
    {
      name: 'regress',
      klass: 'L0',
      summary: 'Regression report: last audit vs previous tick by category.',
      usage: 'thoth regress',
      run(engine) {
        const design = engine.state.thoth?.design || {};
        return regressionReport({
          ...design.lastAudit,
          history: design.lastAudit?.history,
        });
      },
    },
    {
      name: 'compliance',
      klass: 'L0',
      summary: 'Standards & regulations scan (supply-chain, privacy egress, CSP, a11y, safety).',
      usage: 'thoth compliance',
      async run(engine, _args, _ctx, _all, kernel) {
        const { scanCompliance } = await complianceScanner();
        const report = scanCompliance({ fix: false });
        const c = engine.state.thoth || {};
        c.compliance = {
          at: report.generatedAt,
          counts: report.counts,
          findings: report.findings.slice(0, 25),
        };
        engine.store.save(engine.state);
        kernel?.relay?.emit?.('compliance', {
          total: report.findings.length,
          bySeverity: report.counts,
          announce: (report.counts.high || 0) > 0,
          text: `Compliance scan: ${report.findings.length} finding(s).`,
        });
        return (
          `Standards v${report.standardsVersion}: ${report.findings.length} finding(s)` +
          ` (${JSON.stringify(report.counts)}).\n` +
          report.findings
            .slice(0, 8)
            .map(f => `- [${f.severity}] ${f.rule}: ${f.file} - ${f.message}`)
            .join('\n')
        );
      },
    },
    {
      name: 'comply-fix',
      klass: 'L2',
      summary: 'Apply whitelisted mechanical fixes (SPDX headers). Elevated.',
      usage: 'thoth comply-fix',
      async run(engine, _args, _ctx, _all) {
        const { scanCompliance } = await complianceScanner();
        const pre = await scanCompliance({ fix: false });
        if (!pre.fixed.length && !pre.findings.some(f => f.rule === 'spdx-header')) {
          return 'No whitelisted auto-fixes available. All other standards items need human action.';
        }
        const post = await scanCompliance({ fix: true });
        engine.state.thoth.compliance = {
          at: post.generatedAt,
          counts: post.counts,
          findings: post.findings.slice(0, 25),
        };
        engine.store.save(engine.state);
        return `Applied ${post.fixed.length} mechanical fix(es): ${post.fixed.join(', ')}. Remaining findings: ${post.findings.length}.`;
      },
    },
    {
      name: 'design',
      klass: 'L0',
      summary: 'Run the architecture scan now (cycles, seams, env, hotspots).',
      usage: 'thoth design [map <module>]',
      async run(engine, args, _ctx, _all, kernel) {
        const arg = String(args || '').trim();
        const { report, stored } = await auditNow(engine, kernel?.relay);
        if (arg.startsWith('map')) {
          const target = arg.slice(3).trim().toLowerCase();
          const deps = stored.top.filter(f => f.file.toLowerCase().includes(target));
          return deps.length
            ? `Modules touched in findings for "${target}":\n${deps.map(d => `- ${d.file}: ${d.message}`).join('\n')}`
            : `No findings reference "${target}". Clean module.`;
        }
        return (
          `Design audit complete: ${report.modules} modules / ${report.edges} edges / ` +
          `${report.filesScanned} files.\nFindings ${report.findings.length} ` +
          `(byCategory ${JSON.stringify(report.counts.byCategory)}). Stored to profile; ` +
          '"thoth next" prioritizes, "thoth goals" tracks docs.'
        );
      },
    },
    {
      name: 'goals',
      klass: 'L0',
      summary: 'Goal documents this architecture must keep serving.',
      usage: 'thoth goals',
      run() {
        const rows = goalsStatus().map(g => `- [${g.present ? 'x' : ' '}] ${g.goal} (${g.doc})`);
        return ['Goal sources anchoring every design decision:', ...rows].join('\n');
      },
    },
    {
      name: 'next',
      klass: 'L0',
      summary: 'Deterministic priority queue from the last design audit.',
      usage: 'thoth next',
      run(engine) {
        return nextActions(engine.state.thoth?.design?.lastAudit);
      },
    },
    {
      name: 'watch',
      klass: 'L1',
      summary: 'Continuous mode: re-audit every 30 min into the local profile.',
      usage: 'thoth watch on|off|status',
      run(engine, args, _ctx, _all, kernel) {
        const arg =
          String(args || '')
            .toLowerCase()
            .trim() || 'status';
        if (arg === 'on') {
          const on = startWatch(engine, kernel?.relay);
          return on ? 'Design watch enabled (30-min loop).' : 'Already watching.';
        }
        if (arg === 'off')
          return stopWatch(engine) ? 'Design watch disabled.' : 'Watch was already off.';
        return `Design watch is ${engine.state.thoth?.design?.watch ? 'ON' : 'OFF'}.`;
      },
    },
  ];

  tools.sort((a, b) => a.name.localeCompare(b.name));
  return tools;
}
