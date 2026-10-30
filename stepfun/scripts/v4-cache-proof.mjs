import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";

const precision = process.argv[2] || "int8";
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
await mkdir(outputDir, { recursive: true });
const gpu = precision === "fp16";
const evidence = { at: new Date().toISOString(), precision, blockedRequests: [], errors: [], note: "Fresh isolated context; warm pass blocks all model HTTP requests to prove cached model assets are sufficient." };
let browser;
try {
  browser = await chromium.launch({ channel: gpu ? "msedge" : "chrome", headless: !gpu, ...(gpu ? { ignoreDefaultArgs: ["--enable-unsafe-swiftshader"] } : {}) });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:5174/embedding-lab.html");
  const run = async () => page.evaluate(async precision => {
    const { EmbeddingClient } = await import("/src/embedding.ts");
    const client = new EmbeddingClient();
    try { const start = performance.now(); const state = await client.initialize(precision); const batch = await client.embed(["A browser creates a local embedding for a query."], 1); return { state, wallMs: performance.now() - start, dimension: batch.embeddings[0].length, backend: batch.backend, dtype: batch.dtype }; }
    finally { client.close(); }
  }, precision);
  evidence.before = await page.evaluate(() => caches.keys());
  evidence.cold = await run();
  evidence.cache = await page.evaluate(async () => Promise.all((await caches.keys()).map(async name => ({ name, urls: (await (await caches.open(name)).keys()).map(request => request.url) }))));
  await context.route("**/models/**", async route => { evidence.blockedRequests.push(route.request().url()); await route.abort(); });
  evidence.warm = await run();
  evidence.pass = evidence.before.length === 0 && evidence.cache.some(cache => cache.urls.some(url => /model(?:_quantized|_fp16)?\.onnx/.test(url))) && evidence.warm.dimension === 384 && evidence.warm.backend === evidence.cold.backend && evidence.warm.dtype === evidence.cold.dtype;
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile(`${outputDir}/cache-proof-${precision}.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ precision, pass: evidence.pass, cold: evidence.cold, warm: evidence.warm, blocked: evidence.blockedRequests.length, errors: evidence.errors }, null, 2));
}
