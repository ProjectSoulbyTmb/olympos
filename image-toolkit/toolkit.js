#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]);

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--apply") args.apply = true;
    else if (a === "-r" || a === "--recursive") args.recursive = true;
    else if (a === "--pattern") args.pattern = argv[++i];
    else if (a === "--start") args.start = parseInt(argv[++i], 10);
    else if (a === "--by-ext") args.byExt = true;
    else if (a === "--delete") args.delete = true;
    else if (a === "--help" || a === "-h") args.help = true;
    else args._.push(a);
  }
  return args;
}

function walk(dir, recursive) {
  const out = [];
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (e) {
    console.error(`Cannot read folder: ${dir} (${e.message})`);
    process.exitCode = 1;
    return out;
  }
  for (const ent of entries) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      if (recursive) out.push(...walk(full, true));
      continue;
    }
    if (!ent.isFile()) continue;
    if (IMAGE_EXTS.has(path.extname(ent.name).toLowerCase())) out.push(full);
  }
  return out;
}

function fmtBytes(n) {
  if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB";
  if (n >= 1048576) return (n / 1048576).toFixed(2) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}

function hashFile(file) {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash("sha256");
    const s = fs.createReadStream(file);
    s.on("data", (d) => h.update(d));
    s.on("error", reject);
    s.on("end", () => resolve(h.digest("hex")));
  });
}

function readHeader(file, len) {
  const fd = fs.openSync(file, "r");
  try {
    const buf = Buffer.alloc(len);
    const got = fs.readSync(fd, buf, 0, len, 0);
    return buf.subarray(0, got);
  } finally {
    fs.closeSync(fd);
  }
}

function pngSize(b) {
  if (b.length < 24 || b.readUInt32BE(0) !== 0x89504e47) return null;
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}

function gifSize(b) {
  if (b.length < 10 || b.toString("ascii", 0, 3) !== "GIF") return null;
  return { w: b.readUInt16LE(6), h: b.readUInt16LE(8) };
}

function bmpSize(b) {
  if (b.length < 26 || b[0] !== 0x42 || b[1] !== 0x4d) return null;
  return { w: b.readInt32LE(18), h: Math.abs(b.readInt32LE(22)) };
}

function jpegSize(b) {
  if (b.length < 4 || b[0] !== 0xff || b[1] !== 0xd8) return null;
  let off = 2;
  while (off + 4 <= b.length) {
    if (b[off] !== 0xff) { off++; continue; }
    const marker = b[off + 1];
    if (marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7)) { off += 2; continue; }
    if (off + 9 > b.length) break;
    const segLen = b.readUInt16BE(off + 2);
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return { w: b.readUInt16BE(off + 7), h: b.readUInt16BE(off + 5) };
    }
    off += 2 + segLen;
  }
  return null;
}

function webpSize(file) {
  const b = readHeader(file, 64);
  if (b.length < 20 || b.toString("ascii", 0, 4) !== "RIFF" || b.toString("ascii", 8, 12) !== "WEBP") return null;
  const fourcc = b.toString("ascii", 12, 16);
  const chunkSize = b.readUInt32LE(16);
  const avail = Math.min(b.length - 20, chunkSize);
  if (fourcc === "VP8 ") {
    if (avail < 10) return null;
    return { w: b.readUInt16LE(26) & 0x3fff, h: b.readUInt16LE(28) & 0x3fff };
  }
  if (fourcc === "VP8L") {
    if (avail < 5) return null;
    const bits = b.readUInt32LE(21);
    return { w: (bits & 0x3fff) + 1, h: ((bits >> 14) & 0x3fff) + 1 };
  }
  if (fourcc === "VP8X") {
    if (avail < 10) return null;
    const w = (b[24] | (b[25] << 8) | (b[26] << 16)) + 1;
    const h = (b[27] | (b[28] << 8) | (b[29] << 16)) + 1;
    return { w, h };
  }
  return null;
}

function imageSize(file) {
  try {
    const ext = path.extname(file).toLowerCase();
    if (ext === ".png") return pngSize(readHeader(file, 24));
    if (ext === ".gif") return gifSize(readHeader(file, 10));
    if (ext === ".bmp") return bmpSize(readHeader(file, 26));
    if (ext === ".webp") return webpSize(file);
    if (ext === ".jpg" || ext === ".jpeg") return jpegSize(readHeader(file, 256 * 1024));
  } catch (_) {}
  return null;
}

