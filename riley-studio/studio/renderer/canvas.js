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
  } else if (l.type === "video" && l.src) {
    const v = document.createElement("video");
    v.src = fileSrc(l.src);
    v.muted = true;
    v.loop = true;
    v.autoplay = true;
    v.play().catch(() => {});
    d.appendChild(v);
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
  renderTimeline();
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
  if (!l.dur && (l.type === "image" || l.type === "video")) l.dur = 2.5;
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
  const media = l && (l.type === "image" || l.type === "video") && l.src;
  $("bUpscale").style.display =
    media && l.type === "image" ? "" : "none";
  $("bAnimate").style.display = media ? "" : "none";
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
  const wantKind = $("gKind").value === "video" ? "video" : "image";
  if (!r.ok) {
    const o = document.createElement("option");
    o.textContent = "(engine offline)";
    sel.appendChild(o);
    setEnginePill(false);
    return;
  }
  setEnginePill(true);
  const pool = Object.keys(r.models).filter(
    (k) => r.models[k].kind === wantKind);
  if (!pool.length) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = `no ${wantKind} models in manifest`;
    sel.appendChild(o);
    return;
  }
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

$("gKind").addEventListener("change", () => {
  const vid = $("gKind").value === "video";
  $("gLenRow").style.display = vid ? "" : "none";
  const sizes = vid
    ? [["480x480", "480 x 480"], ["768x512", "768 x 512"],
       ["512x768", "512 x 768"]]
    : [["512x512", "512 x 512 square"], ["512x768", "512 x 768 portrait"],
       ["768x512", "768 x 512 landscape"], ["768x768", "768 x 768 square"],
       ["1024x1024", "1024 x 1024 large"]];
  const sel = $("gSize");
  sel.textContent = "";
  for (const [v, label] of sizes) {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = label;
    sel.appendChild(o);
  }
  refreshModels();
});

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
  const isVideo = $("gKind").value === "video";
  const body = {
    kind: isVideo ? "txt2vid" : "txt2img",
    model, prompt,
    negative: $("gNeg").value.trim(),
    width: w, height: h,
    seed,
  };
  if (isVideo) {
    body.length = Number($("gLen").value) || 97;
    body.steps = 8;
    body.cfg = 3.0;
  } else {
    body.steps = Number($("gSteps").value) || 20;
    body.cfg = Number($("gCfg").value) || 7;
  }
  genBusy = true;
  logGen("submitting…");
  const sub = await api.post("/api/generate", body);
  if (!sub.ok) {
    logGen(`<span style='color:var(--bad)'>${sub.error}</span>`);
    genBusy = false;
    return;
  }
  const job = await pollJob(sub.job, "generating");
  if (job && job.files[0]) {
    const rel = job.files[0].split(/[\\/]/).slice(-3).join("/");
    const src = fileSrc(rel);
    if (isVideo) {
      addLayer({ type: "video", name: "clip " + body.seed, src,
                 w: Math.round(proj.width * 0.5),
                 h: Math.round(proj.width * 0.5 * h / w),
                 x: Math.round(proj.width * 0.25),
                 y: Math.round(proj.height * 0.2),
                 dur: Math.round((body.length || 97) / 24 * 10) / 10 });
    } else {
      const fit = Math.min(proj.width * 0.7 / w,
                           proj.height * 0.7 / h);
      addLayer({ type: "image", name: "gen " + body.seed, src,
                 w: Math.round(w * fit), h: Math.round(h * fit),
                 x: Math.round((proj.width - w * fit) / 2),
                 y: Math.round((proj.height - h * fit) / 2) });
    }
  }
  genBusy = false;
});

/* ---------------------------------------------------------- timeline */

function mediaLayers() {
  return proj.layers.filter(
    (l) => (l.type === "image" || l.type === "video") && l.visible);
}

