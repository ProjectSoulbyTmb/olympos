"use strict";

// canvas - Riley Studio's creation surface.
// Layers are plain absolutely-positioned divs inside #stage; the project
// object is the source of truth and every mutation re-renders. The
// Generate panel drives the loopback engine API through preload.

const api = window.riley;
const project = api.project;

let proj = project.emptyProject();
let selId = null;
let dirty = false;
let genBusy = false;
const els = new Map(); // layer id -> DOM node

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------ render */

function fitStage() {
  const wrap = $("stageWrap");
  const s = Math.min(wrap.clientWidth / proj.width,
                     wrap.clientHeight / proj.height, 1);
  const st = $("stage");
  st.style.width = proj.width + "px";
  st.style.height = proj.height + "px";
  st.style.transform = `scale(${s})`;
}

function fileSrc(rel) { return api.fileUrl(rel); }

function layerNode(l) {
  const d = document.createElement("div");
  d.className = "layerEl" + (l.id === selId ? " sel" : "");
  d.style.left = l.x + "px";
  d.style.top = l.y + "px";
  d.style.width = l.w + "px";
  d.style.height = l.h + "px";
  d.style.opacity = l.opacity;
  d.style.visibility = l.visible ? "visible" : "hidden";
  if (l.rot) d.style.transform = `rotate(${l.rot}deg)`;
  if (l.type === "image" && l.src) {
    const img = document.createElement("img");
    img.src = l.src.startsWith("http") || l.src.startsWith("data:")
      ? l.src : fileSrc(l.src);
    img.draggable = false;
    d.appendChild(img);
  } else if (l.type === "text") {
    d.style.color = l.color || "#fff";
    d.style.fontSize = (l.fontSize || 48) + "px";
    d.style.fontWeight = "700";
    d.style.whiteSpace = "pre-wrap";
    d.textContent = l.text || "";
  } else {
    d.style.background = l.color || "#7c5cff";
    d.style.borderRadius = "10px";
  }
  if (!l.locked) {
    const h = document.createElement("div");
    h.className = "handle";
    h.addEventListener("pointerdown", (e) => startResize(e, l.id));
    d.appendChild(h);
  }
  d.addEventListener("pointerdown", (e) => {
    select(l.id);
    if (!l.locked) startMove(e, l.id);
  });
  return d;
}

function render() {
  const stage = $("stage");
  stage.style.background = proj.bg;
  const keep = new Set(proj.layers.map((l) => l.id));
  for (const [id, node] of els) {
    if (!keep.has(id)) { node.remove(); els.delete(id); }
  }
  for (const l of proj.layers) {
    const node = layerNode(l);
    if (els.has(l.id)) {
      els.get(l.id).replaceWith(node);
    } else {
      stage.appendChild(node);
    }
    els.set(l.id, node);
  }
  renderLayerList();
  renderProps();
  fitStage();
}

function renderLayerList() {
  const list = $("layerList");
  list.textContent = "";
  [...proj.layers].reverse().forEach((l) => {
    const row = document.createElement("div");
    row.className = "layrow" + (l.id === selId ? " sel" : "");
    const eye = document.createElement("button");
    eye.className = "ghost";
    eye.textContent = l.visible ? "◉" : "○";
    eye.title = "toggle visibility";
    eye.onclick = (e) => { e.stopPropagation(); l.visible = !l.visible;
                           touch(); };
    const name = document.createElement("span");
    name.textContent = l.name + (l.locked ? " 🔒" : "");
    row.append(eye, name);
    row.onclick = () => select(l.id);
    list.appendChild(row);
  });
}

/* ----------------------------------------------------------- editing */

function current() {
  return proj.layers.find((l) => l.id === selId) || null;
}

function touch() { dirty = true; render(); }

function select(id) {
  selId = id;
  for (const [lid, node] of els) {
    node.classList.toggle("sel", lid === id);
  }
  renderLayerList();
  renderProps();
}

function addLayer(partial) {
  const base = {
    type: "rect",
    x: Math.round(proj.width * 0.2),
    y: Math.round(proj.height * 0.2),
    w: Math.round(proj.width * 0.3),
    h: Math.round(proj.height * 0.3),
    opacity: 1,
    visible: true,
    locked: false,
  };
  const l = Object.assign(base, partial);
  l.id = "L" + Date.now().toString(36) +
         Math.random().toString(36).slice(2, 6);
  proj.layers.push(l);
  select(l.id);
  touch();
  return l;
}

