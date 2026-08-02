// tools/make-icons.mjs — generates the PWA icons under vendor/icons/.
//
//   node tools/make-icons.mjs
//
// The icons are committed (they are application assets, like the vendored
// fonts); this script is their provenance. It draws the same mark the topbar
// draws in CSS — three skewed bars on the volt accent — with a hand-rolled PNG
// encoder, so the repo stays dependency-free.
//
// MASKABLE: Android crops an installed icon to whatever shape the launcher
// uses, keeping only the central 80% circle. The mark is therefore drawn at
// 52% of the canvas on a full-bleed background, so no crop can clip it.

import { deflateSync } from "node:zlib";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const OUT = fileURLToPath(new URL("../vendor/icons/", import.meta.url));

const BG = [0xC7, 0xF6, 0x46];   // volt --accent
const INK = [0x0E, 0x0F, 0x12];  // volt --bg

// ── a minimal PNG encoder (RGBA, filter 0) ─────────────────────────────────
const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();
function crc32(buf) {
  let c = -1;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}
function png(width, height, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;    // bit depth
  ihdr[9] = 6;    // colour type: RGBA
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 4 + 1)] = 0;  // filter: none
    rgba.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// ── the mark ───────────────────────────────────────────────────────────────
// Three bars, each 14×3 within a 34-unit tile, stacked 6 units apart and
// skewed −22°: skewX maps (x, y) → (x + y·tan a, y), so testing membership
// means un-skewing the sample first. Sampled 3×3 per pixel for smooth edges.
const TAN = Math.tan((-22 * Math.PI) / 180);

function draw(size, markFrac) {
  const px = Buffer.alloc(size * size * 4);
  const unit = (size * markFrac) / 34;      // one logo unit in pixels
  const halfW = (14 / 2) * unit;
  const halfH = (3 / 2) * unit;
  const gap = 6 * unit;
  const c = size / 2;
  const inBar = (x, y) => {
    const dy = y - c;
    const xu = x - c - dy * TAN;            // un-skew
    if (Math.abs(xu) > halfW) return false;
    for (const cy of [-gap, 0, gap]) if (Math.abs(dy - cy) <= halfH) return true;
    return false;
  };
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let hits = 0;
      for (let sy = 0; sy < 3; sy++) {
        for (let sx = 0; sx < 3; sx++) {
          if (inBar(x + (sx + 0.5) / 3, y + (sy + 0.5) / 3)) hits++;
        }
      }
      const a = hits / 9;
      const i = (y * size + x) * 4;
      for (let ch = 0; ch < 3; ch++) px[i + ch] = Math.round(BG[ch] * (1 - a) + INK[ch] * a);
      px[i + 3] = 255;
    }
  }
  return png(size, size, px);
}

await mkdir(OUT, { recursive: true });
// 192/512 are maskable (mark at 52% — inside the 80% safe circle); the Apple
// touch icon is never masked, so its mark can breathe at 68%.
for (const [name, size, frac] of [
  ["icon-192.png", 192, 0.52],
  ["icon-512.png", 512, 0.52],
  ["apple-touch-180.png", 180, 0.68],
]) {
  await writeFile(OUT + name, draw(size, frac));
  console.log("wrote", OUT + name);
}