async function cmdStats(folder, args) {
  const files = walk(folder, !!args.recursive);
  if (files.length === 0) { console.log("No images found."); return; }
  const byExt = new Map();
  const resCount = new Map();
  const sized = [];
  let totalBytes = 0;
  let parsedDims = 0;
  for (const f of files) {
    const ext = path.extname(f).toLowerCase();
    byExt.set(ext, (byExt.get(ext) || 0) + 1);
    let size = 0;
    try { size = fs.statSync(f).size; } catch (_) {}
    totalBytes += size;
    sized.push({ f, size });
    const d = imageSize(f);
    if (d && d.w > 0 && d.h > 0) {
      parsedDims++;
      const key = `${d.w}x${d.h}`;
      resCount.set(key, (resCount.get(key) || 0) + 1);
    }
  }
  console.log(`Folder: ${folder}`);
  console.log(`Images: ${files.length} | Total: ${fmtBytes(totalBytes)} | Dimensions readable: ${parsedDims}/${files.length}`);
  console.log("");
  console.log("By type:");
  for (const [ext, n] of [...byExt.entries()].sort((a, b) => b[1] - a[1])) {
    console.log(`  ${ext.padEnd(7)} ${n}`);
  }
  const topRes = [...resCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10);
  if (topRes.length) {
    console.log("");
    console.log("Top resolutions:");
    for (const [r, n] of topRes) console.log(`  ${r.padEnd(14)} ${n}`);
  }
  sized.sort((a, b) => b.size - a.size);
  console.log("");
  console.log("Largest files:");
  for (const s of sized.slice(0, 10)) {
    console.log(`  ${fmtBytes(s.size).padStart(9)}  ${s.f}`);
  }
}

async function cmdDuplicates(folder, args) {
  const files = walk(folder, !!args.recursive);
  if (files.length === 0) { console.log("No images found."); return; }
  const bySize = new Map();
  for (const f of files) {
    let size = 0;
    try { size = fs.statSync(f).size; } catch (_) { continue; }
    if (!bySize.has(size)) bySize.set(size, []);
    bySize.get(size).push(f);
  }
  const candidates = [];
  for (const group of bySize.values()) if (group.length > 1) candidates.push(...group);
  const byHash = new Map();
  for (const f of candidates) {
    try {
      const h = await hashFile(f);
      if (!byHash.has(h)) byHash.set(h, []);
      byHash.get(h).push(f);
    } catch (e) {
      console.error(`Hash failed: ${f} (${e.message})`);
    }
  }
  const groups = [...byHash.values()].filter((g) => g.length > 1);
  if (groups.length === 0) { console.log("No duplicates found."); return; }
  let wasted = 0;
  groups.forEach((g, i) => {
    const size = fs.statSync(g[0]).size;
    wasted += size * (g.length - 1);
    console.log(`Group ${i + 1} (${g.length} copies, ${fmtBytes(size)} each):`);
    g.forEach((f, j) => {
      console.log(`  ${j === 0 ? "[keep] " : "        "}${f}`);
    });
  });
  console.log("");
  console.log(`${groups.length} duplicate group(s); ${fmtBytes(wasted)} reclaimable.`);
  if (args.delete) {
    let removed = 0;
    let freed = 0;
    for (const g of groups) {
      for (let j = 1; j < g.length; j++) {
        try {
          const sz = fs.statSync(g[j]).size;
          fs.unlinkSync(g[j]);
          removed++;
          freed += sz;
          console.log(`Deleted: ${g[j]}`);
        } catch (e) {
          console.error(`Failed to delete ${g[j]}: ${e.message}`);
        }
      }
    }
    console.log(`Removed ${removed} file(s), freed ${fmtBytes(freed)}.`);
  } else {
    console.log("(dry run - pass --delete to remove extra copies)");
  }
}

function uniqueTarget(dir, base, ext) {
  let candidate = path.join(dir, base + ext);
  let i = 1;
  while (fs.existsSync(candidate)) {
    candidate = path.join(dir, `${base}_${i}${ext}`);
    i++;
  }
  return candidate;
}

