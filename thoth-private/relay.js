// SPDX-FileCopyrightText: 2026 Soul Consciousness Studios
// SPDX-License-Identifier: LicenseRef-Eidovara-Source-Available-1.0
/**
 * THOTH relay hub - kernel <-> UI/avatar bridge.
 *
 * Main-process side. Bounded ring buffer replays the last events to late
 * subscribers (e.g. a renderer that loads after an audit fired). Payloads
 * are plain JSON and stay on this machine; broadcast transport is injected
 * by electron/main.js (webContents.send over the 'thoth:event' channel).
 */
const REPLAY_LIMIT = 25;

export function createRelay({ broadcast } = {}) {
  const buffer = [];
  const subscribers = new Set();
  let boundKernel = null;

  function emit(type, payload = {}) {
    const event = { type, payload, at: new Date().toISOString() };
    buffer.push(event);
    if (buffer.length > REPLAY_LIMIT) buffer.shift();
    for (const cb of subscribers) {
      try {
        cb(event);
      } catch {
        /* one bad subscriber never blocks the others */
      }
    }
    if (broadcast) {
      try {
        broadcast('thoth:event', event);
      } catch {
        /* window may be closing */
      }
    }
    return event;
  }

  return {
    emit,
    subscribe(cb) {
      subscribers.add(cb);
      for (const event of buffer) cb(event);
      return () => subscribers.delete(cb);
    },
    bindKernel(kernel) {
      boundKernel = kernel;
    },
    get kernel() {
      return boundKernel;
    },
  };
}
