"use strict";

// main - Riley Studio shell.
//
// One Electron app, several faces: Canvas (create), Gallery (browse),
// Models (pull weights), Wizard (first-run setup). The main process
// owns the engine lifecycle: it starts the loopback Python API when no
// engine is already answering, health-polls every few seconds and
// restarts the child with backoff if it dies. The tray gives quick
// access to everything without a window.

const { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, dialog } =
  require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");

const PORT = Number(process.env.RILEY_STUDIO_PORT || 8288);
const BASE = `http://127.0.0.1:${PORT}`;
const SMOKE = process.env.RILEY_STUDIO_SMOKE === "1";

let tray = null;
let quitting = false;
let engineChild = null;
let engineFails = 0;
const wins = { canvas: null, gallery: null, models: null, wizard: null };

function engineDir() {
  // dev layout: studio/ lives inside riley-studio/ next to server.py;
  // packaged builds expect RILEY_STUDIO_HOME to point at that root.
  const home = process.env.RILEY_STUDIO_HOME;
  if (home) return home;
  return path.resolve(app.getAppPath(), "..");
}

async function engineUp(timeoutMs = 1500) {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeoutMs);
    const r = await fetch(`${BASE}/api/status`, { signal: ctl.signal });
    clearTimeout(t);
    return r.ok;
  } catch (_) {
    return false;
  }
}

function spawnEngine() {
  const dir = engineDir();
  if (!fs.existsSync(path.join(dir, "server.py"))) {
    console.log(`[engine] no server.py at ${dir} - run setup_studio.ps1`);
    return null;
  }
  const py = process.env.RILEY_PYTHON || "python";
  const child = spawn(py, ["server.py", "--port", String(PORT)], {
    cwd: dir,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", () => {});
  child.stderr.on("data", (b) =>
    console.log(`[engine] ${String(b).trim().slice(0, 200)}`));
  child.on("exit", () => {
    if (engineChild === child) engineChild = null;
  });
  return child;
}

async function ensureEngine() {
  if (await engineUp()) {
    engineFails = 0;
    if (engineChild && !engineChild.killed) {
      // someone else's instance is serving; drop our redundant child
      try { engineChild.kill(); } catch (_) {}
      engineChild = null;
    }
    return true;
  }
  if (!engineChild) engineChild = spawnEngine();
  return false;
}

function startEngineWatch() {
  setInterval(async () => {
    const up = await ensureEngine();
    if (up) {
      engineFails = 0;
    } else {
      engineFails += 1;
      if (engineFails > 30 && engineChild) {
        try { engineChild.kill(); } catch (_) {}
        engineChild = null; // give up for a while; next poll respawns once
        engineFails = 0;
      }
    }
    if (tray) {
      tray.setToolTip(up ? `Riley Studio - engine up :${PORT}`
                         : `Riley Studio - engine down (:${PORT})`);
    }
  }, 4000);
}

function createWindow(name, opts) {
  if (wins[name] && !wins[name].isDestroyed()) {
    wins[name].focus();
    return wins[name];
  }
  const w = (wins[name] = new BrowserWindow(
    Object.assign({
      backgroundColor: "#14121c",
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, "preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: false,
      },
    }, opts)));
  w.loadFile(path.join(__dirname, "renderer", `${name}.html`));
  w.on("closed", () => { wins[name] = null; });
  return w;
}

function openFace(name) {
  const sizes = {
    canvas: { width: 1440, height: 900, minWidth: 1080, minHeight: 680 },
    gallery: { width: 1020, height: 700, minWidth: 720, minHeight: 480 },
    models: { width: 940, height: 660, minWidth: 720, minHeight: 480 },
    wizard: { width: 760, height: 540, minWidth: 640, minHeight: 460 },
  };
  createWindow(name, Object.assign({ title: `Riley Studio - ${name}` },
                                   sizes[name] || {}));
}

function makeTray() {
  let img;
  try {
    img = nativeImage.createFromPath(
      path.join(__dirname, "assets", "tray.png"));
  } catch (_) { img = nativeImage.createEmpty(); }
  tray = new Tray(img);
  tray.setToolTip("Riley Studio");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Open Studio", click: () => openFace("canvas") },
    { label: "Gallery", click: () => openFace("gallery") },
    { label: "Models", click: () => openFace("models") },
    { type: "separator" },
    { label: `Engine: 127.0.0.1:${PORT}`, enabled: false },
    { role: "quit", label: "Quit Riley Studio" },
  ]));
}

// ------------------------------------------------------------------ ipc

ipcMain.handle("api:get", async (_e, p) => {
  try {
    const r = await fetch(BASE + p);
    return await r.json();
  } catch (err) {
    return { ok: false, error: String(err.message || err) };
  }
});

ipcMain.handle("api:post", async (_e, p, body) => {
  try {
    const r = await fetch(BASE + p, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return await r.json();
  } catch (err) {
    return { ok: false, error: String(err.message || err) };
  }
});

ipcMain.handle("file:url", (_e, rel) =>
  `${BASE}/api/file?p=${encodeURIComponent(rel)}`);

ipcMain.handle("file:saveDataUrl", async (_e, { name, dataUrl }) => {
  const m = /^data:(image\/(png|jpeg));base64,(.+)$/.exec(
    String(dataUrl || ""));
  if (!m) return { ok: false, error: "not a base64 image data url" };
  const r = await dialog.showSaveDialog(wins.canvas || undefined, {
    defaultPath: name || "export.png",
    filters: [{ name: "Image",
                extensions: [m[2] === "jpeg" ? "jpg" : "png"] }],
  });
  if (r.canceled || !r.filePath) return { ok: false, cancelled: true };
  fs.writeFileSync(r.filePath, Buffer.from(m[3], "base64"));
  return { ok: true, path: r.filePath };
});

ipcMain.handle("project:save", async (_e, { name, data }) => {
  const r = await dialog.showSaveDialog(wins.canvas || undefined, {
    defaultPath: name || "untitled.rsproj",
    filters: [{ name: "Riley Studio Project", extensions: ["rsproj"] }],
  });
  if (r.canceled || !r.filePath) return { ok: false, cancelled: true };
  fs.writeFileSync(r.filePath, data, "utf8");
  return { ok: true, path: r.filePath };
});

ipcMain.handle("project:open", async () => {
  const r = await dialog.showOpenDialog(wins.canvas || undefined, {
    properties: ["openFile"],
    filters: [{ name: "Riley Studio Project", extensions: ["rsproj"] }],
  });
  if (r.canceled || !r.filePaths[0]) return { ok: false, cancelled: true };
  try {
    return { ok: true, path: r.filePaths[0],
             data: fs.readFileSync(r.filePaths[0], "utf8") };
  } catch (err) {
    return { ok: false, error: String(err.message || err) };
  }
});

ipcMain.handle("win:open", (_e, name) => { openFace(name); return true; });

ipcMain.handle("engine:info", () =>
  ({ base: BASE, owned: !!engineChild }));

// ------------------------------------------------------------------ app

app.whenReady().then(async () => {
  if (SMOKE) {
    const img = nativeImage.createFromPath(
      path.join(__dirname, "assets", "tray.png"));
    if (img.isEmpty()) throw new Error("tray image failed to decode");
    console.log("SMOKE OK");
    app.exit(0);
    return;
  }
  Menu.setApplicationMenu(null);
  makeTray();
  openFace("canvas");
  startEngineWatch();
  await ensureEngine();
});

app.on("before-quit", () => {
  quitting = true;
  if (engineChild) { try { engineChild.kill(); } catch (_) {} }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin" && !quitting) app.quit();
});
