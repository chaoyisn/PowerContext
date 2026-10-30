import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import test from "node:test";
import { createServer } from "node:net";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { embeddingSpace } from "../../frontend/src/embedding-space.mjs";

const model = JSON.parse(readFileSync(fileURLToPath(new URL("../../model.json", import.meta.url)), "utf8"));
const modelKey = embeddingSpace(model.modelKey, model.revision, "WASM", "q8");
const root = fileURLToPath(new URL("../../", import.meta.url));

test("API rejects model mismatch and invalid vector dimensions", async () => {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const child = await startServer(port);
  try {
    const health = await fetch(`${base}/api/health`);
    assert.equal(health.status, 200);
    const mismatch = await fetch(`${base}/api/kbs`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: `model-mismatch-${Date.now()}`, modelKey: "another-model@revision" }),
    });
    assert.equal(mismatch.status, 409);

    const create = await fetch(`${base}/api/kbs`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: `dimension-check-${Date.now()}`, modelKey }),
    });
    assert.equal(create.status, 201);
    const { kb } = await create.json();
    const badSearch = await fetch(`${base}/api/kbs/${kb.id}/search`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: "test", embedding: [1, 0, 0], modelKey, backend: "WASM", dtype: "q8", mode: "vector", topK: 5 }),
    });
    assert.equal(badSearch.status, 422);
    assert.match((await badSearch.json()).error, /384/);
    const wrongSpace = await fetch(`${base}/api/kbs/${kb.id}/search`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: "test", embedding: Array(384).fill(0), modelKey, backend: "WASM", dtype: "fp32", mode: "vector" }),
    });
    assert.equal(wrongSpace.status, 409);
  } finally {
    await stopServer(child);
  }
});

async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => server.once("error", reject).listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function startServer(port) {
  const child = spawn(process.execPath, ["server/index.mjs"], { cwd: root, env: { ...process.env, PORT: String(port), SEEKDB_PORT: "2882", SEEKDB_DATABASE: "test" }, stdio: ["ignore", "pipe", "pipe"] });
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
  if (child.exitCode !== null) return;
  await new Promise((resolve) => {
    const timer = setTimeout(() => { child.kill(); resolve(); }, 5000);
    child.once("exit", () => { clearTimeout(timer); resolve(); });
    child.kill("SIGTERM");
  });
}