async function cmdRename(folder, args) {
  const pattern = args.pattern || "img_{n}";
  const start = Number.isFinite(args.start) ? args.start : 1;
  const files = walk(folder, false).sort();
  if (files.length === 0) { console.log("No images found."); return; }
  const now = new Date();
  const tokens = {
    Y: String(now.getFullYear()),
    m: String(now.getMonth() + 1).padStart(2, "0"),
    d: String(now.getDate()).padStart(2, "0"),
  };
  const plans = [];
  let n = start;
  for (const f of files) {
    const ext = path.extname(f).toLowerCase();
    let name = pattern.replace(/\{n\}/g, () => String(n)).replace(/\{([Ymd])\}/g, (_, t) => tokens[t]);
    name = name.replace(/[<>:"/\\|?*]/g, "_");
    const target = path.join(path.dirname(f), name + ext);
    if (target !== f) plans.push({ from: f, to: target });
    n++;
  }
  if (plans.length === 0) { console.log("Nothing to rename."); return; }
  for (const p of plans) console.log(`${path.basename(p.from)}  ->  ${path.basename(p.to)}`);
  if (!args.apply) {
    console.log(`(dry run - ${plans.length} rename(s) planned; pass --apply to execute)`);
    return;
  }
  let done = 0;
  for (const p of plans) {
    try {
      const finalTarget = fs.existsSync(p.to)
        ? uniqueTarget(path.dirname(p.to), path.basename(p.to, path.extname(p.to)), path.extname(p.to))
        : p.to;
      fs.renameSync(p.from, finalTarget);
      done++;
    } catch (e) {
      console.error(`Failed: ${p.from} -> ${p.to}: ${e.message}`);
    }
  }
  console.log(`Renamed ${done}/${plans.length} file(s).`);
}

function pad(n) { return String(n).padStart(2, "0"); }

async function cmdOrganize(folder, args) {
  const files = walk(folder, !!args.recursive);
  if (files.length === 0) { console.log("No images found."); return; }
  const plans = [];
  for (const f of files) {
    if (path.dirname(f) !== folder && !args.recursive) continue;
    let destDirName;
    if (args.byExt) {
      destDirName = path.extname(f).toLowerCase().replace(".", "") || "other";
    } else {
      let mtime;
      try { mtime = fs.statSync(f).mtime; } catch (_) { continue; }
      destDirName = `${mtime.getFullYear()}-${pad(mtime.getMonth() + 1)}`;
    }
    const destDir = path.join(folder, destDirName);
    const target = path.join(destDir, path.basename(f));
    if (target !== f) plans.push({ from: f, destDir, to: target });
  }
  if (plans.length === 0) { console.log("Nothing to move."); return; }
  for (const p of plans) console.log(`${path.basename(p.from)}  ->  ${path.relative(folder, p.destDir)}\\`);
  if (!args.apply) {
    console.log(`(dry run - ${plans.length} move(s) planned; pass --apply to execute)`);
    return;
  }
  let done = 0;
  for (const p of plans) {
    try {
      fs.mkdirSync(p.destDir, { recursive: true });
      const finalTarget = fs.existsSync(p.to)
        ? uniqueTarget(p.destDir, path.basename(p.to, path.extname(p.to)), path.extname(p.to))
        : p.to;
      fs.renameSync(p.from, finalTarget);
      done++;
    } catch (e) {
      console.error(`Failed to move ${p.from}: ${e.message}`);
    }
  }
  console.log(`Moved ${done}/${plans.length} file(s).`);
}

function help() {
  console.log(`
image-toolkit - zero-dependency image folder utility

Usage:
  node toolkit.js stats <folder> [-r]
      Summarize a folder: counts by type, total size, resolutions, largest files.
  node toolkit.js duplicates <folder> [-r] [--delete]
      Find exact duplicate images. Dry run by default; --delete removes extra
      copies (keeps the first file of each group).
  node toolkit.js rename <folder> --pattern "photo_{n}" [--start N] [--apply]
      Bulk rename images in a folder (top level only). Tokens: {n} sequence,
      {Y}/{m}/{d} date. Dry run unless --apply.
  node toolkit.js organize <folder> [-r] [--by-ext] [--apply]
      Move images into year-month subfolders (or type subfolders with
      --by-ext), based on file modification time. Dry run unless --apply.

Flags:
  -r, --recursive   include subfolders (stats/duplicates/organize)
  --apply           execute changes (rename/organize default to dry run)
  --delete          delete duplicates instead of just listing them
`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const [cmd, folder] = args._;
  if (args.help || !cmd) { help(); return; }
  if (!folder) { console.error("Error: missing <folder> argument.\n"); help(); process.exitCode = 1; return; }
  if (!fs.existsSync(folder) || !fs.statSync(folder).isDirectory()) {
    console.error(`Error: not a folder: ${folder}`);
    process.exitCode = 1;
    return;
  }
  switch (cmd) {
    case "stats": await cmdStats(folder, args); break;
    case "duplicates": await cmdDuplicates(folder, args); break;
    case "rename": await cmdRename(folder, args); break;
    case "organize": await cmdOrganize(folder, args); break;
    default:
      console.error(`Unknown command: ${cmd}\n`);
      help();
      process.exitCode = 1;
  }
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});