function renderTimeline() {
  const box = $("tlClips");
  if (!box) return;
  box.textContent = "";
  let total = 0;
  const clips = mediaLayers();
  if (!clips.length) {
    $("tlTotal").textContent = "add generated images / clips";
    return;
  }
  for (const l of clips) {
    total += l.type === "video"
      ? (l.dur || 4)
      : (l.dur || 2.5);
    const c = document.createElement("div");
    c.className = "clip" + (l.id === selId ? " sel" : "");
    let thumb;
    if (l.type === "video") {
      thumb = document.createElement("video");
      thumb.src = fileSrc(l.src);
      thumb.muted = true;
    } else {
      thumb = document.createElement("img");
      thumb.src = fileSrc(l.src);
    }
    const row = document.createElement("div");
    row.className = "cdur";
    if (l.type === "image") {
      const inp = document.createElement("input");
      inp.type = "number";
      inp.step = "0.5";
      inp.min = "0.5";
      inp.value = l.dur || 2.5;
      inp.addEventListener("change", () => {
        l.dur = Math.max(0.3, Number(inp.value) || 2.5);
        touch();
      });
      const s = document.createElement("span");
      s.textContent = "s";
      row.append(inp, s);
    } else {
      row.textContent = `clip ${(l.dur || 4).toFixed(1)}s`;
    }
    c.append(thumb, row);
    c.onclick = () => select(l.id);
    box.appendChild(c);
  }
  $("tlTotal").textContent =
    `${clips.length} clip(s) · ~${total.toFixed(1)}s`;
}

/* ----------------------------------------------------------- exports */

