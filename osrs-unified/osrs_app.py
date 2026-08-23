"""OSRS Suite - native Windows GUI for osrs-unified.

Tkinter app that runs bench.py / train.py / evaluate.py /
tools-update_knowledge.py as subprocesses and streams their output.

Launch:  pythonw osrs_app.py   (or double-click "Launch OSRS Suite.bat",
or run the packaged OSRS-Suite.exe kept next to this project's files).
"""
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "OSRS Suite"
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW


def is_frozen():
    return getattr(sys, "frozen", False)


def find_python():
    if not is_frozen():
        return sys.executable
    for name in ("python.exe", "py.exe"):
        p = shutil.which(name)
        if p:
            return p
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")
    if os.path.isdir(base):
        for entry in sorted(os.listdir(base), reverse=True):
            if entry.lower().startswith("python"):
                cand = os.path.join(base, entry, "python.exe")
                if os.path.exists(cand):
                    return cand
    return "python"


def _is_root(d):
    return bool(d) and os.path.exists(os.path.join(d, "bench.py"))


def detect_root():
    env = os.environ.get("OSRS_ROOT")
    if env and _is_root(env):
        return env
    if is_frozen():
        starts = [os.path.dirname(os.path.abspath(sys.executable))]
        fallback = starts[0]
    else:
        starts = [os.path.dirname(os.path.abspath(__file__)),
                  os.path.dirname(os.path.abspath(sys.argv[0]))]
        fallback = starts[0]
    for start in starts:
        cand = start
        for _ in range(5):
            if _is_root(cand):
                return cand
            parent = os.path.dirname(cand)
            if parent == cand:
                break
            cand = parent
    return fallback


ROOT = detect_root()


