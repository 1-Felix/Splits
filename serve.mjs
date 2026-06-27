// Minimal zero-dependency static file server for the SPLITS dashboard.
//
//   pnpm dev            → serves this folder on http://localhost:8000
//   PORT=3000 pnpm dev  → pick a different port
//
// Why not `python -m http.server`? Same idea, but this keeps the toolchain on
// Node/pnpm and adds: "/" redirects straight to the dashboard, correct MIME
// types for ES-module imports, and no-cache headers so edits to running-data.js
// show up on reload.

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)));
const PORT = Number(process.env.PORT) || 8000;
const ENTRY = "/Running%20Dashboard.dc.html";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".py": "text/plain; charset=utf-8",
};

const server = createServer(async (req, res) => {
  try {
    let pathname = decodeURIComponent(new URL(req.url, `http://${req.headers.host}`).pathname);
    if (pathname === "/") {
      res.writeHead(302, { Location: ENTRY });
      res.end();
      return;
    }

    // Resolve inside ROOT only — block path traversal.
    const filePath = normalize(join(ROOT, pathname));
    if (!filePath.startsWith(ROOT)) {
      res.writeHead(403).end("Forbidden");
      return;
    }

    const info = await stat(filePath).catch(() => null);
    if (!info || !info.isFile()) {
      res.writeHead(404, { "Content-Type": "text/plain" }).end(`404 — ${pathname} not found`);
      return;
    }

    const body = await readFile(filePath);
    res.writeHead(200, {
      "Content-Type": MIME[extname(filePath).toLowerCase()] || "application/octet-stream",
      "Cache-Control": "no-cache, no-store, must-revalidate",
    });
    res.end(body);
  } catch (err) {
    res.writeHead(500, { "Content-Type": "text/plain" }).end(`500 — ${err.message}`);
  }
});

server.listen(PORT, () => {
  console.log(`SPLITS dashboard → http://localhost:${PORT}${ENTRY}`);
});
