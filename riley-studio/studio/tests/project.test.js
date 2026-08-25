"use strict";

const test = require("node:test");
const assert = require("node:assert");
const path = require("path");
const project = require(path.join(__dirname, "..", "lib", "project.js"));

test("empty project has sane defaults", () => {
  const p = project.emptyProject();
  assert.equal(p.version, 1);
  assert.equal(p.width, 1600);
  assert.deepEqual(p.layers, []);
});

test("serialize -> parse round-trips layers", () => {
  const p = project.emptyProject(800, 600);
  p.layers.push({
    id: "a1", name: "hero", type: "image", x: 10, y: 20, w: 300, h: 150,
    rot: 15, opacity: 0.9, src: "http://127.0.0.1/x.png",
  });
  p.layers.push({
    type: "text", text: "hello", x: 5, y: 5, fontSize: 42, color: "#fff",
  });
  const back = project.parse(project.serialize(p));
  assert.equal(back.width, 800);
  assert.equal(back.layers.length, 2);
  assert.equal(back.layers[0].rot, 15);
  assert.equal(back.layers[1].fontSize, 42);
  assert.equal(back.layers[1].type, "text");
});

test("parse rejects garbage and bad shapes", () => {
  assert.throws(() => project.parse("{nope"), /JSON/);
  // sizes clamp now, but a missing layer list is still fatal
  assert.throws(() => project.parse("{}"), /layers/);
  assert.throws(() =>
    project.parse(JSON.stringify({ width: 400, height: 400,
                                   layers: [{ type: "wat" }] })), /bad type/);
  assert.throws(() =>
    project.parse(JSON.stringify({ width: 400, height: 400,
                                   layers: [{ type: "image" }] })), /src/);
  // video layers are first-class and carry an optional clip duration
  const ok = project.parse(JSON.stringify({
    width: 400, height: 400,
    layers: [{ type: "video", src: "http://127.0.0.1/x.webm",
               dur: 99 }] }));
  assert.equal(ok.layers[0].dur, 30); // clamped
});

test("normalize clamps hostile values instead of throwing", () => {
  const p = JSON.stringify({
    width: 99999, height: 400, fps: 999,
    layers: [{ type: "rect", x: "x", opacity: 7, rot: 370 }],
  });
  const out = project.parse(p);
  assert.equal(out.width, 8192);
  assert.equal(out.fps, 60);
  const l = out.layers[0];
  assert.equal(l.x, 0);
  assert.equal(l.opacity, 1);
  assert.equal(l.rot, 10);
});
