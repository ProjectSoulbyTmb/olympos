"""ZEUS sentinel - the process guardian.

Every patrol the sentinel samples the live process table and asks four
questions: are the watched services still alive, did any explicitly
pinned pid die, is any process running away (sustained CPU / memory),
and who owns our ports? Deaths become alerts (or restart repairs when
a manifest entry carries a restart command); runaway confirmation is
handed to the kernel so policy - alert or thunderbolt - decides.
"""

import subprocess

import content
import procsys


class Sentinel:
    def __init__(self, proc_table=None, manifest=None):
        self.table = proc_table or procsys.ProcTable()
        self.manifest = list(manifest if manifest is not None
                             else content.WATCH_MANIFEST)
        self.pinned = {}            # pid -> {"name":..., "on_death":...}
        self.last = {}              # pid -> ProcInfo of last sample
        self._alive_named = {}      # watch name -> pid seen last tick
        self._runaway = {}          # pid -> {"soft":n,"hard":n,"peak":pct}

    # ---------- public surface ----------

    def pin_pid(self, pid, name=None, on_death="alert"):
        if on_death not in ("alert", "restart"):
            raise ValueError("on_death must be alert|restart")
        self.pinned[int(pid)] = {"name": name or f"pid-{pid}",
                                 "on_death": on_death}

    def unpin_pid(self, pid):
        return self.pinned.pop(int(pid), None)

    def patrol(self):
        """One supervision pass. Returns (findings, snapshot)."""
        findings = []
        snap = self.table.sample()
        self.last = snap

        alive_by_name = {}
        for pid, info in snap.items():
            if info.name:
                alive_by_name.setdefault(info.name.lower(), []).append(pid)

        findings += self._named_watches(alive_by_name)
        findings += self._pinned_watches(snap)
        findings += self._runaways(snap)
        findings += self._ports(snap)
        return findings, snap

    # ---------- watches ----------

    def _named_watches(self, alive_by_name):
        out = []
        for entry in self.manifest:
            name = entry["name"]
            match = str(entry["match"]).lower()
            kind = entry.get("kind", "image")
            pids = []
            if kind == "image":
                pids = alive_by_name.get(match, [])
            elif kind == "contains":
                pids = [pid for pid, info in self.last.items()
                        if match in (info.exe or "").lower()]
            prev = self._alive_named.get(name)
            self._alive_named[name] = pids[0] if pids else None
            if pids:
                continue
            if prev is None:
                continue  # was already gone (or never seen) - stay quiet
            out.append(self._death_finding(name, prev, entry))
        return out

    def _pinned_watches(self, snap):
        out = []
        # A pinned pid dies when its row disappears outright; a row we
        # merely cannot open stays counted as alive (it was readable
        # when pinned, so darkness is unusual but not death).
        for pid in list(self.pinned):
            info = snap.get(pid)
            if info is not None:
                continue
            meta = self.pinned.pop(pid)
            out.append({
                "type": "proc_death", "severity": "warn",
                "watch": meta["name"], "pid": pid,
                "text": f"pinned {meta['name']} (pid {pid}) died",
                "on_death": meta["on_death"],
                "entry": meta,
            })
        return out

    def _death_finding(self, name, pid, entry):
        finding = {
            "type": "proc_death", "severity": "warn",
            "watch": name, "pid": pid,
            "text": f"watch '{name}' (pid {pid}) no longer alive",
            "on_death": entry.get("on_death", "alert"),
            "entry": entry,
        }
        return finding

    def try_restart(self, finding):
        """Honour a death finding's restart command, if any."""
        cmd = (finding.get("entry") or {}).get("restart_cmd")
        if not cmd:
            return None
        try:
            proc = subprocess.Popen(cmd, cwd=content.WORKSPACE,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError as exc:
            return {"restarted": False, "error": str(exc)}
        if finding["watch"] and proc.pid:
            self._alive_named[finding["watch"]] = proc.pid
        return {"restarted": True, "pid": proc.pid}

    # ---------- resource runaways ----------

    def _runaways(self, snap):
        out = []
        soft_cpu, hard_cpu = content.CPU_SOFT_PCT, content.CPU_HARD_PCT
        mem_soft = content.MEM_SOFT_MB
        for pid, info in snap.items():
            state = self._runaway.setdefault(
                pid, {"soft": 0, "hard": 0})
            if info.cpu_pct is not None:
                if info.cpu_pct >= hard_cpu:
                    state["hard"] += 1
                    state["soft"] += 1
                elif info.cpu_pct >= soft_cpu:
                    state["soft"] += 1
                    state["hard"] = 0
                else:
                    state["soft"] = 0
                    state["hard"] = 0
            if state["hard"] >= max(1, content.RUNAWAY_SAMPLES // 2) \
                    or state["soft"] >= content.RUNAWAY_SAMPLES:
                action = content.ESCALATION_POLICY.get(
                    "default", "alert")
                out.append({
                    "type": "runaway", "severity": "critical",
                    "pid": pid, "name": info.name, "exe": info.exe,
                    "cpu_pct": info.cpu_pct, "mem_mb": info.mem_mb,
                    "action": action,
                    "text": f"{info.name or 'pid ' + str(pid)} "
                            f"sustained high CPU "
                            f"({info.cpu_pct:.0f}% now)",
                })
                state.update(soft=0, hard=0)
                continue
            if info.mem_mb and info.mem_mb > mem_soft:
                out.append({
                    "type": "mem_pressure", "severity": "warn",
                    "pid": pid, "name": info.name,
                    "text": f"{info.name or pid} working set "
                            f"{info.mem_mb:.0f} MB over soft cap",
                })
        return out

    # ---------- ports ----------

    def _ports(self, snap):
        out = []
        try:
            listeners = procsys.tcp_listeners()
        except OSError:
            return out
        ws_low = content.WORKSPACE.lower()
        for pid, port, addr in listeners[:content.PORT_SCAN_TOP_N]:
            if port not in content.OWNED_PORTS:
                continue
            info = snap.get(pid)
            exe = (info.exe if info else "") or ""
            trusted = bool(exe) and (
                exe.lower().startswith(ws_low)
                or info.name.lower().startswith("python"))
            out.append({
                "type": "port_watch",
                "severity": "info" if trusted else "warn",
                "pid": pid, "port": port, "addr": addr,
                "owner": exe or "(inaccessible)",
                "text": f"listener on owned port {port}: "
                        f"{exe or 'unknown owner'} (pid {pid})",
            })
        return out
