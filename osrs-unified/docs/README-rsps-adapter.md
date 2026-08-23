# RSPS adapter

Train/evaluate the PPO policy against a real Elvarg-based private server that
YOU host. Nothing here connects to Jagex services.

## Components

- `env_rsps.py` - `RspsPvpEnv`: same step/reset interface as the local
  `OsrsPvpEnv`, but state comes from your server over TCP (line protocol:
  `OK,reward,done,obs[12],mask[6]`).
- `server/RelayPlugin.java` - zero-dependency socket relay you drop into your
  RSPS. It exposes RESET / STEP,CLOSE commands and streams observations.

## Integration steps

1. Host an Elvarg-based server (e.g. github.com/RSPSApp/elvarg) on your own
   machine or VPS.
2. Copy `RelayPlugin.java` into your server source and call `new
   RelayPlugin().init()` from your plugin bootstrap.
3. Wire the five marked methods (`observe`, `legalActions`, `applyAction`,
   `tickWorld`, `fightOver`, `resetFight`) to your combat queue. The comments
   list the exact observation layout expected by the trained policies.
4. Point the client at it:

```python
from rsps_adapter.env_rsps import RspsPvpEnv

env = RspsPvpEnv(host="127.0.0.1", port=43594)
# same obs/action contract as OsrsPvpEnv -> swap into play_episode()
```

5. For self-play on-server, run two bot accounts each with their own relay
   connection and pass the second port as `opp_port`.

## Why line protocol instead of JSON

Zero dependencies on the Java side - no Gson/Jackson needed, works with any
Elvarg fork regardless of library setup.
