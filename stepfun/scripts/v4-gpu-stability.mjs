import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { embeddingSpace } from "../frontend/src/embedding-space.mjs";

const model = JSON.parse(await readFile("model.json", "utf8"));
const qualityDir = process.env.EDGESEEK_QUALITY_DIR || "benchmark/results/v3";
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
await mkdir(outputDir, { recursive: true });
const prior = JSON.parse(await readFile(`${qualityDir}/quality-fp16.json`, "utf8"));
const resultName = process.env.EDGESEEK_RESULT_NAME || "gpu-stability";
const evidence = { at: new Date().toISOString(), headed: true, channel: "msedge", kbId: prior.kbId, query: "How can local browser processing protect private documents?", samples: [], errors: [] };
let browser;
try {
  browser = await chromium.launch({ channel: "msedge", headless: false, ignoreDefaultArgs: ["--enable-unsafe-swiftshader"] });
  evidence.version = browser.version();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:5174/embedding-lab.html");
  evidence.adapter = await page.evaluate(async () => { const a = await navigator.gpu?.requestAdapter(); return a ? { vendor: a.info?.vendor, architecture: a.info?.architecture, fallback: a.info?.isFallbackAdapter, shaderF16: a.features.has("shader-f16") } : null; });
  const result = await page.evaluate(async ({ kbId, query, modelKey }) => {
    const { EmbeddingClient } = await import("/src/embedding.ts");
    const worker = new EmbeddingClient();
    try {
      const state = await worker.initialize("fp16");
      if (state.backend !== "WebGPU" || state.dtype !== "fp16") throw new Error(`GPU unavailable: ${state.backend} ${state.dtype}`);
      const samples = [];
      let baseline;
      for (let run = 1; run <= 20; run++) {
        const batch = await worker.embed([query], 1);
        if (batch.backend !== "WebGPU" || batch.dtype !== "fp16") throw new Error("Runtime fell back; refusing to label output as FP16");
        const vector = batch.embeddings[0];
        baseline ??= vector;
        const l2 = Math.sqrt(vector.reduce((sum, x, i) => sum + (x - baseline[i]) ** 2, 0));
        const dot = vector.reduce((sum, x, i) => sum + x * baseline[i], 0);
        const norm = v => Math.sqrt(v.reduce((sum, x) => sum + x*x, 0));
        const cosine = dot / (norm(vector) * norm(baseline));
        const response = await fetch(`/api/kbs/${kbId}/search`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query, embedding: vector, modelKey, backend: "WebGPU", dtype: "fp16", mode: "hybrid", topK: 5 }) });
        const body = await response.json();
        if (!response.ok) throw new Error(`search HTTP ${response.status}: ${JSON.stringify(body)}`);
        const sha256 = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(vector))))).map(b => b.toString(16).padStart(2, "0")).join("");
        samples.push({ run, l2, cosine, norm: norm(vector), sha256, inferenceMs: batch.elapsedMs, rankedIds: body.results.map(row => row.id), rankedFiles: body.results.map(row => row.metadata.filename), dbMs: body.dbMs });
      }
      return { state, samples };
    } finally { worker.close(); }
  }, { kbId: prior.kbId, query: evidence.query, modelKey: embeddingSpace(model.modelKey, model.revision, "WebGPU", "fp16") });
  Object.assign(evidence, result);
  const first = JSON.stringify(evidence.samples[0].rankedIds);
  evidence.rankingIdentical = evidence.samples.every(row => JSON.stringify(row.rankedIds) === first);
  evidence.maxL2 = Math.max(...evidence.samples.map(row => row.l2));
  evidence.minCosine = Math.min(...evidence.samples.map(row => row.cosine));
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile(`${outputDir}/${resultName}.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ samples: evidence.samples.length, rankingIdentical: evidence.rankingIdentical, maxL2: evidence.maxL2, minCosine: evidence.minCosine, adapter: evidence.adapter, errors: evidence.errors }, null, 2));
}