class JobRunner:
    def __init__(self, app):
        self.app = app
        self.proc = None
        self.q = queue.Queue()
        self.started_at = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, script, args, cwd):
        if self.running:
            messagebox.showwarning(APP_TITLE,
                                   "A job is already running - stop it first.")
            return False
        cmd = [find_python(), script] + [str(a) for a in args]
        self.app.log(f"> {subprocess.list2cmdline(cmd)}\n")
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=cwd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace",
                creationflags=CREATE_FLAGS)
        except OSError as e:
            self.app.log(f"[error] could not launch: {e}\n")
            messagebox.showerror(APP_TITLE, f"Could not launch python:\n{e}")
            return False
        self.started_at = time.time()
        self.app.set_status("running")
        threading.Thread(target=self._pump, daemon=True).start()
        self.app.root.after(80, self._drain)
        return True

    def _pump(self):
        proc = self.proc
        for line in proc.stdout:
            self.q.put(line)
        self.q.put(None)

    def _drain(self):
        alive = False
        while True:
            try:
                line = self.q.get_nowait()
            except queue.Empty:
                alive = True
                break
            if line is None:
                dt = time.time() - (self.started_at or time.time())
                self.app.log(f"[job finished in {dt:.1f}s]\n")
                self.proc = None
                self.app.set_status("idle")
                return
            self.app.log(line)
        if alive and self.running:
            self.app.root.after(80, self._drain)

    def stop(self):
        if not self.running:
            return
        subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                       capture_output=True, creationflags=CREATE_FLAGS)
        self.app.log("[stopped by user]\n")


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1000x700")
        self.root.minsize(860, 560)
        self.runner = JobRunner(self)
        self.tasks = ["wc_xp", "gold", "total_xp", "cook_xp", "uim_total_xp"]
        self._build_menu()
        self._build_layout()
        self._build_bench_tab()
        self._build_rl_tab()
        self._build_knowledge_tab()
        self.log(f"root: {ROOT}\npython: {find_python()}\nready.\n")

    def set_status(self, text):
        self.status_var.set(text)

    def log(self, text):
        self.console.configure(state="normal")
        self.console.insert("end", text)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _build_menu(self):
        m = tk.Menu(self.root)
        r = tk.Menu(m, tearoff=0)
        r.add_command(label="Open runs folder",
                      command=lambda: self._open(os.path.join(ROOT, "runs")))
        r.add_command(label="Open project folder", command=lambda:
                      self._open(ROOT))
        r.add_separator()
        r.add_command(label="Quit", command=self.root.destroy)
        m.add_cascade(label="File", menu=r)
        h = tk.Menu(m, tearoff=0)
        h.add_command(label="About", command=lambda: messagebox.showinfo(
            APP_TITLE, "osrs-unified 1.0.0\nSkilling LLM agent + PvP RL suite."
                       "\nLocal simulation only."))
        m.add_cascade(label="Help", menu=h)
        self.root.config(menu=m)

    @staticmethod
    def _open(path):
        if os.path.isdir(path):
            os.startfile(path)

    def _build_layout(self):
        pane = ttk.Panedwindow(self.root, orient="vertical")
        pane.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(pane)
        pane.add(self.notebook, weight=3)
        bottom = ttk.Labelframe(pane, text="Console")
        pane.add(bottom, weight=2)
        self.console = tk.Text(bottom, height=12, state="disabled",
                               font=("Consolas", 9), wrap="none")
        ys = ttk.Scrollbar(bottom, orient="vertical",
                           command=self.console.yview)
        self.console.configure(yscrollcommand=ys.set)
        self.console.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="idle")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left",
                                                          padx=6)
        ttk.Button(bar, text="Stop job", command=self.runner.stop)\
            .pack(side="right", padx=6, pady=3)
        ttk.Button(bar, text="Clear console",
                   command=self.clear_console)\
            .pack(side="right", padx=6, pady=3)

    def clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self.log("--- cleared ---\n")

    def _row(self, parent, label):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=label, width=16).pack(side="left")
        return f

    def _build_bench_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Skilling Bench")
        row = self._row(tab, "Task")
        self.task_var = tk.StringVar(value=self.tasks[0])
        cb = ttk.Combobox(row, textvariable=self.task_var, values=self.tasks,
                          state="readonly", width=18)
        cb.pack(side="left")

        row = self._row(tab, "Tick budget")
        self.ticks_var = tk.IntVar(value=3000)
        ttk.Spinbox(row, from_=100, to=100000, increment=100,
                    textvariable=self.ticks_var, width=8).pack(side="left")

        self.mode_var = tk.StringVar(value="manual")
        row = self._row(tab, "Mode")
        ttk.Radiobutton(row, text="Manual strategy file",
                        variable=self.mode_var, value="manual")\
            .pack(side="left")
        ttk.Radiobutton(row, text="LLM agent (Ollama/OpenAI-compatible)",
                        variable=self.mode_var, value="llm").pack(side="left",
                                                                  padx=8)

        self.code_row = self._row(tab, "Strategy file")
        self.code_var = tk.StringVar(
            value=os.path.join(ROOT, "strategies", "example_bot.py"))
        ttk.Entry(self.code_row, textvariable=self.code_var)\
            .pack(side="left", fill="x", expand=True)
        ttk.Button(self.code_row, text="Browse...", command=self._pick_code)\
            .pack(side="left", padx=4)
        self.saveevery_var = tk.IntVar(value=0)
        ttk.Label(self.code_row, text="autosave every").pack(side="left",
                                                             padx=(10, 2))
        ttk.Spinbox(self.code_row, from_=0, to=5000, increment=50,
                    textvariable=self.saveevery_var,
                    width=6).pack(side="left")

        llm = ttk.Labelframe(tab, text="LLM settings", padding=6)
        llm.pack(fill="x", pady=6)
        row = self._row(llm, "Base URL")
        self.url_var = tk.StringVar(
            value=os.environ.get("LLM_BASE_URL",
                                 "http://localhost:11434/v1"))
        ttk.Entry(row, textvariable=self.url_var).pack(side="left",
                                                       fill="x", expand=True)
        row = self._row(llm, "Model")
        self.model_var = tk.StringVar(
            value=os.environ.get("LLM_MODEL", "llama3.1:8b"))
        ttk.Entry(row, textvariable=self.model_var, width=28).pack(side="left")
        row = self._row(llm, "Rounds")
        self.rounds_var = tk.IntVar(value=8)
        ttk.Spinbox(row, from_=1, to=100, textvariable=self.rounds_var,
                    width=6).pack(side="left")

        ttk.Button(tab, text="Run benchmark", command=self.run_bench)\
            .pack(anchor="w", pady=8)

    def _pick_code(self):
        path = filedialog.askopenfilename(
            title="Choose strategy file",
            initialdir=os.path.join(ROOT, "strategies"),
            filetypes=[("Python", "*.py"), ("All files", "*.*")])
        if path:
            self.code_var.set(path)

    def run_bench(self):
        args = ["--task", self.task_var.get(), "--ticks", self.ticks_var.get()]
        if self.mode_var.get() == "manual":
            code = self.code_var.get().strip()
            if not os.path.exists(code):
                messagebox.showerror(APP_TITLE,
                                     f"Strategy file not found:\n{code}")
                return
            args += ["--code-file", code]
            if self.saveevery_var.get() > 0:
                args += ["--save-every", self.saveevery_var.get()]
        else:
            args += ["--base-url", self.url_var.get(),
                     "--model", self.model_var.get(),
                     "--rounds", self.rounds_var.get()]
        self.runner.start("bench.py", args, ROOT)

    def _build_rl_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="PvP RL")

        tr = ttk.Labelframe(tab, text="Train (self-play PPO)", padding=8)
        tr.pack(fill="x", pady=(0, 10))
        row = self._row(tr, "Run name")
        self.name_var = tk.StringVar(value="v3")
        ttk.Entry(row, textvariable=self.name_var, width=14).pack(side="left")
        ttk.Label(row, text="iters").pack(side="left", padx=(12, 2))
        self.iters_var = tk.IntVar(value=200)
        ttk.Spinbox(row, from_=1, to=100000, textvariable=self.iters_var,
                    width=7).pack(side="left")
        ttk.Label(row, text="episodes").pack(side="left", padx=(12, 2))
        self.episodes_var = tk.IntVar(value=40)
        ttk.Spinbox(row, from_=1, to=1000, textvariable=self.episodes_var,
                    width=6).pack(side="left")
        row = self._row(tr, "Collector")
        self.fast_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="fast batched", variable=self.fast_var)\
            .pack(side="left")
        ttk.Label(row, text="slots").pack(side="left", padx=(12, 2))
        self.slots_var = tk.IntVar(value=16)
        ttk.Spinbox(row, from_=1, to=64, textvariable=self.slots_var,
                    width=5).pack(side="left")
        row = self._row(tr, "Resume")
        self.resume_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="continue from ckpt_latest.pt "
                                  "(same run name)",
                        variable=self.resume_var).pack(side="left")
        ttk.Button(tr, text="Start training", command=self.run_train)\
            .pack(anchor="w", pady=6)

        ev = ttk.Labelframe(tab, text="Evaluate checkpoint", padding=8)
        ev.pack(fill="x")
        row = self._row(ev, "Checkpoint")
        self.ckpt_var = tk.StringVar(
            value=os.path.join(ROOT, "runs", "v2", "ckpt_latest.pt"))
        ttk.Entry(ev, textvariable=self.ckpt_var)\
            .pack(side="left", fill="x", expand=True)
        ttk.Button(ev, text="Browse...",
                   command=lambda: self._pick_file(self.ckpt_var,
                                                   ROOT, "runs")).pack(
            side="left", padx=4)
        ttk.Label(ev, text="matches").pack(side="left", padx=(10, 2))
        self.matches_var = tk.IntVar(value=100)
        ttk.Spinbox(ev, from_=1, to=2000, textvariable=self.matches_var,
                    width=6).pack(side="left")
        ttk.Button(ev, text="Evaluate", command=self.run_eval)\
            .pack(anchor="w", pady=6)

    def _pick_file(self, var, initialdir, subdir=""):
        start = os.path.join(initialdir, subdir) if subdir else initialdir
        path = filedialog.askopenfilename(initialdir=start)
        if path:
            var.set(path)

    def run_train(self):
        args = ["--name", self.name_var.get(), "--iters", self.iters_var.get(),
                "--episodes", self.episodes_var.get()]
        if self.fast_var.get():
            args += ["--fast", "--slots", self.slots_var.get()]
        if self.resume_var.get():
            args.append("--resume")
        self.runner.start("train.py", args, ROOT)

    def run_eval(self):
        ckpt = self.ckpt_var.get().strip()
        if not os.path.exists(ckpt):
            messagebox.showerror(APP_TITLE, f"Checkpoint not found:\n{ckpt}")
            return
        self.runner.start("evaluate.py",
                          [ckpt, "--matches", self.matches_var.get()], ROOT)

    def _build_knowledge_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Knowledge")
        info = ("Refreshes ground-truth data used by the LLM agent:\n"
                "Grand Exchange live prices + OSRS Wiki extracts.\n"
                "Writes knowledge/digest.md, ground_truth.json and raw/ "
                "snapshots.")
        ttk.Label(tab, text=info, justify="left").pack(anchor="w", pady=6)
        self.kstatus_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.kstatus_var,
                  justify="left").pack(anchor="w")
        ttk.Button(tab, text="Update knowledge now",
                   command=self.run_knowledge).pack(anchor="w", pady=8)
        self.refresh_knowledge_status()

    def refresh_knowledge_status(self):
        digest = os.path.join(ROOT, "knowledge", "digest.md")
        prices = os.path.join(ROOT, "knowledge", "live", "ge_prices.json")
        parts = []
        for label, path in (("digest.md", digest), ("ge_prices.json", prices)):
            if os.path.exists(path):
                age_h = (time.time() - os.path.getmtime(path)) / 3600
                parts.append(f"{label}: updated {age_h:.1f}h ago")
            else:
                parts.append(f"{label}: missing")
        self.kstatus_var.set(" | ".join(parts))

    def run_knowledge(self):
        ok = self.runner.start(os.path.join(ROOT, "tools",
                                            "update_knowledge.py"), [], ROOT)
        if ok:
            self.root.after(1500, self.refresh_knowledge_status)

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        if self.runner.running and not messagebox.askokcancel(
                APP_TITLE, "A job is still running. Quit anyway?"):
            return
        self.runner.stop()
        self.root.destroy()


def selftest():
    app = App()
    app.root.update()
    tabs = app.notebook.tabs()
    assert len(tabs) == 3, tabs
    app.root.destroy()
    print("GUI self-test OK")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    App().run()


if __name__ == "__main__":
    main()