function startMove(e, id) {
  e.preventDefault();
  const stage = $("stage").getBoundingClientRect();
  const scale = stage.width / proj.width;
  const l = proj.layers.find((x) => x.id === id);
  const ox = e.clientX, oy = e.clientY, lx = l.x, ly = l.y;
  const move = (ev) => {
    l.x = Math.round(lx + (ev.clientX - ox) / scale);
    l.y = Math.round(ly + (ev.clientY - oy) / scale);
    const n = els.get(id);
    n.style.left = l.x + "px";
    n.style.top = l.y + "px";
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    touch();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function startResize(e, id) {
  e.preventDefault();
  e.stopPropagation();
  const stage = $("stage").getBoundingClientRect();
  const scale = stage.width / proj.width;
  const l = proj.layers.find((x) => x.id === id);
  const ox = e.clientX, oy = e.clientY, lw = l.w, lh = l.h;
  const move = (ev) => {
    l.w = Math.max(12, Math.round(lw + (ev.clientX - ox) / scale));
    l.h = Math.max(12, Math.round(lh + (ev.clientY - oy) / scale));
    const n = els.get(id);
    n.style.width = l.w + "px";
    n.style.height = l.h + "px";
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    touch();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

/* --------------------------------------------------------- inspector */

function renderProps() {
  const l = current();
  const box = $("props");
  if (!l) {
    box.style.display = "none";
    $("propName").textContent = "nothing selected";
    return;
  }
  box.style.display = "";
  $("propName").textContent = `${l.type} · ${l.name}`;
  $("pX").value = l.x; $("pY").value = l.y;
  $("pW").value = l.w; $("pH").value = l.h;
  $("pRot").value = l.rot; $("pRotV").textContent = l.rot + "°";
  $("pOpa").value = Math.round(l.opacity * 100);
  $("pOpaV").textContent = Math.round(l.opacity * 100) + "%";
  const tp = $("textProps");
  if (l.type === "text") {
    tp.style.display = "";
    $("pText").value = l.text || "";
    $("pFontSize").value = l.fontSize || 48;
    $("pColor").value = l.color && l.color[0] === "#"
      ? l.color : "#ffffff";
  } else {
    tp.style.display = "none";
  }
  if (l.type === "rect") $("pColor").value = "#7c5cff";
}

function bindProp(id, fn) {
  $(id).addEventListener("input", () => {
    const l = current();
    if (!l) return;
    fn(l);
    dirty = true;
    render();
  });
}

bindProp("pX", (l) => { l.x = Number($("pX").value) || 0; });
bindProp("pY", (l) => { l.y = Number($("pY").value) || 0; });
bindProp("pW", (l) => { l.w = Math.max(4, Number($("pW").value) || l.w); });
bindProp("pH", (l) => { l.h = Math.max(4, Number($("pH").value) || l.h); });
bindProp("pRot", (l) => {
  l.rot = Number($("pRot").value);
  $("pRotV").textContent = l.rot + "°";
});
bindProp("pOpa", (l) => {
  l.opacity = Number($("pOpa").value) / 100;
  $("pOpaV").textContent = $("pOpa").value + "%";
});
bindProp("pText", (l) => { l.text = $("pText").value; });
bindProp("pFontSize", (l) => {
  l.fontSize = Number($("pFontSize").value) || 48;
});
bindProp("pColor", (l) => { l.color = $("pColor").value; });

$("bDup").addEventListener("click", () => {
  const l = current();
  if (!l) return;
  addLayer(Object.assign({}, l, { name: l.name + " copy", y: l.y + 24 }));
});

$("bDel").addEventListener("click", () => {
  proj.layers = proj.layers.filter((l) => l.id !== selId);
  selId = null;
  touch();
});

window.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(
        document.activeElement.tagName)) return;
  if ((e.key === "Delete" || e.key === "Backspace") &&
      !current()?.locked) {
    proj.layers = proj.layers.filter((l) => l.id !== selId);
    selId = null;
    touch();
  }
  const nudge = { ArrowLeft: [-1, 0], ArrowRight: [1, 0],
                  ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  if (nudge && current()) {
    current().x += nudge[0] * (e.shiftKey ? 10 : 1);
    current().y += nudge[1] * (e.shiftKey ? 10 : 1);
    touch();
  }
});

/* ---------------------------------------------------------- generate */

async function refreshModels() {
  const r = await api.get("/api/models");
  const sel = $("gModel");
  sel.textContent = "";
  if (!r.ok) {
    const o = document.createElement("option");
    o.textContent = "(engine offline)";
    sel.appendChild(o);
    setEnginePill(false);
    return;
  }
  setEnginePill(true);
  const keys = Object.keys(r.models).filter(
    (k) => r.models[k].kind === "image" && r.models[k].complete);
  const pool = keys.length
    ? keys
    : Object.keys(r.models).filter((k) => r.models[k].kind === "image");
  for (const k of pool) {
    const o = document.createElement("option");
    o.value = k;
    o.textContent = r.models[k].label.split("(")[0].trim() +
                    (r.models[k].complete ? "" : " (pull first)");
    sel.appendChild(o);
  }
}

function setEnginePill(up) {
  const p = $("enginePill");
  p.className = "pill " + (up ? "on" : "err");
  p.textContent = up ? "engine online" : "engine offline";
}

function logGen(html) {
  $("genStatus").innerHTML = html;
}

$("bGenerate").addEventListener("click", async () => {
  if (genBusy) return;
  const prompt = $("gPrompt").value.trim();
  if (!prompt) { logGen("<span style='color:var(--bad)'>prompt?</span>");
                 return; }
  const model = $("gModel").value;
  if (!model || model.includes("offline")) {
    logGen("engine offline or no models pulled yet");
    return;
  }
  const [w, h] = $("gSize").value.split("x").map(Number);
  const seed = $("gRandSeed").checked
    ? Math.floor(Math.random() * 2147483647)
    : Number($("gSeed").value) || 0;
  const body = {
    kind: "txt2img", model, prompt,
    negative: $("gNeg").value.trim(),
    width: w, height: h,
    steps: Number($("gSteps").value) || 20,
    cfg: Number($("gCfg").value) || 7,
    seed,
  };
  genBusy = true;
  logGen("submitting…");
  const sub = await api.post("/api/generate", body);
  if (!sub.ok) {
    logGen(`<span style='color:var(--bad)'>${sub.error}</span>`);
    genBusy = false;
    return;
  }
  const t0 = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, 1600));
    const j = await api.get("/api/job/" + sub.job);
    if (!j.ok) { logGen("lost job"); break; }
    const st = j.job.status;
    if (st === "done") {
      const rel = j.job.files[0].split(/[\\/]/).slice(-3).join("/");
      const src = fileSrc(rel);
      const fit = Math.min(proj.width * 0.7 / w, proj.height * 0.7 / h);
      addLayer({ type: "image", name: "gen " + body.seed, src,
                 w: Math.round(w * fit), h: Math.round(h * fit),
                 x: Math.round((proj.width - w * fit) / 2),
                 y: Math.round((proj.height - h * fit) / 2) });
      logGen(`done in ${Math.round((Date.now() - t0) / 1000)}s`);
      break;
    }
    if (st === "error") {
      logGen(`<span style='color:var(--bad)'>${j.job.error}</span>`);
      break;
    }
    if (st === "cancelled") { logGen("cancelled"); break; }
    logGen(`generating… <b>${st}</b> (${Math.
           round((Date.now() - t0) / 1000)}s)`);
  }
  genBusy = false;
});