async function saveStill(mime, ext) {
  const off = document.createElement("canvas");
  off.width = proj.width;
  off.height = proj.height;
  const ctx = off.getContext("2d");
  ctx.fillStyle = proj.bg;
  ctx.fillRect(0, 0, off.width, off.height);
  for (const l of proj.layers) {
    if (!l.visible) continue;
    ctx.save();
    ctx.globalAlpha = l.opacity;
    ctx.translate(l.x + l.w / 2, l.y + l.h / 2);
    if (l.rot) ctx.rotate(l.rot * Math.PI / 180);
    try {
      if ((l.type === "image" || l.type === "video") && l.src) {
        const m = new Image();
        m.src = l.src.startsWith("http") ? l.src : fileSrc(l.src);
        await m.decode();
        ctx.drawImage(m, -l.w / 2, -l.h / 2, l.w, l.h);
      } else if (l.type === "text") {
        ctx.fillStyle = l.color || "#fff";
        ctx.font = `700 ${l.fontSize || 48}px 'Segoe UI', sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        (l.text || "").split("\n").forEach((line, i, arr) => {
          const dy = (i - (arr.length - 1) / 2) *
                     (l.fontSize || 48) * 1.25;
          ctx.fillText(line, 0, dy, l.w);
        });
      } else {
        ctx.fillStyle = l.color || "#7c5cff";
        ctx.beginPath();
        const r = 10;
        ctx.roundRect(-l.w / 2, -l.h / 2, l.w, l.h, r);
        ctx.fill();
      }
    } catch (_) { /* skip unrenderable layer */ }
    ctx.restore();
  }
  const r = await api.saveDataUrl({
    name: "export." + ext,
    dataUrl: off.toDataURL(mime, 0.92),
  });
  logGen(r.ok ? `saved ${ext.toUpperCase()}:\n${r.path}`
              : (r.error || "save cancelled"));
}

async function pollJob(jobId, label) {
  const t0 = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, 1600));
    const j = await api.get("/api/job/" + jobId);
    if (!j.ok) { logGen("lost job"); return null; }
    const st = j.job.status;
    if (st === "done") {
      logGen(`${label} done in ${Math.round((Date.now() - t0) / 1000)}s`);
      return j.job;
    }
    if (st === "error") {
      logGen(`<span style='color:var(--bad)'>${j.job.error}</span>`);
      return null;
    }
    if (st === "cancelled") { logGen("cancelled"); return null; }
    logGen(`${label}… <b>${st}</b> ` +
           `(${Math.round((Date.now() - t0) / 1000)}s)`);
  }
}

async function exportReel(kind) {
  const files = [];
  for (const l of mediaLayers()) {
    if (l.type !== "image") continue;
    // engine-generated layers carry src via /api/file?p=outputs/<id>/<f>
    const q = l.src.split("/api/file?p=")[1];
    if (!q) { logGen("reel needs engine-generated images only"); return; }
    files.push(decodeURIComponent(q));
  }
  if (files.length < 2) {
    logGen("need >=2 visible image layers for a reel");
    return;
  }
  const steps = [{
    type: "slideshow", images: files, output: "reel.mp4",
    per_image: 2.5, crossfade: 0.5,
    size: `${_even(proj.width)}x${_even(proj.height)}`, fps: 30,
  }];
  if (kind === "export_gif") {
    steps.push({ type: "gif", input: "reel.mp4", output: "reel.gif",
                 fps: 12, width: Math.min(480, proj.width) });
  }
  const sub = await api.post("/api/generate", { kind, steps });
  if (!sub.ok) { logGen(sub.error || "export refused"); return; }
  const job = await pollJob(sub.job, "exporting");
  if (job && job.files[0]) {
    window.open(await api.fileUrl(
      job.files[0].split(/[\\/]/).slice(-3).join("/")), "_blank");
  }
}

function _even(n) { return Math.max(16, Math.round(n / 2) * 2); }

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
$("bExpPng").addEventListener("click", () => saveStill("image/png",
                                                       "png"));
$("bExpJpg").addEventListener("click", () =>
  saveStill("image/jpeg", "jpg"));
$("bExpMp4").addEventListener("click", () => exportReel("export_mp4"));
$("bExpGif").addEventListener("click", () => exportReel("export_gif"));

/* --------------------------------------------------------- extras */

$("cPreset").addEventListener("change", () => {
  const v = $("cPreset").value;
  if (!v) return;
  const [w, h] = v.split("x").map(Number);
  proj.width = w;
  proj.height = h;
  $("cW").value = w;
  $("cH").value = h;
  touch();
});

function relPathOf(l) {
  const q = (l.src || "").split("/api/file?p=")[1];
  return q ? decodeURIComponent(q) : null;
}

$("bUpscale").addEventListener("click", async () => {
  const l = current();
  if (!l || l.type !== "image" || genBusy) return;
  const rel = relPathOf(l);
  if (!rel) { logGen("upscale needs an engine-generated image"); return; }
  genBusy = true;
  logGen("upscaling…");
  const sub = await api.post("/api/generate",
                             { kind: "upscale", image: rel,
                               scale_by: 2 });
  if (!sub.ok) { logGen(sub.error || "refused"); genBusy = false; return; }
  const job = await pollJob(sub.job, "upscaling");
  if (job && job.files[0]) {
    addLayer({ type: "image", name: l.name + " ×2",
               src: fileSrc(job.files[0].split(/[\\/]/).
                            slice(-3).join("/")),
               w: Math.round(l.w * 2), h: Math.round(l.h * 2),
               x: Math.max(0, l.x - Math.round(l.w / 2)),
               y: Math.max(0, l.y - Math.round(l.h / 2)) });
  }
  genBusy = false;
});

$("bAnimate").addEventListener("click", async () => {
  const l = current();
  if (!l || genBusy) return;
  const rel = relPathOf(l);
  if (!rel) { logGen("animate needs an engine-generated image"); return; }
  const prompt = $("gPrompt").value.trim() ||
                 ("gentle cinematic motion, breathing camera");
  // LTX likes modest resolutions on small GPUs
  const ar = l.w / l.h;
  let w = 480;
  let h = Math.round(480 / ar / 8) * 8;
  h = Math.min(Math.max(h, 256), 768);
  genBusy = true;
  logGen("animating…");
  const sub = await api.post("/api/generate", {
    kind: "img2vid", model: "ltxv-distilled-q3",
    image: rel, prompt, width: _even(w), height: _even(h),
    length: Number($("gLen").value) || 97, seed:
      Math.floor(Math.random() * 2147483647),
  });
  if (!sub.ok) { logGen(sub.error || "refused"); genBusy = false; return; }
  const job = await pollJob(sub.job, "animating");
  if (job && job.files[0]) {
    const w2 = Math.min(proj.width - 40, l.w);
    addLayer({ type: "video",
               name: "motion of " + l.name,
               src: fileSrc(job.files[0].split(/[\\/]/).
                            slice(-3).join("/")),
               w: Math.round(w2),
               h: Math.round(w2 * h / w),
               x: l.x, y: l.y,
               dur: Math.round(((Number($("gLen").value) || 97) /
                                24) * 10) / 10 });
  }
  genBusy = false;
});

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
