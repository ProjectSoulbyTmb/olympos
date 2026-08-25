"""queue - crash-safe serial generation queue with a JSONL journal.

One GPU means one worker. Every state change is appended to
data/jobs.jsonl (tmp-write + atomic replace) so a hard kill can never
corrupt the journal; on boot orphaned running/pending jobs are marked
interrupted. The comfy calls are injectable for offline tests.
"""
import json
import os
import threading
import time
import uuid

from . import comfy, graphs, models


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class JobQueue(object):
    def __init__(self, data_dir, ai_home=None, comfy_base=None,
                 submit_fn=None, poll_fn=None, fetch_fn=None,
                 upload_fn=None):
        self.data_dir = data_dir
        self.ai_home = ai_home or models.default_ai_home(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.out_root = os.path.join(data_dir, "outputs")
        os.makedirs(self.out_root, exist_ok=True)
        self.journal_path = os.path.join(data_dir, "jobs.jsonl")
        self.comfy_base = comfy_base
        self._submit = submit_fn or comfy.submit
        self._poll = poll_fn or comfy.poll
        self._fetch = fetch_fn or comfy.fetch_outputs
        self._upload = upload_fn or comfy.upload_image
        self.jobs = {}
        self.order = []
        self._lock = threading.Lock()
        self._journal_lock = threading.Lock()
        self._wake = threading.Event()
        self._stop_flag = False
        self._thread = None
        self._load_journal()

    # ------------------------------------------------------------ journal
    def _load_journal(self):
        if not os.path.isfile(self.journal_path):
            return
        try:
            with open(self.journal_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue  # torn tail write from a hard kill
                    jid = rec.get("id")
                    if not jid:
                        continue
                    self.jobs[jid] = rec
                    if jid not in self.order:
                        self.order.append(jid)
        except OSError:
            pass
        # anything mid-flight at boot died with the process
        for rec in self.jobs.values():
            if rec["status"] in ("pending", "running"):
                self._set(rec["id"], "error",
                          error="interrupted by restart")

    def _append(self, rec):
        tmp = "%s.%s.tmp" % (self.journal_path, uuid.uuid4().hex[:8])
        with self._journal_lock:
            with open(tmp, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.journal_path)

    def _set(self, jid, status, **extra):
        with self._lock:
            rec = self.jobs[jid]
            rec["status"] = status
            rec["updated"] = _now()
            rec.update(extra)
            snapshot = dict(rec)
        self._append(snapshot)

    # ------------------------------------------------------------- public
    def submit(self, kind, params=None, priority=False):
        jid = uuid.uuid4().hex[:12]
        rec = {"id": jid, "kind": kind, "params": params or {},
               "status": "pending", "error": None, "files": [],
               "created": _now(), "updated": _now()}
        with self._lock:
            self.jobs[jid] = rec
            if priority:
                self.order.insert(0, jid)
            else:
                self.order.append(jid)
        self._append(rec)
        self._wake.set()
        return jid

    def cancel(self, jid):
        with self._lock:
            rec = self.jobs.get(jid)
            if not rec or rec["status"] != "pending":
                return False
        self._set(jid, "cancelled")
        return True

    def get(self, jid):
        with self._lock:
            rec = self.jobs.get(jid)
            return dict(rec) if rec else None

    def recent(self, limit=50):
        with self._lock:
            out = []
            for jid in reversed(self.order[-limit:]):
                out.append(dict(self.jobs[jid]))
            return out

    def counts(self):
        with self._lock:
            pend = sum(1 for r in self.jobs.values()
                       if r["status"] == "pending")
            run = sum(1 for r in self.jobs.values()
                      if r["status"] == "running")
        return {"pending": pend, "running": run}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, timeout=5.0):
        self._stop_flag = True
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    # -------------------------------------------------------------- worker
    def _loop(self):
        while not self._stop_flag:
            jid = None
            with self._lock:
                for cand in self.order:
                    if self.jobs[cand]["status"] == "pending":
                        jid = cand
                        break
            if jid is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            self._set(jid, "running")
            try:
                files = self._run_job(jid)
                self._set(jid, "done", files=files)
            except Exception as exc:  # noqa: BLE001 - journal everything
                self._set(jid, "error", error=str(exc)[:500])

    def _run_job(self, jid):
        rec = self.get(jid)
        kind = rec["kind"]
        params = dict(rec["params"])
        outdir = os.path.join(self.out_root, jid)
        graph = self._build_graph(kind, params)
        prompt_id = self._submit(graph, base_url=self.comfy_base)
        entry = self._poll(prompt_id, base_url=self.comfy_base,
                           timeout=float(params.get("timeout", 3600)))
        return self._fetch(entry, outdir, base_url=self.comfy_base)

    def _build_graph(self, kind, params):
        params = dict(params)
        model_key = params.pop("model", None)
        if kind == "upscale":
            uploaded = self._upload(params.pop("image"),
                                    base_url=self.comfy_base)
            return graphs.g_upscale(
                uploaded, float(params.get("scale_by", 2.0)))
        if kind.startswith("img2"):
            src = params.pop("image")
            params["_uploaded"] = self._upload(src,
                                               base_url=self.comfy_base)
        if model_key:
            resolved = models.resolve(model_key, self.ai_home)
            return self._graph_for(kind, resolved, params)
        return self._graph_direct(kind, params)

    def _graph_direct(self, kind, params):
        """Call an explicit graph builder with exactly its own kwargs."""
        import inspect
        fn = graphs.BUILDERS.get(kind)
        if not fn:
            raise ValueError("unknown generation kind %r "
                             "(or pass a supported 'model' key)" % kind)
        params = dict(params)
        if "_uploaded" in params and "uploaded_image" in \
                inspect.signature(fn).parameters:
            params["uploaded_image"] = params.pop("_uploaded")
        sig = inspect.signature(fn)
        kwargs = {k: v for k, v in params.items() if k in sig.parameters}
        missing = [p.name for p in sig.parameters.values()
                   if p.name not in kwargs
                   and p.default is inspect.Parameter.empty]
        if missing:
            raise ValueError("kind %r missing required args: %s"
                             % (kind, ", ".join(missing)))
        return fn(**kwargs)

    @staticmethod
    def _graph_for(kind, resolved, params):
        params = dict(params)
        seed = int(params.pop("seed", 0))
        prompt = params.pop("prompt", "")
        negative = params.pop("negative", "")
        if kind == "txt2img":
            if "checkpoint" in resolved:
                return graphs.g_txt2img_checkpoint(
                    resolved["checkpoint"], prompt, negative,
                    int(params.pop("width", 512)),
                    int(params.pop("height", 512)),
                    int(params.pop("steps", 20)),
                    float(params.pop("cfg", 7.0)), seed)
            if "clip2" in resolved:  # SDXL dual-encoder GGUF path
                return graphs.g_txt2img_gguf_sdxl(
                    resolved["unet"], resolved["clip1"], resolved["clip2"],
                    resolved["vae"], prompt, negative,
                    int(params.pop("width", 768)),
                    int(params.pop("height", 768)),
                    int(params.pop("steps", 24)),
                    float(params.pop("cfg", 6.5)), seed)
            return graphs.g_txt2img_gguf_flux(
                resolved["unet"], resolved.get("clip1"), resolved["t5"],
                resolved["vae"], prompt, negative,
                int(params.pop("width", 768)),
                int(params.pop("height", 768)),
                int(params.pop("steps", 4)), float(params.pop("cfg", 1.0)),
                seed)
        if kind in ("txt2vid", "img2vid"):
            args = [resolved["unet"], resolved["vae"], resolved["t5"]]
            if kind == "img2vid":
                args.append(params.pop("_uploaded"))
            args.append(prompt)
            kw = {"negative": negative, "seed": seed}
            for k in ("width", "height", "length", "fps", "steps", "cfg"):
                if k in params:
                    v = params[k]
                    kw[k] = int(v) if k != "cfg" else float(v)
            fn = graphs.g_img2vid_ltx if kind == "img2vid" \
                else graphs.g_txt2vid_ltx
            return fn(*args, **kw)
        raise ValueError("no graph route for kind %r" % kind)
