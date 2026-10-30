import { chromium } from "playwright";
import { createHash, randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import { writeFile } from "node:fs/promises";
import { FulltextIndexConfig, Schema, SeekdbClient, VectorIndexConfig } from "seekdb";
import { loadEnv } from "../server/env.mjs";

loadEnv();
const evidence = { at: new Date().toISOString(), description: "Four real browser q8 vectors, five independent collections per strategy, same texts and query; timings exclude collection creation.", samples: [], errors: [] };
const deferredOnly = process.argv[2] === "deferred";
const texts = ["A browser computes private semantic embeddings.", "A database indexes and searches vector documents.", "An incremental import refreshes newly added chunks.", "A hybrid search combines text and vector relevance."];
let browser, client;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  evidence.browser = browser.version();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:5174/embedding-lab.html");
  const browserOutput = await page.evaluate(async texts => {
    const { EmbeddingClient } = await import("/src/embedding.ts");
    const worker = new EmbeddingClient();
    try { const state = await worker.initialize("int8"); const batch = await worker.embed(texts, 1); return { state, batch }; }
    finally { worker.close(); }
  }, texts);
  const vectors = browserOutput.batch.embeddings;
  evidence.backend = browserOutput.state.backend;
  evidence.dtype = browserOutput.state.dtype;
  evidence.vectorSha256 = vectors.map(vector => createHash("sha256").update(JSON.stringify(vector)).digest("hex"));
  if (evidence.backend !== "WASM" || evidence.dtype !== "q8" || vectors.some(v => v.length !== 384 || v.some(n => !Number.isFinite(n)))) throw new Error("Unexpected browser embedding configuration");
  await context.close();
  await browser.close(); browser = null;
  client = new SeekdbClient({ host: process.env.SEEKDB_HOST ?? "127.0.0.1", port: Number(process.env.SEEKDB_PORT ?? 2882), user: process.env.SEEKDB_USER ?? "root", password: process.env.SEEKDB_PASSWORD ?? "", database: process.env.SEEKDB_DATABASE ?? "test" });
  const strategies = deferredOnly ? [["deferred-refresh", [[0],[1],[2],[3]], false]] : [["single-refresh", [[0],[1],[2],[3]], true], ["batch-refresh", [[0,1,2,3]], true], ["incremental-refresh", [[0,1],[2,3]], true]];
  for (const [strategy, groups, refreshEach] of strategies) {
    for (let run = 1; run <= 5; run++) {
      const name = `edgeseek_v3_bench_${randomUUID().replaceAll("-", "")}`;
      const collection = await client.createCollection({ name, embeddingFunction: null, schema: new Schema({ fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }), vectorIndex: new VectorIndexConfig({ hnsw: { dimension: 384, distance: "cosine" }, embeddingFunction: null }) }) });
      const sample = { strategy, run, collection: name, writesMs: [], refreshesMs: [] };
      evidence.samples.push(sample);
      const started = performance.now();
      for (const [groupIndex, indices] of groups.entries()) {
        let t = performance.now();
        await collection.upsert({ ids: indices.map(i => `doc-${i}`), documents: indices.map(i => texts[i]), embeddings: indices.map(i => vectors[i]), metadatas: indices.map(i => ({ filename: `doc-${i}.txt` })) });
        sample.writesMs.push(performance.now() - t);
        if (refreshEach || groupIndex === groups.length - 1) {
          t = performance.now(); await collection.refresh_index(); sample.refreshesMs.push(performance.now() - t);
        }
      }
      sample.writeAndRefreshMs = performance.now() - started;
      const readback = await collection.get({ ids: ["doc-0", "doc-1", "doc-2", "doc-3"], include: ["embeddings"] });
      const query = await collection.query({ queryEmbeddings: [vectors[0]], nResults: 4, include: ["documents"] });
      const ids = Array.isArray(query.ids?.[0]) ? query.ids[0] : query.ids;
      sample.readbackCount = readback.ids.length;
      sample.searchIds = ids;
      sample.visible = sample.readbackCount === 4 && [0,1,2,3].every(i => ids.includes(`doc-${i}`));
      if (!sample.visible) throw new Error(`Final visibility failed for ${name}`);
    }
  }
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  if (client) await client.close().catch(() => {});
  await writeFile(`benchmark/results/v3/index-${deferredOnly ? "deferred" : "strategies"}.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify(evidence));
}
