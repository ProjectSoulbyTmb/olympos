"use strict";

const api = window.riley;
const $ = (id) => document.getElementById(id);

async function load() {
  const g = await api.get("/api/gallery");
  const grid = $("grid");
  grid.textContent = "";
  if (!g.ok) {
    $("note").textContent = "engine offline - start it and reopen";
    return;
  }
  $("note").textContent = g.items.length
    ? `${g.items.length} item(s), newest first`
    : "nothing generated yet - make something in the Studio";
  for (const it of g.items) {
    const card = document.createElement("div");
    card.className = "card";
    const src = await api.fileUrl(it.path);
    let media;
    if (it.kind === "image") {
      media = document.createElement("img");
      media.src = src;
    } else {
      media = document.createElement("video");
      media.src = src;
      media.muted = true;
      media.loop = true;
      media.play();
    }
    const meta = document.createElement("div");
    meta.className = "meta";
    const name = document.createElement("b");
    name.textContent = it.name;
    const size = document.createElement("span");
    size.textContent = (it.bytes / 1048576).toFixed(1) + " MB";
    meta.append(name, size);
    card.append(media, meta);
    card.title = `${it.job}/${it.name}`;
    grid.appendChild(card);
  }
}

load();
