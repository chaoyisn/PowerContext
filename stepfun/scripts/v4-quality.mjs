import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { embeddingSpace } from "../frontend/src/embedding-space.mjs";

const precision = process.argv[2] || "int8";
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
const raw = await readFile("benchmark/v4-quality.json");
const dataset = JSON.parse(raw);
const model = JSON.parse(await readFile("model.json", "utf8"));
const dtype = { int8: "q8", fp32: "fp32", fp16: "fp16" }[precision];
const backend = precision === "fp16" ? "WebGPU" : "WASM";
const modelKey = embeddingSpace(model.modelKey, model.revision, backend, dtype);
const evidence = { at: new Date().toISOString(), precision, backend, datasetSha256: createHash("sha256").update(raw).digest("hex"), dataset: "benchmark/v4-quality.json", corpusSize: dataset.documents.length, queryCount: dataset.queries.length, cases: [], errors: [], note: "Original synthetic corpus with labels assigned before evaluation; results are not a general-domain benchmark." };
let browser;
try {
  browser = await chromium.launch({ channel: "msedge", headless: false, ignoreDefaultArgs: ["--enable-unsafe-swiftshader"] });
  evidence.browserVersion = browser.version();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:5174/embedding-lab.html");
  evidence.adapter = await page.evaluate(async () => { const a = await navigator.gpu?.requestAdapter(); return a ? { vendor: a.info?.vendor, architecture: a.info?.architecture, fallback: a.info?.isFallbackAdapter, shaderF16: a.features.has("shader-f16") } : null; });
  const result = await page.evaluate(async ({ precision, dtype, backend, modelKey, documents, queries }) => {
    const { EmbeddingClient } = await import("/src/embedding.ts");
    const worker = new EmbeddingClient();
    const data = { cases: [], errors: [] };
    try {
      const state = await worker.initialize(precision);
      data.state = state;
      if (state.backend !== backend || state.dtype !== dtype) throw new Error(`Unexpected fallback: ${state.backend}/${state.dtype}`);
      const create = await fetch("/api/kbs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: `v4-quality-${precision}-${Date.now()}`, modelKey }) });
      const created = await create.json();
      if (!create.ok) throw new Error(`Create knowledge base failed: ${JSON.stringify(created)}`);
      data.kbId = created.kb.id;
      const batch = await worker.embed(documents.map(doc => doc.text), 4);
      if (batch.backend !== backend || batch.dtype !== dtype) throw new Error("Runtime changed space during document embedding");
      data.documentEmbeddingMs = batch.elapsedMs;
      const hex = bytes => Array.from(new Uint8Array(bytes)).map(byte => byte.toString(16).padStart(2, "0")).join("");
      const payload = await Promise.all(documents.map(async (doc, i) => ({ filename: doc.filename, content: doc.text, sha256: hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(doc.text))), modelKey, backend, dtype, chunks: [{ text: doc.text, embedding: batch.embeddings[i] }] })));
      const imported = await fetch(`/api/kbs/${data.kbId}/documents/batch`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ documents: payload }) });
      const importBody = await imported.json();
      if (!imported.ok || importBody.results?.length !== documents.length) throw new Error(`Import failed: ${JSON.stringify(importBody)}`);
      data.import = { count: importBody.results.length, refreshMs: importBody.refreshMs, visibilityMs: importBody.visibilityMs, writeMs: importBody.results.reduce((sum, row) => sum + (row.writeMs || 0), 0) };
      for (const query of queries) {
        const vector = await worker.embed([query.text], 1);
        if (vector.backend !== backend || vector.dtype !== dtype) throw new Error("Runtime changed space during query embedding");
        for (const mode of ["vector", "hybrid"]) {
          const response = await fetch(`/api/kbs/${data.kbId}/search`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query: query.text, embedding: vector.embeddings[0], modelKey, backend, dtype, mode, topK: 10 }) });
          const body = await response.json();
          if (!response.ok) throw new Error(`Search failed: ${JSON.stringify(body)}`);
          data.cases.push({ id: query.id, language: query.language, mode, ranking: body.results.map(row => row.metadata.filename), resultIds: body.results.map(row => row.id), embeddingMs: vector.elapsedMs, dbMs: body.dbMs });
        }
      }
    } catch (error) { data.errors.push(error.stack || String(error)); }
    finally { worker.close(); }
    return data;
  }, { precision, dtype, backend, modelKey, documents: dataset.documents, queries: dataset.queries.map(({ id, text, language }) => ({ id, text, language })) });
  Object.assign(evidence, result);
  const labels = new Map(dataset.queries.map(query => [query.id, query.relevant]));
  for (const row of evidence.cases) {
    const relevant = new Set(labels.get(row.id));
    const recall = k => row.ranking.slice(0, k).filter(filename => relevant.has(filename)).length / relevant.size;
    const rank = row.ranking.findIndex(filename => relevant.has(filename)) + 1;
    const dcg = row.ranking.slice(0, 10).reduce((sum, filename, index) => sum + (relevant.has(filename) ? 1 / Math.log2(index + 2) : 0), 0);
    const ideal = [...relevant].reduce((sum, _, index) => sum + 1 / Math.log2(index + 2), 0);
    Object.assign(row, { gold: [...relevant], recall1: recall(1), recall5: recall(5), recall10: recall(10), mrr10: rank > 0 ? 1 / rank : 0, ndcg10: dcg / ideal });
  }
  evidence.complete = evidence.cases.length === dataset.queries.length * 2 && !evidence.errors.length;
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await mkdir(outputDir, { recursive: true });
  await writeFile(`${outputDir}/quality-${precision}.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ precision, complete: evidence.complete, kbId: evidence.kbId, cases: evidence.cases.length, errors: evidence.errors }, null, 2));
}