/* ------------------------------------------------------- tools & io */

$("bTextLay").addEventListener("click", () =>
  addLayer({ type: "text", text: "double-tap to edit", fontSize: 64,
             color: "#ffffff", name: "headline",
             w: Math.round(proj.width * 0.5), h: 90 }));
$("bRectLay").addEventListener("click", () =>
  addLayer({ type: "rect", name: "shape", color: "#7c5cff" }));
$("bImageLay").addEventListener("click", () => {
  const bar = $("imgImport");
  bar.style.display = bar.style.display === "none" ? "" : "none";
  $("imgPath").focus();
});
$("bImgAdd").addEventListener("click", () => {
  const v = $("imgPath").value.trim();
  if (!v) return;
  const probe = new Image();
  probe.onload = () => {
    const fit = Math.min(proj.width * 0.6 / probe.width,
                         proj.height * 0.6 / probe.height);
    addLayer({ type: "image", name: "import", src: v,
               w: Math.round(probe.width * fit),
               h: Math.round(probe.height * fit) });
    $("imgPath").value = "";
    $("imgImport").style.display = "none";
  };
  probe.onerror = () => window.alert("could not load that image");
  probe.src = v.startsWith("http") || v.includes(":\\")
    ? v : "file:///" + encodeURI(v.replace(/\\/g, "/"));
});

$("bGallery").addEventListener("click", () => api.openWin("gallery"));
$("bModels").addEventListener("click", () => api.openWin("models"));

$("cW").addEventListener("change", () => {
  proj.width = Math.max(64, Number($("cW").value) || proj.width);
  touch();
});
$("cH").addEventListener("change", () => {
  proj.height = Math.max(64, Number($("cH").value) || proj.height);
  touch();
});
$("cBg").addEventListener("input", () => { proj.bg = $("cBg").value;
                                          touch(); });

$("bNew").addEventListener("click", () => {
  if (dirty && !window.confirm("discard unsaved changes?")) return;
  proj = project.emptyProject(proj.width, proj.height);
  selId = null;
  touch();
  dirty = false;
});
$("bSave").addEventListener("click", async () => {
  const r = await api.saveProject({
    name: "untitled.rsproj",
    data: project.serialize(proj),
  });
  if (r.ok) { dirty = false; window.alert("saved:\n" + r.path); }
});
$("bOpen").addEventListener("click", async () => {
  const r = await api.openProject();
  if (!r.ok) return;
  try {
    proj = project.parse(r.data);
    selId = null;
    touch();
    dirty = false;
    $("cW").value = proj.width;
    $("cH").value = proj.height;
  } catch (err) {
    window.alert(String(err.message || err));
  }
});

window.addEventListener("resize", fitStage);

refreshModels();
setInterval(refreshModels, 8000);
render();
