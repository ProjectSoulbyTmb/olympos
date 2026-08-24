"""Vulcan console: interactive building control.

Works embedded (local World) or connected to a hosted BuildingServer
through VulcanClient - same commands either way.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import argparse
import sys

import content


def fmt_w(w):
    return f"{w} W" if w < 1000 else f"{w / 1000:.2f} kW"


class Console:
    def __init__(self, sdk):
        self.sdk = sdk

    # ---- printers ----

    @staticmethod
    def _print_state(state):
        b = state["building"]
        print(f"building mode={b['mode']} clock={b['clock']} "
              f"outside={b['outside_c']:.1f}C tick={b['tick']}")
        print(f"power {fmt_w(b['power_w'])} total {b['kwh_total']} kWh "
              f"| zones={b['zones']} devices={b['devices']} "
              f"rules active={b.get('rules_active', '?')}")

    @staticmethod
    def _print_zones(zones):
        for name in sorted(zones):
            z = zones[name]
            occ = f" occ={z['occupants']}" if z["occupants"] else ""
            print(f"  {name:<9} {z['temp']:>5.1f}C "
                  f"{fmt_w(z['power_w']):>8}{occ}")

    @staticmethod
    def _print_devices(devices):
        for d in devices:
            bits = [d["type"], d["zone"]]
            for key in ("on", "open", "locked", "occupied", "alarm",
                        "mode", "target", "brightness", "people"):
                if key in d:
                    bits.append(f"{key}={d[key]}")
            print(f"  {d['id']:<18}" + " ".join(bits)
                  + (f" [{fmt_w(d['watts'])}]" if d["watts"] else ""))

    # ---- command dispatch ----

    def execute(self, line):
        parts = line.strip().split()
        if not parts:
            return True
        cmd, args = parts[0].lower(), parts[1:]
        sdk = self.sdk

        def need(n):
            if len(args) < n:
                raise ValueError(f"'{cmd}' needs {n} argument(s)")
            return args[:n]

        if cmd in ("quit", "exit"):
            return False
        elif cmd == "help":
            self.help()
        elif cmd == "status":
            self._print_state(sdk.state())
        elif cmd == "zones":
            self._print_zones(sdk.zones())
        elif cmd == "zone":
            (name,) = need(1)
            zone = sdk.zone(name=name)
            print(f"{zone['name']}: {zone['temp']:.1f}C floor"
                  f"{zone['floor']} {zone['area_m2']}m2 "
                  f"adjacent={','.join(zone['adjacent']) or '-'} "
                  f"power={fmt_w(zone['power_w'])}")
        elif cmd == "devices":
            kwargs = {}
            i = 0
            while i < len(args) - 1:
                if args[i] == "zone":
                    kwargs["zone"] = args[i + 1]
                elif args[i] == "type":
                    kwargs["dtype"] = args[i + 1]
                i += 2
            self._print_devices(sdk.devices(**kwargs))
        elif cmd == "device":
            (dev_id,) = need(1)
            self._print_devices([sdk.device(dev_id=dev_id)])
        elif cmd == "set":
            dev_id, key, val = need(3)[0:3]
            parsed = self._coerce(val)
            snap = sdk.set_device(dev_id=dev_id, **{key: parsed})
            self._print_devices([snap])
        elif cmd == "hvac":
            zone, mode = need(2)[0:2]
            target = float(args[2]) if len(args) > 2 else None
            snap = sdk.set_hvac(zone=zone, mode=mode, target=target)
            print(f"hvac {zone}: mode={snap['mode']} "
                  f"target={snap['target']}C")
        elif cmd == "motion":
            zone = need(1)[0]
            people = int(args[1]) if len(args) > 1 else 1
            snap = sdk.motion(zone=zone, people=people)
            print(f"{zone}: {snap['people']} present")
        elif cmd == "contact":
            dev_id, state = need(2)[0:2]
            result = sdk.contact(dev_id=dev_id, is_open=state in ("open", "on", "true"))
            print(result.get("event") or f"{dev_id} unchanged")
        elif cmd == "smoke":
            dev_id = need(1)[0]
            active = (args[1] not in ("off", "clear", "false")) \
                if len(args) > 1 else True
            result = sdk.smoke(dev_id=dev_id, active=active)
            print("SMOKE ALARM" if result.get("event") else "smoke reset")
        elif cmd == "weather":
            (c,) = need(1)
            print(sdk.outside_temp(celsius=float(c)))
        elif cmd == "scene":
            (name,) = need(1)
            print(sdk.scene(name=name))
        elif cmd == "mode":
            (name,) = need(1)
            print(sdk.mode(name=name))
        elif cmd == "rules":
            for r in sdk.rules():
                flag = "*" if r["enabled"] else " "
                print(f" {flag} {r['id']:<22}{r['trigger']['type']:<9}"
                      f"{r['name']}")
        elif cmd == "rule_add":
            spec = eval(" ".join(args), {"__builtins__": {}})
            added = sdk.add_rule(spec=spec)
            print(f"added rule {added['id']}")
        elif cmd == "rule_toggle":
            (rid,) = need(1)
            print(sdk.toggle_rule(rule_id=rid))
        elif cmd == "rule_del":
            (rid,) = need(1)
            print(sdk.delete_rule(rule_id=rid))
        elif cmd == "repairs":
            rows = sdk.repairs(n=int(args[0]) if args else 20)
            for r in rows:
                print(f"  #{r['n']} [{r['category']}] "
                      f"{r['t']['clock']} {r['text']}")
        elif cmd == "diagnose":
            report = sdk.diagnose()
            print(f"warden: {report.get('warden')} | repairs total: "
                  f"{report.get('repairs_total', '?')} | fixed now: "
                  f"{report.get('fixed_now', 0)}")
            for f in report.get("findings", []):
                print(f"  - [{f['category']}] {f['text']}")
        elif cmd == "warden":
            arg = args[0].lower() if args else None
            enabled = None if arg is None else arg in ("on", "true")
            print(sdk.warden(enabled=enabled))
        elif cmd == "alerts":
            for a in sdk.alerts(n=int(args[0]) if args else 20):
                print(f"  [{a['level']}] {a['t']['clock']} {a['text']}")
        elif cmd == "events":
            for e in sdk.events(n=int(args[0]) if args else 20):
                print(f"  {e['t']['clock']} {e['kind']:<10}{e['text']}")
        elif cmd == "stats":
            rows = sdk.stats(n=int(args[0]) if args else 30)
            peak = max((r["w"] for r in rows), default=0)
            avg = sum(r["w"] for r in rows) / max(1, len(rows))
            print(f"last {len(rows)} ticks: avg {fmt_w(int(avg))} "
                  f"peak {fmt_w(peak)}")
        elif cmd == "tick":
            n = int(args[0]) if args else 1
            result = sdk.tick(n=n)
            print(f"ticked to {result['tick']} "
                  f"(power {fmt_w(result['power_w'])})")
        elif cmd == "save":
            (path,) = need(1)
            print(sdk.save(path=path))
        elif cmd == "load":
            (path,) = need(1)
            print(sdk.load(path=path))
        else:
            print(f"unknown command '{cmd}' (try help)")
        return True

    @staticmethod
    def _coerce(raw):
        low = raw.lower()
        if low in ("true", "on"):
            return True
        if low in ("false", "off"):
            return False
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        return raw

    @staticmethod
    def help():
        print("""commands:
  status | zones | zone NAME | devices [zone NAME] [type TYPE] | device ID
  set DEV KEY VALUE          e.g. set light_lobby on true
  hvac ZONE MODE [TARGET]    modes: off heat cool auto fan
  motion ZONE [PEOPLE]       simulate occupancy sensor trigger
  contact ID open|closed     door/window contact
  smoke ID [on|clear]        smoke detector alarm
  weather CELSIUS            outside temperature
  scene day|night|away|vacation | mode home|away|night|vacation
  rules | rule_toggle ID | rule_del ID
  repairs [N] | diagnose | warden on|off
  alerts [N] | events [N] | stats [N] | tick [N]
  save PATH | load PATH
  quit""")

    def repl(self):
        print(f"vulcan console - 'help' for commands, "
              f"v{content.SAVE_VERSION}")
        while True:
            try:
                line = input("vulcan> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line:
                continue
            try:
                if not self.execute(line):
                    return
            except Exception as exc:
                print(f"error: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Vulcan building console")
    parser.add_argument("--connect", nargs="*", metavar=("HOST", "PORT"))
    parser.add_argument("-c", "--command", action="append",
                        help="run one command and exit (repeatable)")
    opts = parser.parse_args()

    if opts.connect is not None:
        from sdk import VulcanClient
        host = opts.connect[0] if opts.connect else content.SERVER_HOST
        port = int(opts.connect[1]) if len(opts.connect) > 1 \
            else content.SERVER_PORT
        client = VulcanClient(host, port)
        hello = client.connect()
        print(f"connected -> {hello['result']['hello']} "
              f"({hello['result']['zones']} zones)")
        console = Console(client)
    else:
        from rules import RuleEngine
        from sdk import VulcanSDK
        from world import World
        world = World()
        engine = RuleEngine(world)
        console = Console(VulcanSDK(world, engine))

    if opts.command:
        for line in opts.command:
            print(f"> {line}")
            console.execute(line)
        if opts.connect is not None:
            client.close()
        return 0
    console.repl()
    if opts.connect is not None:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
