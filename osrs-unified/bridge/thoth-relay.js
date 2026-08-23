// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH <-> MIND file relay adapter (osrs-unified side lives in mind/bus.py).
 *
 * Drop into thoth-private as src/features/thoth/mind-relay.js and wire:
 *   import { attachToRelay, publishToMind } from './mind-relay.js';
 *   const unbind = attachToRelay(relayInstance, '<abs path>/osrs-unified');
 * Every thoth:event is mirrored onto the durable bus; pending mind.* jobs
 * are yielded via takePending() for kernel scheduling.
 *
 * Envelope: { id, at, from: 'mind'|'thoth', type, status, payload }
 */
import fs from 'node:fs';
import path from 'node:path';

export function createBusLink(root) {
  const dir = path.join(root, 'runs', 'osrs_bus');
  const spool = path.join(dir, 'spool');
  const archive = path.join(dir, 'archive');
  for (const d of [spool, archive]) fs.mkdirSync(d, { recursive: true });

  const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
  const writeAtomic = (p, data) => {
    const tmp = p + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(data, null, 1));
    fs.renameSync(tmp, p);
  };
  const scan = (d) => fs.readdirSync(d).filter((n) => n.endsWith('.json')).sort();

  return {
    dir,
    publish(type, payload = {}, source = 'thoth') {
      const evt = {
        id: `${source}_${Date.now()}`,
        at: new Date().toISOString(),
        from: source,
        type,
        status: 'queued',
        payload,
      };
      writeAtomic(path.join(spool, evt.id + '.json'), evt);
      return evt;
    },
    pending(type) {
      return scan(spool)
        .map((n) => { try { return readJson(path.join(spool, n)); } catch { return null; } })
        .filter((e) => e && e.status === 'queued' && (!type || e.type === type));
    },
    complete(id, result = {}, ok = true) {
      const p = path.join(spool, id + '.json');
      const evt = readJson(p);
      evt.status = ok ? 'done' : 'failed';
      evt.result = result;
      evt.completed_at = new Date().toISOString();
      writeAtomic(path.join(archive, id + '.json'), evt);
      fs.unlinkSync(p);
      return evt;
    },
    recent(limit = 15) {
      return scan(archive).slice(-limit).reverse()
        .map((n) => { try { return readJson(path.join(archive, n)); } catch { return null; } })
        .filter(Boolean);
    },
  };
}

/** Mirror every Thoth relay event onto the durable bus; returns unbind(). */
export function attachToRelay(relayLike, root) {
  const link = createBusLink(root);
  const unsubscribe = relayLike.subscribe((evt) => {
    try {
      link.publish(`thoth.${evt.type}`, evt.payload ?? {}, 'thoth');
    } catch { /* bus offline must never break the kernel */ }
  });
  return { link, unsubscribe };
}
