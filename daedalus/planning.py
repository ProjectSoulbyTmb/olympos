r"""DAEDALUS planning station - durable work orders for the workshop.

A plan is a signed, file-backed work order that survives restarts.
Blueprint builds were always first-class; plans make everything else
(docs passes, multi-step commissions, research checkpoints) queueable
and auditable too.

Lifecycle:  draft -> approved -> commissioned -> done
                    \-> rejected      \-> quarantined

- draft:      submitted by anyone; inert until an operator signs off
              (sign_off{who, how} required - expansion doctrine keeps
              operator sign-off points sacred).
- approved:   cleared for work. Commissioning still requires the
              explicit commission call (approve --commission in the CLI).
- commissioned: build steps have been handed to the workshop as real
              jobs; manual steps wait on plan_step_done. When every
              step closes, the plan closes.
- rejected / quarantined: terminal, reason recorded.

Persistence: one JSON file per plan under content.PLANS_DIR, written
atomically (os.replace) and reloaded wholesale at boot. Every state
transition is mirrored into the workshop's hash-chained audit trail,
and published on the ratatosk bus when available.
"""

import json
import os
import time
import uuid

from daedalus import rules as rig

try:
    import ratatosk
except ImportError:                 # pragma: no cover
    ratatosk = None


class PlanError(Exception):
    pass


DRAFT = "draft"
APPROVED = "approved"
COMMISSIONED = "commissioned"
DONE = "done"
REJECTED = "rejected"
QUARANTINED = "quarantined"

TERMINAL = frozenset({DONE, REJECTED, QUARANTINED})
ACTIVE_STATES = frozenset({DRAFT, APPROVED, COMMISSIONED})

STEP_BUILD = "build"
STEP_MANUAL = "manual"
STEP_KINDS = frozenset({STEP_BUILD, STEP_MANUAL})

# steps per plan ceiling - a plan is a work order, not a novel
MAX_STEPS = 32


def _now():
    return time.time()


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def validate_plan(doc, known_blueprints=()):
    """-> list of issue strings; empty means acceptable."""
    issues = []
    if not isinstance(doc, dict):
        return ["error: plan must be an object"]
    title = doc.get("title")
    if not isinstance(title, str) or len(title.strip()) < 3:
        issues.append("error: title must be a string of >=3 chars")
    intent = doc.get("intent")
    if not isinstance(intent, str) or len(intent.strip()) < 20:
        issues.append("error: intent too short (<20 chars) - "
                      "describe the outcome")
    author = doc.get("author")
    if not isinstance(author, str) or not author.strip():
        issues.append("error: author must be a non-empty string")
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        issues.append("error: steps must be a non-empty list")
        return issues
    if len(steps) > MAX_STEPS:
        issues.append(f"error: more than {MAX_STEPS} steps")
    for i, st in enumerate(steps):
        if not isinstance(st, dict):
            issues.append(f"error: step {i} must be an object")
            continue
        kind = st.get("kind")
        if kind not in STEP_KINDS:
            issues.append(f"error: step {i}.kind must be one of: "
                          f"{sorted(STEP_KINDS)}")
            continue
        note = st.get("note")
        if kind == STEP_MANUAL:
            if not isinstance(note, str) or len(note.strip()) < 5:
                issues.append(
                    f"error: step {i} manual needs a note "
                    "(>=5 chars) saying what to verify")
        else:
            spec = st.get("spec")
            if not isinstance(spec, dict):
                issues.append(f"error: step {i} build needs a spec object")
                continue
            for iss in rig.validate_spec(spec, known_blueprints):
                issues.append(f"error: step {i} spec: {iss}")
    return issues


