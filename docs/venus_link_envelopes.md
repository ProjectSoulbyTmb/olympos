# Venus Link Bus Envelopes

How messages flow between Venus (the desktop companion in `assistant/`) and
MIND over the durable file bus in `runs/osrs_bus/` - the same transport the
Thoth relay uses.

## Envelope structure

Every message on the bus is a JSON envelope with these fields:

| Field | Meaning |
|-------|---------|
| `id` | Unique id, e.g. `venus_<epoch>_<seq>` |
| `at` | ISO timestamp of creation |
| `from` | Sender (`venus`, `mind`, ...) |
| `type` | Message type: requests use `venus.request`; Mind emits `mind.*` events (sentinel alerts, net alerts, patrol findings) |
| `status` | Lifecycle state - `queued` until drained, then completed or failed |
| `payload` | The actual data (for requests: `{action, args}`; for events: the alert/finding) |

## Flow

1. **Venus -> Mind (requests).** `mind request <action> '<json>'` writes a
   `venus.request` envelope into the bus spool.
2. **Mind drains.** The daemon picks it up via `osrs mind venus --execute`,
   runs the action, and captures stdout. Release and autonomic actions only
   run when explicit consent flags are present inside the envelope payload -
   a forged envelope cannot ship code.
3. **Completion.** The envelope is marked done (or failed with the error text)
   and moved to the bus archive; results never raise out of the drain loop.
4. **Mind -> Venus (events).** Mind publishes `mind.*` envelopes; Venus's
   resident drain task emits each one onto her kernel event bus, where they
   appear in the UI feed and can drive automation rules:

   ```
   auto add on mind.net.alert match DOWN do say network trouble detected
   ```

Offline-first by design: a missing suite or an empty bus is a valid,
quietly-handled state.
