# MIND <-> Thoth relay bridge

Durable, file-based event bus connecting **MIND** (this repo's Python
automation kernel, `mind/bus.py`) with **Thoth** (`thoth-private`, whose
`relay.js` is an in-memory hub).

## Wire format

JSON envelope per file under `osrs-unified/runs/osrs_bus/spool/`:

```json
{"id": "thoth_20260823_...", "at": "...", "from": "thoth",
 "type": "thoth.result.run", "status": "queued", "payload": {}}
```

Completed events move to `archive/` with `result` + `completed_at`.

## Event catalog (all relays)

| Type | Direction | Meaning |
|---|---|---|
| `mind.briefing` | MIND -> Thoth | live status injected into every strategy prompt |
| `mind.status` | MIND -> Thoth | patrol summary (findings/tests) |
| `mind.job.improve_strategy` | MIND -> Thoth | payload `{task, rounds, ticks, model?, base_url?}`; pumped by `osrs mind relay pump --execute` |
| `mind.job.diagnose` | MIND -> Thoth | run tests + AI diagnosis |
| `thoth.result.run` | Thoth -> MIND | bench LLM session outcome (best score, errors) |
| `thoth.proposal` | Thoth -> MIND | engineering patch proposal (also saved to mind/proposals/) |

## Using the Thoth side

Copy `thoth-relay.js` into `thoth-private/src/features/thoth/mind-relay.js`
(edit there per its contract), then in kernel.js:

```js
import { attachToRelay } from './mind-relay.js';
const { link, unsubscribe } = attachToRelay(relay, '<abs>/osrs-unified');
// react to jobs:
for (const job of link.pending('mind.job.improve_strategy')) {
  // ... schedule via your kernel ...
  link.complete(job.id, { accepted: true });
}
```

Python side commands:

```powershell
osrs mind relay status
osrs mind relay publish mind.job.improve_strategy "{\"task\":\"wc_xp\",\"rounds\":4}"
osrs mind relay pump --execute
```
