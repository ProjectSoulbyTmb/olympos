"use strict";

// project - .rsproj serialization contract (shared by renderer & tests).
//
// A project is one JSON file:
//   { version, width, height, bg, fps,
//     layers: [{ id, name, type: image|text|rect, x, y, w, h, rot,
//                opacity, visible, locked, src?, text?, fontSize?,
//                color? }] }
//
// Coordinates are project-space pixels; y grows downward; rot degrees.

const SCHEMA_VERSION = 1;

function emptyProject(width = 1600, height = 1000) {
  return {
    version: SCHEMA_VERSION,
    width,
    height,
    bg: "#14121c",
    fps: 30,
    layers: [],
  };
}

function isNum(n) { return typeof n === "number" && Number.isFinite(n); }

function normalizeLayer(raw, i) {
  const type = raw.type;
  if (!["image", "text", "rect"].includes(type)) {
    throw new Error(`layer ${i}: bad type ${JSON.stringify(type)}`);
  }
  if (type === "image" && typeof raw.src !== "string") {
    throw new Error(`layer ${i}: image needs src`);
  }
  if (type === "text" && typeof raw.text !== "string") {
    throw new Error(`layer ${i}: text layer needs text`);
  }
  return {
    id: typeof raw.id === "string" && raw.id ? raw.id : `L${i}-${Date.now()}`,
    name: String(raw.name || `${type} ${i + 1}`).slice(0, 80),
    type,
    x: isNum(raw.x) ? raw.x : 0,
    y: isNum(raw.y) ? raw.y : 0,
    w: isNum(raw.w) ? Math.max(1, raw.w) : type === "text" ? 200 : 100,
    h: isNum(raw.h) ? Math.max(1, raw.h) : type === "text" ? 48 : 100,
    rot: isNum(raw.rot) ? ((raw.rot % 360) + 360) % 360 : 0,
    opacity: isNum(raw.opacity) ? Math.min(1, Math.max(0, raw.opacity)) : 1,
    visible: raw.visible !== false,
    locked: raw.locked === true,
    src: typeof raw.src === "string" ? raw.src : undefined,
    text: typeof raw.text === "string" ? raw.text : undefined,
    fontSize: isNum(raw.fontSize) ? raw.fontSize : undefined,
    color: typeof raw.color === "string" ? raw.color : undefined,
  };
}

function validateProject(p) {
  if (!p || typeof p !== "object" || Array.isArray(p)) {
    throw new Error("project must be an object");
  }
  // hostile/out-of-spec sizes are clamped, not rejected - a saved file
  // should always open
  const clamp = (n, lo, hi, dflt) =>
    isNum(n) ? Math.round(Math.min(hi, Math.max(lo, n))) : dflt;
  const width = clamp(p.width, 16, 8192, 1600);
  const height = clamp(p.height, 16, 8192, 1000);
  if (!Array.isArray(p.layers)) throw new Error("layers must be an array");
  return {
    version: SCHEMA_VERSION,
    width,
    height,
    bg: typeof p.bg === "string" ? p.bg : "#14121c",
    fps: clamp(p.fps, 1, 60, 30),
    layers: p.layers.map(normalizeLayer),
  };
}

function serialize(project) {
  return JSON.stringify(validateProject(project), null, 2);
}

function parse(text) {
  let raw;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    throw new Error("not valid JSON: " + e.message);
  }
  return validateProject(raw);
}

module.exports = { SCHEMA_VERSION, emptyProject, validateProject,
                   serialize, parse };
