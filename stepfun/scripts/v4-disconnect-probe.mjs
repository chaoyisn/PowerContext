import { createServer, createConnection } from "node:net";
import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const evidence = { at: new Date().toISOString(), fault: "isolated TCP proxy on 127.0.0.1:2883 to dedicated edgeseek-seekdb:2882; no database container stopped", errors: [], apiLog: [], viteLog: [] };
const channel = process.env.EDGESEEK_BROWSER || "chrome";
const headed = process.env.EDGESEEK_HEADED === "1";
const resultName = process.env.EDGESEEK_RESULT_NAME || "disconnect-probe";
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
evidence.channel = channel; evidence.headed = headed;
await mkdir(outputDir, { recursive: true });
let available = true;
let stall = false;
let armRefreshFailure = false;
let injectedRefreshFailure = false;
const sockets = new Set();
const proxy = createServer(incoming => {
  if (!available) return incoming.destroy();
  const outgoing = createConnection({ host: "127.0.0.1", port: 2882 });
  sockets.add(incoming); sockets.add(outgoing);
  const close = () => { incoming.destroy(); outgoing.destroy(); sockets.delete(incoming); sockets.delete(outgoing); };
  incoming.on("error", close); outgoing.on("error", close);
  incoming.on("close", () => { sockets.delete(incoming); outgoing.destroy(); });
  outgoing.on("close", () => { sockets.delete(outgoing); incoming.destroy(); });
  incoming.on("data", chunk => {
    if (stall) return;
    if (armRefreshFailure && chunk.toString("utf8").toLowerCase().includes("dbms_index_manager.refresh")) {
      armRefreshFailure = false; injectedRefreshFailure = true; available = false; close(); return;
    }
    outgoing.write(chunk);
  });
  outgoing.on("data", chunk => incoming.write(chunk));
});
let api, vite, browser;
function startApi() {
  const child = spawn(process.execPath, ["server/index.mjs"], { env: { ...process.env, SEEKDB_HOST: "127.0.0.1", SEEKDB_PORT: "2883", PORT: "4174" }, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout.on("data", chunk => evidence.apiLog.push(String(chunk)));
  child.stderr.on("data", chunk => evidence.apiLog.push(String(chunk)));
  return child;
}
try {
  await new Promise((resolve, reject) => proxy.once("error", reject).listen(2883, "127.0.0.1", resolve));
  api = startApi();
  vite = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--config", "scripts/vite-lab.config.mjs"], { stdio: ["ignore", "pipe", "pipe"] });
  for (const [child, log] of [[vite, evidence.viteLog]]) {
    child.stdout.on("data", chunk => log.push(String(chunk)));
    child.stderr.on("data", chunk => log.push(String(chunk)));
  }
  for (const url of ["http://127.0.0.1:4174/api/health", "http://127.0.0.1:5174/probe.html"]) {
    let ready = false;
    for (let attempt = 0; attempt < 60; attempt++) {
      if (api.exitCode !== null || vite.exitCode !== null) throw new Error("Test server exited during startup");
      try { if ((await fetch(url, { signal: AbortSignal.timeout(1000) })).ok) { ready = true; break; } } catch { /* wait */ }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    if (!ready) throw new Error(`Timed out waiting for ${url}`);
  }
  browser = await chromium.launch({ channel, headless: !headed, timeout: 20000 });
  evidence.browser = browser.version();
  const context = await browser.newContext();
  await context.addInitScript(() => localStorage.setItem("edgeseek.precision", "int8"));
  const page = await context.newPage();
  evidence.consoleErrors = [];
  page.on("pageerror", error => evidence.consoleErrors.push(String(error)));
  page.on("console", message => { if (message.type() === "error") evidence.consoleErrors.push(message.text()); });
  const payloads = {};
  page.setDefaultTimeout(20000);
  await page.goto("http://127.0.0.1:5174/");
  await page.getByText("seekdb 已连接").waitFor();
  await page.getByRole("button", { name: "新建知识库" }).click();
  await page.locator(".modal-card input").fill(`v4-disconnect-${Date.now()}`);
  await page.locator(".modal-card").getByRole("button", { name: "创建知识库" }).click();
  await page.getByRole("status").getByText(/已创建知识库/).waitFor({ timeout: 120000 });
  evidence.kbId = await page.getByLabel("切换知识库").inputValue();
  await page.locator('input[type="file"]').setInputFiles({ name: "recovery.md", mimeType: "text/markdown", buffer: Buffer.from("Browser-side embeddings protect privacy and the database enables semantic search.") });
  await page.getByText("已导入 1 份新文档", { exact: false }).waitFor({ timeout: 120000 });
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill("How do browser embeddings protect privacy?");
  async function query(label, kbId = evidence.kbId) {
    const start = performance.now();
    try {
      const [response] = await Promise.all([page.waitForResponse(r => r.url().includes(`/api/kbs/${kbId}/search`) && r.request().method() === "POST", { timeout: 30000 }), page.getByRole("button", { name: "开始检索" }).click()]);
      payloads[label] = response.request().postDataJSON();
      const body = await response.json();
      const result = { label, status: response.status(), elapsedMs: performance.now() - start, body };
      if (!response.ok()) { await page.getByRole("alert").waitFor({ timeout: 5000 }); result.uiError = await page.getByRole("alert").innerText(); }
      return result;
    } catch (error) { return { label, elapsedMs: performance.now() - start, error: error.stack || String(error) }; }
  }
  evidence.before = await query("before");
  await new Promise(resolve => { api.once("exit", resolve); api.kill(); });
  api = startApi();
  let restarted = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    try { if ((await fetch("http://127.0.0.1:4174/api/health", { signal: AbortSignal.timeout(1000) })).ok) { restarted = true; break; } } catch { /* wait */ }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  if (!restarted) throw new Error("API did not restart");
  evidence.afterApiRestart = await query("after-api-restart");
  evidence.restartSameIds = JSON.stringify(evidence.before.body?.results?.map(row => row.id)) === JSON.stringify(evidence.afterApiRestart.body?.results?.map(row => row.id));
  available = false;
  for (const socket of sockets) socket.destroy();
  evidence.disconnected = await query("disconnected");
  available = true;
  evidence.recovered = await query("recovered");
  evidence.sameIds = JSON.stringify(evidence.before.body?.results?.map(row => row.id)) === JSON.stringify(evidence.recovered.body?.results?.map(row => row.id));
  const files = [
    { name: "interrupted-one.md", mimeType: "text/markdown", buffer: Buffer.from("A batch import should recover safely after an index refresh interruption.") },
    { name: "interrupted-two.md", mimeType: "text/markdown", buffer: Buffer.from("A second document keeps a stable identifier when the batch is retried.") },
  ];
  armRefreshFailure = true;
  const batchResponse = page.waitForResponse(r => r.url().endsWith("/documents/batch") && r.request().method() === "POST", { timeout: 30000 });
  await page.locator('input[type="file"]').setInputFiles(files);
  const failed = await batchResponse;
  evidence.writeFailure = { injectedAtRefresh: injectedRefreshFailure, status: failed.status(), body: await failed.json() };
  await page.getByRole("alert").waitFor();
  evidence.writeFailure.uiError = await page.getByRole("alert").innerText();
  available = true;
  const list = async () => (await (await fetch(`http://127.0.0.1:4174/api/kbs/${evidence.kbId}/documents`)).json()).documents;
  const pending = (await list()).filter(doc => doc.filename.startsWith("interrupted-"));
  evidence.pendingAfterFailure = pending;
  await page.locator('input[type="file"]').setInputFiles(files);
  await page.getByText("已导入 2 份新文档", { exact: false }).waitFor({ timeout: 120000 });
  const completed = (await list()).filter(doc => doc.filename.startsWith("interrupted-"));
  evidence.completedAfterRetry = completed;
  evidence.preexistingPreserved = (await list()).some(doc => doc.filename === "recovery.md" && doc.status === "imported");
  evidence.stableDocumentIds = pending.length === 2 && completed.length === 2 && pending.every(doc => completed.some(row => row.id === doc.id && row.status === "imported"));
  await page.locator('input[type="file"]').setInputFiles(files);
  await page.getByText("所选 2 份文档都已导入，未重复计算向量").waitFor();
  evidence.duplicateSkippedAfterRetry = true;
  await page.getByLabel("检索内容").fill("How does a batch import recover after index refresh interruption?");
  evidence.afterWriteRecovery = await query("after-write-recovery");
  evidence.uniqueChunkIds = new Set(evidence.afterWriteRecovery.body?.results?.map(row => row.id)).size === evidence.afterWriteRecovery.body?.results?.length;
  await page.getByLabel("检索内容").fill("How do browser embeddings protect privacy?");
  const baselineA = await query("concurrent-a");
  await page.getByLabel("检索内容").fill("How does a batch import recover after index refresh interruption?");
  const baselineB = await query("concurrent-b");
  const baselines = [baselineA, baselineB].map(row => row.body?.results?.map(result => result.id));
  const concurrent = await Promise.all(Array.from({ length: 6 }, async (_, i) => {
    const response = await fetch(`http://127.0.0.1:4174/api/kbs/${evidence.kbId}/search`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payloads[i % 2 ? "concurrent-b" : "concurrent-a"]), signal: AbortSignal.timeout(30000) });
    const body = await response.json();
    return { status: response.status, matches: JSON.stringify(body.results?.map(row => row.id)) === JSON.stringify(baselines[i % 2]) };
  }));
  evidence.concurrent = concurrent;
  stall = true;
  evidence.timeout = await query("stalled");
  stall = false;
  evidence.afterTimeout = await query("after-timeout");
  const qualityDir = process.env.EDGESEEK_QUALITY_DIR || "benchmark/results/v3";
  const other = JSON.parse(await readFile(`${qualityDir}/quality-int8.json`, "utf8"));
  await page.getByLabel("切换知识库").selectOption(other.kbId);
  await page.getByLabel("检索内容").fill("How can local browser processing protect private documents?");
  evidence.switchedKnowledgeBase = await query("switched-kb", other.kbId);
  await page.reload();
  await page.waitForFunction(id => document.querySelector('select[aria-label="切换知识库"]')?.value === id, other.kbId, { timeout: 30000 });
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill("How can local browser processing protect private documents?");
  evidence.afterRefresh = await query("after-refresh", other.kbId);
  const unused = createServer();
  await new Promise(resolve => unused.listen(0, "127.0.0.1", resolve));
  const unusedPort = unused.address().port;
  await new Promise(resolve => unused.close(resolve));
  const broken = spawn(process.execPath, ["server/index.mjs"], { env: { ...process.env, SEEKDB_HOST: "127.0.0.1", SEEKDB_PORT: String(unusedPort), PORT: "4191" }, stdio: ["ignore", "pipe", "pipe"] });
  let startupLog = "";
  broken.stdout.on("data", chunk => { startupLog += String(chunk); });
  broken.stderr.on("data", chunk => { startupLog += String(chunk); });
  const startupExit = await new Promise(resolve => {
    const timeout = setTimeout(() => { broken.kill(); resolve("timeout"); }, 15000);
    broken.once("exit", code => { clearTimeout(timeout); resolve(code); });
  });
  evidence.startupFailure = { exitCode: startupExit, output: startupLog };
  evidence.browserPerformance = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]").filter(row => ["model.load", "query.embedding"].includes(row.name)));
  await page.screenshot({ path: `${outputDir}/${resultName}.png`, timeout: 15000 }).catch(error => { evidence.screenshotError = String(error); });
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  if (api && api.exitCode === null) api.kill();
  if (vite && vite.exitCode === null) vite.kill();
  for (const socket of sockets) socket.destroy();
  await new Promise(resolve => proxy.close(() => resolve()));
  await writeFile(`${outputDir}/${resultName}.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ before: evidence.before, disconnected: evidence.disconnected, recovered: evidence.recovered, sameIds: evidence.sameIds, errors: evidence.errors }, null, 2));
}
