/**
 * Static server for the built SPA, mirroring deploy/nginx.conf:
 *
 *  - `/api/*` is proxied to the backend (the mock API in tests);
 *  - every other unknown path serves index.html (history fallback).
 *
 * Proxying matters: a production build resolves the API base to the same-origin
 * `/api` prefix, so serving the bundle without that proxy makes every request
 * return index.html and the whole app fails in a way that looks like a UI bug.
 * Doing it here means the E2E suite exercises the real production path.
 */
import { createServer, request as httpRequest } from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";

const ROOT = path.resolve("dist");
const PORT = Number(process.env.PREVIEW_PORT ?? 4173);
const API_PORT = Number(process.env.MOCK_API_PORT ?? 8000);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".json": "application/json",
  ".woff2": "font/woff2",
};

/** Forwards /api/* to the backend, stripping the prefix as nginx does. */
function proxyToApi(req, res, prefix) {
  const upstream = httpRequest(
    {
      host: "127.0.0.1",
      port: API_PORT,
      method: req.method,
      path: req.url.slice(prefix.length) || "/",
      headers: { ...req.headers, host: `127.0.0.1:${API_PORT}` },
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstream.on("error", () => {
    res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ detail: "Backend indisponível no ambiente de teste." }));
  });
  req.pipe(upstream);
}

createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");

  if (url.pathname.startsWith("/api/")) return proxyToApi(req, res, "/api");
  if (url.pathname.startsWith("/consulta-api/")) {
    return proxyToApi(req, res, "/consulta-api");
  }

  let filePath = path.join(ROOT, decodeURIComponent(url.pathname));

  // Refuse to escape the build directory.
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403).end("Forbidden");
    return;
  }

  if (!existsSync(filePath) || !path.extname(filePath)) {
    filePath = path.join(ROOT, "index.html"); // history fallback
  }

  try {
    const body = await readFile(filePath);
    res.writeHead(200, {
      "content-type": TYPES[path.extname(filePath)] ?? "application/octet-stream",
      "cache-control": "no-store",
    });
    res.end(body);
  } catch {
    res.writeHead(404).end("Not found");
  }
}).listen(PORT, () => console.log(`dist served on http://localhost:${PORT}`));
