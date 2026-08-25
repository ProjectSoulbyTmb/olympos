"use strict";

const api = window.riley;
const $ = (id) => document.getElementById(id);

function human(n) {
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + u[i];
}

function card(key, m) {
  const d = document.createElement("div");
  d.className = "model";
  const head = document.createElement("div");
  head.className = "head";
  const title = document.createElement("b");
  title.textContent = m.label;
  const badge = document.createElement("span");
  badge.className = "badge " +
    (m.complete ? "ok" : m.tier === "video" ? "vid" : "");
  badge.textContent = m.complete
    ? "installed"
    : `${m.tier} · ${m.vram_gb}GB · ${human(m.files.reduce(
        (a, f) => a + f.bytes, 0))}`;
  head.append(title, badge);
  const notes = document.createElement("div");
  notes.className = "notes";
  notes.textContent = m.notes || "";
  const files = document.createElement("ul");
  for (const f of m.files) {
    const li = document.createElement("li");
    li.textContent = `${f.role}: ${f.name} (${human(f.bytes)})` +
                     (f.gated ? " — license-gated upstream" : "");
    files.appendChild(li);
  }
  const btn = document.createElement("button");
  btn.className = "primary";
  btn.textContent = m.complete ? "Re-check / finish pull"
                               : "Pull all pieces";
  btn.onclick = async () => {
    const r = await api.post("/api/models/pull", { key });
    state(r.ok ? `pull started for ${key}` :
                 `pull refused: ${r.message || r.error}`);
  };
  d.append(head, notes, files, btn);
  return d;
}

function state(msg) { $("state").textContent = msg; refresh(); }

async function refresh() {
  const r = await api.get("/api/models");
  const list = $("list");
  list.textContent = "";
  if (!r.ok) {
    $("vram").textContent = "engine offline";
    return;
  }
  $("vram").textContent =
    `detected VRAM: ${r.vram_mb ? r.vram_mb + " MB" : "none/CPU"}` +
    ` · recommended first pull: ${r.recommended[0]}`;
  const dl = r.downloads || {};
  for (const [key, m] of Object.entries(r.models)) {
    const c = card(key, m);
    const prog = dl[key];
    if (prog && !prog.done && !prog.error && prog.total) {
      const bar = document.createElement("div");
      bar.className = "bar";
      const fill = document.createElement("i");
      fill.style.width =
        Math.min(100, Math.round(prog.written / prog.total * 100)) + "%";
      bar.appendChild(fill);
      const pct = document.createElement("div");
      pct.className = "notes";
      pct.textContent =
        `${Math.round(prog.written / prog.total * 100)}% ` +
        `(${human(prog.written)} of ${human(prog.total)})`;
      c.append(bar, pct);
    } else if (prog && prog.error) {
      const err = document.createElement("div");
      err.className = "notes err";
      err.textContent = "download error: " + prog.error;
      c.appendChild(err);
    } else if (prog && prog.done) {
      const okd = document.createElement("div");
      okd.className = "notes";
      okd.style.color = "var(--ok)";
      okd.textContent = "download complete";
      c.appendChild(okd);
    }
    list.appendChild(c);
  }
}

refresh();
setInterval(refresh, 4000);
