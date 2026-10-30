import { chromium } from "playwright";
import { writeFile } from "node:fs/promises";

const evidence = { at: new Date().toISOString(), browser: "chrome headless", precision: "int8", samples: [], errors: [] };
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  evidence.version = browser.version();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:5174/embedding-lab.html");
  const data = await page.evaluate(async () => {
    const { EmbeddingClient } = await import("/src/embedding.ts");
    const client = new EmbeddingClient();
    try {
      const start = performance.now();
      const state = await client.initialize("int8");
      const wallInitMs = performance.now() - start;
      const texts = Array.from({ length: 16 }, (_, i) => `Document ${i}: the browser computes a normalized vector for semantic search and local knowledge retrieval.`);
      const samples = [];
      for (const batchSize of [1, 4, 8, 16]) {
        for (let run = 0; run < 5; run++) {
          const output = await client.embed(texts, batchSize);
          samples.push({ batchSize, run: run + 1, items: texts.length, elapsedMs: output.elapsedMs, itemsPerSecond: texts.length / (output.elapsedMs / 1000), backend: output.backend, dtype: output.dtype });
        }
      }
      return { state, wallInitMs, samples, memoryNote: "Browser process peak memory unavailable; no estimate recorded." };
    } finally { client.close(); }
  });
  Object.assign(evidence, data);
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile("benchmark/results/v3/batch-q8.json", JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify(evidence));
}
