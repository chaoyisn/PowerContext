import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import test from "node:test";
import model from "../../model.json" with { type: "json" };

const root = fileURLToPath(new URL("../../", import.meta.url));

test("real API imports incrementally, isolates knowledge bases, and survives server restart", { timeout: 120_000 }, async () => {
  const port = await freePort();
  portForTest = port;
  const environment = { ...process.env, PORT: String(port), SEEKDB_HOST: "127.0.0.1", SEEKDB_PORT: "2882", SEEKDB_DATABASE: "test" };
  let child = await startServer(port, environment);
  try {
    const name = `workflow-${Date.now()}`;
    const { kb } = await json(`/api/kbs`, { method: "POST", body: { name, modelKey: model.modelKey } });
    const first = await importDocument(kb.id, "primary.md", "seekdb bluejay primary record", [1, 0, 0]);
    assert.equal(first.duplicate, false);
    assert.equal(first.chunks, 1);
    assert.ok(first.refreshMs >= 0);
    assert.ok(first.visibilityMs >= 0);

    const duplicate = await importDocument(kb.id, "primary.md", "seekdb bluejay primary record", [1, 0, 0]);
    assert.equal(duplicate.duplicate, true);
    const digest = hash("seekdb bluejay primary record");
    const deduplicated = await json(`/api/kbs/${kb.id}/deduplicate`, { method: "POST", body: { hashes: [digest] } });
    assert.deepEqual(deduplicated.duplicates, [digest]);

    const incremental = await importDocument(kb.id, "incremental.md", "new incremental cedar record", [0, 1, 0]);
    assert.equal(incremental.duplicate, false);
    const freshSearch = await search(kb.id, "cedar", [0, 1, 0], "fulltext");
    assert.equal(freshSearch.results[0]?.metadata.filename, "incremental.md");

    const { kb: isolated } = await json(`/api/kbs`, { method: "POST", body: { name: `${name}-isolated`, modelKey: model.modelKey } });
    await importDocument(isolated.id, "tenant-only.md", "private violet tenant token", [0, 0, 1]);
    const isolatedSearch = await search(isolated.id, "violet tenant", [0, 0, 1], "hybrid");
    assert.equal(isolatedSearch.results[0]?.metadata.filename, "tenant-only.md");
    const primarySearch = await search(kb.id, "violet tenant", [1, 0, 0], "hybrid");
    assert.ok(primarySearch.results.every((row) => row.metadata.filename !== "tenant-only.md"));

    const beforeRestart = await json(`/api/kbs/${kb.id}/documents`);
    assert.equal(beforeRestart.documents.length, 2);
    const original = await json(`/api/kbs/${kb.id}/documents/${first.documentId}`);
    assert.equal(original.document.content, "seekdb bluejay primary record");
    assert.equal(original.document.status, "imported");
    child = await stopServer(child);

    child = await startServer(port, environment);
    const afterRestart = await json(`/api/kbs`);
    assert.ok(afterRestart.kbs.some((row) => row.id === kb.id));
    const persisted = await json(`/api/kbs/${kb.id}/documents/${first.documentId}`);
    assert.equal(persisted.document.content, "seekdb bluejay primary record");
    const persistedSearch = await search(kb.id, "bluejay", [1, 0, 0], "hybrid");
    assert.equal(persistedSearch.results[0]?.metadata.filename, "primary.md");
    const evidence = { test: "real-api-workflow", measuredAt: new Date().toISOString(), source: "real seekdb server; synthetic normalized fixture vectors (not browser model output)", sdk: "seekdb@1.4.0", database: "test", kbId: kb.id, incremental: { duplicateSkipped: true, writeMs: incremental.writeMs, refreshMs: incremental.refreshMs, visibilityMs: incremental.visibilityMs, searchMs: freshSearch.dbMs, searchMode: "fulltext", searchFilename: freshSearch.results[0]?.metadata.filename }, restart: { documentCount: beforeRestart.documents.length, documentPersisted: true, searchMs: persistedSearch.dbMs, vectorSearchFilename: persistedSearch.results[0]?.metadata.filename }, isolation: { separateKbId: isolated.id, primaryContainsTenantDocument: primarySearch.results.some((row) => row.metadata.filename === "tenant-only.md") } };
    mkdirSync(resolve(root, "benchmark/results"), { recursive: true });
    writeFileSync(resolve(root, "benchmark/results/seekdb-api-actual.json"), `${JSON.stringify(evidence, null, 2)}\n`);
    console.info(JSON.stringify(evidence));
  } finally {
    if (child) await stopServer(child);
  }
});

async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => server.once("error", reject).listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function startServer(port, env) {
  const child = spawn(process.execPath, ["server/index.mjs"], { cwd: root, env: { ...env, PORT: String(port) }, stdio: ["ignore", "pipe", "pipe"] });
  let output = "";
  child.stdout.setEncoding("utf8").on("data", (chunk) => { output += chunk; });
  child.stderr.setEncoding("utf8").on("data", (chunk) => { output += chunk; });
  for (let attempt = 0; attempt < 120; attempt++) {
    if (child.exitCode !== null) throw new Error(`API child exited (${child.exitCode}): ${output}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (response.ok && (await response.json()).ok) return child;
    } catch { /* server not ready yet */ }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  child.kill();
  throw new Error(`Timed out waiting for API child: ${output}`);
}

async function stopServer(child) {
  if (child.exitCode !== null) return null;
  await new Promise((resolve) => {
    const timer = setTimeout(() => { child.kill(); resolve(); }, 5000);
    child.once("exit", () => { clearTimeout(timer); resolve(); });
    child.kill("SIGTERM");
  });
  return null;
}

async function json(path, options = {}) {
  const response = await fetch(`http://127.0.0.1:${portForTest}/${path.replace(/^\//, "")}`, {
    method: options.method ?? "GET",
    headers: options.body ? { "content-type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const body = await response.json();
  assert.ok(response.ok, `${response.status} ${JSON.stringify(body)}`);
  return body;
}

let portForTest;

async function importDocument(kbId, filename, content, direction) {
  const vector = Array(384).fill(0);
  direction.forEach((value, index) => { vector[index] = value; });
  return json(`/api/kbs/${kbId}/documents`, { method: "POST", body: {
    filename, content, sha256: hash(content), modelKey: model.modelKey, dtype: "fixture", chunks: [{ text: content, embedding: vector }],
  } });
}

async function search(kbId, query, direction, mode) {
  const embedding = Array(384).fill(0);
  direction.forEach((value, index) => { embedding[index] = value; });
  return json(`/api/kbs/${kbId}/search`, { method: "POST", body: { query, embedding, modelKey: model.modelKey, mode, topK: 5 } });
}

function hash(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}
