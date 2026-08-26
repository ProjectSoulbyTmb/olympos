"use strict";

const api = window.riley;
const el = document.getElementById("st");

async function tick() {
  const s = await api.get("/api/status");
  if (s.ok) {
    const v = s.comfy && s.comfy.up;
    el.textContent =
      `engine API: ONLINE (${s.version})\n` +
      `comfyui backend: ${v ? "up" : "down - run setup_studio.ps1 -Ai " +
                             "and launch ComfyUI"}\n` +
      `models installed: ${s.installed_models.join(", ") || "none yet"}`;
  } else {
    el.textContent = "engine API: offline - the shell keeps retrying";
  }
}

tick();
setInterval(tick, 4000);