class PlanStore:
    """File-backed plan lifecycle bound to one Workshop."""

    def __init__(self, plans_dir, workshop=None):
        self.dir = plans_dir
        self.ws = workshop          # Workshop or None (CLI offline mode)
        self.plans = {}             # id -> plan dict
        self.reload()

    # ------------------------------------------------------ storage --

    def _path(self, pid):
        return os.path.join(self.dir, f"{pid}.json")

    def reload(self):
        """Boot-time rescan: whatever is on disk is the truth."""
        self.plans = {}
        if not os.path.isdir(self.dir):
            return 0
        for fn in sorted(os.listdir(self.dir)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, fn),
                          encoding="utf-8") as fh:
                    plan = json.load(fh)
                pid = plan.get("id")
                if isinstance(pid, str):
                    self.plans[pid] = plan
            except (OSError, ValueError):
                continue            # a torn temp file never blocks boot
        return len(self.plans)

    def _save(self, plan):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self._path(plan["id"]) + f".{uuid.uuid4().hex[:6]}.tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(plan, fh, indent=1, sort_keys=True)
        os.replace(tmp, self._path(plan["id"]))

    def _audit(self, kind, **fields):
        if self.ws is not None:
            try:
                self.ws.log(kind, **fields)
            except Exception:       # noqa: BLE001 - audit is best-effort
                pass
        try:
            if ratatosk is not None:
                ratatosk.publish("daedalus",
                                 {"plan": fields.get("plan"),
                                  "state": fields.get("state")},
                                 frm="daedalus", kind="fleet.plan")
        except Exception:           # noqa: BLE001
            pass

    # ---------------------------------------------------- lifecycle --

    def submit(self, doc, known_blueprints=()):
        issues = validate_plan(doc, known_blueprints)
        hard = [i for i in issues if i.startswith("error")]
        if hard:
            raise PlanError("plan refused: " + "; ".join(hard[:3]))
        slug = "".join(c if (c.isalnum() or c in "-_") else "_"
                       for c in str(doc["title"]))[:24].lower() or "plan"
        pid = f"plan-{slug}-{uuid.uuid4().hex[:6]}"
        now = round(_now(), 3)
        plan = {
            "id": pid,
            "title": doc["title"].strip(),
            "intent": doc["intent"].strip(),
            "author": doc["author"].strip(),
            "status": DRAFT,
            "created": now,
            "updated": now,
            "sign_off": None,
            "steps": [
                {"kind": s["kind"],
                 **({"spec": s["spec"]} if s["kind"] == STEP_BUILD
                    else {}),
                 **({"note": s.get("note", "")}
                    if s["kind"] == STEP_MANUAL else {}),
                 "state": "pending"}
                for s in doc["steps"]
            ],
            "outcomes": [],
        }
        self.plans[pid] = plan
        self._save(plan)
        self._audit("plan-submit", plan=pid, state=DRAFT,
                    steps=len(plan["steps"]))
        return dict(plan)

    def _get_active(self, pid, states):
        plan = self.plans.get(pid)
        if plan is None:
            raise PlanError(f"unknown plan: {pid}")
        if plan["status"] not in states:
            raise PlanError(f"plan {pid} is {plan['status']}; "
                            f"expected one of {sorted(states)}")
        return plan

    def approve(self, pid, sign_off):
        plan = self._get_active(pid, {DRAFT})
        who = (sign_off or {}).get("who")
        how = (sign_off or {}).get("how")
        if not who or not how:
            raise PlanError("sign_off requires 'who' and 'how'")
        plan["status"] = APPROVED
        plan["sign_off"] = {"who": str(who), "how": str(how),
                            "at": round(_now(), 3)}
        plan["updated"] = round(_now(), 3)
        self._save(plan)
        self._audit("plan-approve", plan=pid, state=APPROVED,
                    who=str(who))
        return dict(plan)

    def reject(self, pid, reason):
        plan = self._get_active(pid, {DRAFT, APPROVED})
        plan["status"] = REJECTED
        plan["updated"] = round(_now(), 3)
        plan["outcomes"].append({"t": round(_now(), 3),
                                 "event": "rejected",
                                 "reason": str(reason)})
        self._save(plan)
        self._audit("plan-reject", plan=pid, state=REJECTED)
        return dict(plan)

    def quarantine(self, pid, reason):
        plan = self.plans.get(pid)
        if plan is None:
            raise PlanError(f"unknown plan: {pid}")
        if plan["status"] not in ACTIVE_STATES:
            raise PlanError(f"plan {pid} already {plan['status']}")
        plan["status"] = QUARANTINED
        plan["updated"] = round(_now(), 3)
        plan["outcomes"].append({"t": round(_now(), 3),
                                 "event": "quarantined",
                                 "reason": str(reason)})
        self._save(plan)
        self._audit("plan-quarantine", plan=pid, state=QUARANTINED)
        return dict(plan)

    def commission(self, pid):
        """Hand every pending build step to the workshop as a live job.

        Manual steps stay pending until plan_step_done closes them.
        Requires an approved (or commissioned-with-new-build-steps? no -
        approved only) plan; idempotent per step."""
        plan = self._get_active(pid, {APPROVED})
        if self.ws is None:
            raise PlanError("no workshop bound - cannot commission")
        plan["status"] = COMMISSIONED
        plan["updated"] = round(_now(), 3)
        spawned = []
        for i, st in enumerate(plan["steps"]):
            if st["kind"] != STEP_BUILD or st["state"] != "pending":
                continue
            spec = dict(st["spec"])
            spec.setdefault("name", f"{pid}-{i}")
            try:
                job = self.ws.submit(spec)
            except Exception as exc:   # noqa: BLE001 - warden etc.
                st["state"] = "blocked"
                st["error"] = str(exc)[:200]
                continue
            st["job_id"] = job["id"]
            spawned.append({"step": i, "job": job["id"]})
        self._save(plan)
        self._audit("plan-commission", plan=pid, state=COMMISSIONED,
                    jobs=[s["job"] for s in spawned])
        return {"plan": dict(plan), "jobs": spawned}

    def step_done(self, pid, index, note=""):
        """Close one step manually (manual steps, or blocked builds
        after human review). Plan closes when all steps are closed."""
        plan = self._get_active(pid, {APPROVED, COMMISSIONED})
        if not 0 <= int(index) < len(plan["steps"]):
            raise PlanError(f"step index {index} out of range")
        st = plan["steps"][int(index)]
        if st["state"] == "closed":
            raise PlanError(f"step {index} already closed")
        st["state"] = "closed"
        if note:
            st["outcome_note"] = str(note)[:500]
        plan["outcomes"].append({"t": round(_now(), 3),
                                 "event": f"step-{index}-done"})
        if all(s["state"] == "closed" for s in plan["steps"]):
            plan["status"] = DONE
            self._audit("plan-done", plan=pid, state=DONE)
        plan["updated"] = round(_now(), 3)
        self._save(plan)
        return dict(plan)

    def notify_build(self, job_id, ok, result=None):
        """Workshop callback (from finalize): close any plan build step
        waiting on this job. Best-effort; never raises."""
        for pid, plan in list(self.plans.items()):
            if plan["status"] != COMMISSIONED:
                continue
            hit = False
            for i, st in enumerate(plan["steps"]):
                if st.get("job_id") == job_id \
                        and st["state"] in ("pending", "blocked"):
                    st["state"] = "closed"
                    st["ok"] = bool(ok)
                    if result:
                        st["result_sha256"] = result.get("artifact_sha256")
                        st["attempts"] = result.get("attempts")
                    if not ok and result:
                        st["error"] = str(result.get("stderr", ""))[-200:]
                    plan["outcomes"].append(
                        {"t": round(_now(), 3),
                         "event": f"build-step-{i}",
                         "job": job_id, "ok": bool(ok)})
                    hit = True
            if hit:
                if all(s["state"] == "closed" for s in plan["steps"]):
                    plan["status"] = DONE
                    plan["updated"] = round(_now(), 3)
                    self._audit("plan-done", plan=pid, state=DONE)
                else:
                    plan["updated"] = round(_now(), 3)
                self._save(plan)

    # ----------------------------------------------------- reporting --

    def summary(self):
        counts = {}
        for p in self.plans.values():
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        return {"plans": len(self.plans), "by_state": counts,
                "dir": self.dir}

    def list(self, status=None):
        rows = [{"id": p["id"], "title": p["title"],
                 "status": p["status"], "author": p["author"],
                 "steps": len(p["steps"]),
                 "open_steps": sum(1 for s in p["steps"]
                                   if s["state"] != "closed")}
                for p in self.plans.values()
                if status is None or p["status"] == status]
        return sorted(rows, key=lambda r: r["id"])

    def show(self, pid):
        plan = self.plans.get(pid)
        if plan is None:
            raise PlanError(f"unknown plan: {pid}")
        return dict(plan)
