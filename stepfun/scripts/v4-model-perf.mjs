import { chromium } from "playwright";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdir, writeFile } from "node:fs/promises";

const runFile = promisify(execFile);
const precision = process.argv[2] || "int8";
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
await mkdir(outputDir, { recursive: true });
const gpu = precision === "fp16";
const evidence = { at: new Date().toISOString(), precision, channel: gpu ? "msedge" : "chrome", headed: gpu, samples: [], memory: [], errors: [], runtime: "Transformers.js 4.3.2; ONNX Runtime Web 1.31.0-dev.20260914-8d85527a0", revision: "751bff37182d3f1213fa05d7196b954e230abad9" };
let browser, monitoring = true, monitor;
try {
  browser = await chromium.launch({ channel: evidence.channel, headless: !gpu, timeout: 20000, ...(gpu ? { ignoreDefaultArgs: ["--enable-unsafe-swiftshader"] } : {}) });
  evidence.browserVersion = browser.version();
  const cdp = await browser.newBrowserCDPSession();
  monitor = (async () => {
    while (monitoring) {
      try {
        const info = await cdp.send("SystemInfo.getProcessInfo");
        const ids = info.processInfo.map(row => Number(row.id)).filter(Number.isSafeInteger);
        const command = `Get-Process -Id ${ids.join(",")} -ErrorAction SilentlyContinue | Select-Object Id,WorkingSet64 | ConvertTo-Json -Compress`;
        const { stdout } = await runFile("powershell.exe", ["-NoProfile", "-Command", command], { timeout: 8000, windowsHide: true });
        const parsed = JSON.parse(stdout || "[]");
        const processes = Array.isArray(parsed) ? parsed : [parsed];
        evidence.memory.push({ at: new Date().toISOString(), browserProcesses: processes.length, browserWorkingSetSum: processes.reduce((sum, row) => sum + (row.WorkingSet64 || 0), 0), harnessNodeRss: process.memoryUsage().rss });
      } catch (error) { evidence.memoryError = String(error); }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  })();
  const context = await browser.newContext();
  const page = await context.newPage();
  const network = [];
  page.on("response", response => { if (/\/models\/|ort-wasm/.test(response.url())) network.push({ at: Date.now(), url: response.url(), status: response.status(), bytes: response.headers()["content-length"] ?? null }); });
  await page.goto("http://127.0.0.1:5174/embedding-lab.html");
  if (gpu) evidence.adapter = await page.evaluate(async () => { const a = await navigator.gpu?.requestAdapter(); return a ? { vendor: a.info?.vendor, architecture: a.info?.architecture, fallback: a.info?.isFallbackAdapter, shaderF16: a.features.has("shader-f16") } : null; });
  const data = await page.evaluate(async precision => {
    const { EmbeddingClient } = await import("/src/embedding.ts");
    const texts = Array.from({ length: 32 }, (_, i) => `Document ${i}: local semantic retrieval protects private knowledge while a database indexes and searches text. ${"Context ".repeat((i % 7) + 1)}`);
    const cacheState = async () => Promise.all((await caches.keys()).map(async name => ({ name, entries: (await (await caches.open(name)).keys()).length })));
    const runInit = async () => {
      const worker = new EmbeddingClient();
      const events = [];
      const start = performance.now();
      worker.onProgress = event => { if (["download", "done"].includes(event.status) || ["model-ready", "first-inference", "worker-start"].includes(event.phase)) events.push({ ...event, atMs: performance.now() - start }); };
      const state = await worker.initialize(precision);
      return { worker, state, initWallMs: performance.now() - start, events };
    };
    const cacheBefore = await cacheState();
    const cold = await runInit();
    const coldPostInit = await cold.worker.embed([texts[0]], 1);
    cold.worker.close();
    const cacheAfterCold = await cacheState();
    const warm = await runInit();
    const warmSamples = [];
    for (let i = 0; i < 5; i++) warmSamples.push((await warm.worker.embed([texts[0]], 1)).elapsedMs);
    const samples = [];
    for (const batchSize of [1, 4, 8, 16]) for (let i = 0; i < 5; i++) {
      const batch = await warm.worker.embed(texts, batchSize);
      samples.push({ batchSize, run: i + 1, items: texts.length, elapsedMs: batch.elapsedMs, itemsPerSecond: texts.length * 1000 / batch.elapsedMs, backend: batch.backend, dtype: batch.dtype });
    }
    warm.worker.close();
    return { corpus: { count: texts.length, characterLengths: texts.map(text => text.length), tokenizerLengths: "not measured" }, cacheBefore, cacheAfterCold, cacheAfterWarm: await cacheState(), cold: { state: cold.state, initWallMs: cold.initWallMs, events: cold.events, firstPostInitInferenceMs: coldPostInit.elapsedMs }, warm: { state: warm.state, initWallMs: warm.initWallMs, events: warm.events, subsequentInferenceMs: warmSamples }, samples, pageJsHeapBytes: performance.memory?.usedJSHeapSize ?? null };
  }, precision);
  Object.assign(evidence, data, { network });
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  monitoring = false;
  if (monitor) await monitor;
  if (browser) await browser.close().catch(() => {});
  evidence.memorySummary = { metric: "maximum sampled sum of browser process working sets, shared pages can be counted more than once", sampledPeakBytes: evidence.memory.length ? Math.max(...evidence.memory.map(row => row.browserWorkingSetSum)) : null, nodeMetric: "test harness Node RSS, not API process", gpuMemory: "UNKNOWN" };
  await writeFile(`${outputDir}/model-perf-${precision}.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ precision, cold: evidence.cold, warm: evidence.warm, sampleCount: evidence.samples.length, memorySummary: evidence.memorySummary, adapter: evidence.adapter, errors: evidence.errors }, null, 2));
}
