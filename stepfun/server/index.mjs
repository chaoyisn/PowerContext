import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { extname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadEnv } from "./env.mjs";

loadEnv();
const { createKnowledgeBase, findDuplicateDocuments, getDocument, health, importDocument, initializeDatabase, listDocuments, listKnowledgeBases, search, HttpError } = await import("./db.mjs");
const root = fileURLToPath(new URL("../", import.meta.url));
const staticRoot = resolve(root, "frontend/dist");
const maxBodyBytes = 64 * 1024 * 1024;

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    const route = await routeApi(request, url);
    if (route) return sendJson(response, route.status ?? 200, route.body);
    if (request.method === "GET") return serveStatic(url.pathname, response);
    throw new HttpError(404, "找不到接口");
  } catch (error) {
    const status = Number(error?.status) || (error?.message === "Request body is too large" ? 413 : 500);
    if (status >= 500) console.error(JSON.stringify({ event: "api.error", message: error instanceof Error ? error.message : String(error) }));
    sendJson(response, status, { error: error instanceof Error ? error.message : "服务器错误" });
  }
});

async function routeApi(request, url) {
  const parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] !== "api") return null;
  if (request.method === "GET" && parts[1] === "health") return { body: await health() };
  if (parts.length === 2 && parts[1] === "kbs" && request.method === "GET") return { body: { kbs: await listKnowledgeBases() } };
  if (parts.length === 2 && parts[1] === "kbs" && request.method === "POST") {
    const body = await readJson(request);
    return { status: 201, body: { kb: await createKnowledgeBase(body.name, body.modelKey) } };
  }
  if (parts[1] !== "kbs" || !parts[2]) return null;
  const kbId = parts[2];
  if (parts.length === 4 && parts[3] === "deduplicate" && request.method === "POST") {
    const body = await readJson(request);
    if (!Array.isArray(body.hashes) || body.hashes.some((hash) => !/^[a-f0-9]{64}$/.test(hash))) throw new HttpError(400, "SHA-256 列表无效");
    return { body: { duplicates: await findDuplicateDocuments(kbId, body.hashes) } };
  }
  if (parts.length === 4 && parts[3] === "documents" && request.method === "GET") return { body: { documents: await listDocuments(kbId) } };
  if (parts.length === 4 && parts[3] === "documents" && request.method === "POST") {
    return { status: 201, body: await importDocument(kbId, await readJson(request)) };
  }
  if (parts.length === 5 && parts[3] === "documents" && request.method === "GET") return { body: { document: await getDocument(kbId, parts[4]) } };
  if (parts.length === 4 && parts[3] === "search" && request.method === "POST") return { body: await search(kbId, await readJson(request)) };
  throw new HttpError(404, "找不到接口");
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maxBodyBytes) throw new HttpError(413, "Request body is too large");
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new HttpError(400, "请求 JSON 格式无效");
  }
}

function sendJson(response, status, value) {
  if (response.headersSent) return;
  response.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  response.end(JSON.stringify(value));
}

function serveStatic(pathname, response) {
  const candidate = resolve(staticRoot, `.${decodeURIComponent(pathname)}`);
  const rel = relative(staticRoot, candidate);
  const safe = rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
  const file = safe && existsSync(candidate) ? candidate : resolve(staticRoot, "index.html");
  if (!existsSync(file)) return sendJson(response, 503, { error: "前端尚未构建；开发时请访问 Vite 端口 5174" });
  const type = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml" }[extname(file)] ?? "application/octet-stream";
  response.writeHead(200, { "content-type": type, "cache-control": "no-cache" });
  createReadStream(file).pipe(response);
}

await initializeDatabase();
const port = Number(process.env.PORT ?? 4174);
server.listen(port, "127.0.0.1", () => console.info(JSON.stringify({ event: "api.ready", url: `http://127.0.0.1:${port}` })));

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
