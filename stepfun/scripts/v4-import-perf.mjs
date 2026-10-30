import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";

const docs = [
  ["browser.md", "A browser computes private semantic embeddings."],
  ["database.md", "A database indexes and searches vector documents."],
  ["incremental.md", "An incremental import refreshes newly added chunks."],
  ["hybrid.md", "A hybrid search combines text and vector relevance."],
];
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
await mkdir(outputDir, { recursive: true });
const groups = { single: [[0], [1], [2], [3]], batch: [[0, 1, 2, 3]], incremental: [[0, 1], [2, 3]] };
const evidence = { at: new Date().toISOString(), browser: "chrome headless", precision: "WASM q8", samples: [], errors: [], corpus: docs.map(([filename, text]) => ({ filename, characters: text.length })), note: "UI upload time starts before first file selection and ends when final success is visible; individual stage timings can overlap and are not added to derive the total." };
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  evidence.version = browser.version();
  const context = await browser.newContext();
  await context.addInitScript(() => localStorage.setItem("edgeseek.precision", "int8"));
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  await page.goto("http://127.0.0.1:5174/");
  await page.getByText("seekdb 已连接").waitFor();
  for (const [strategy, batches] of Object.entries(groups)) for (let run = 1; run <= 5; run++) {
    await page.locator("nav").getByRole("button", { name: /知识库/ }).click();
    await page.getByRole("button", { name: "新建知识库" }).click();
    const name = `v4-import-${strategy}-${run}-${Date.now()}`;
    await page.locator(".modal-card input").fill(name);
    await page.locator(".modal-card").getByRole("button", { name: "创建知识库" }).click();
    await page.getByRole("status").getByText(`已创建知识库「${name}」`).waitFor({ timeout: 120000 });
    const kbId = await page.getByLabel("切换知识库").inputValue();
    const before = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]").length);
    const started = performance.now();
    for (const batch of batches) {
      const files = batch.map(index => ({ name: docs[index][0], mimeType: "text/markdown", buffer: Buffer.from(docs[index][1]) }));
      await page.locator('input[type="file"]').setInputFiles(files);
      await page.getByText(`已导入 ${batch.length} 份新文档`, { exact: false }).waitFor({ timeout: 120000 });
      await page.getByRole("button", { name: "关闭提示" }).click();
    }
    const importVisibleMs = performance.now() - started;
    const rows = await page.evaluate(n => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]").slice(n), before);
    const sum = (name, field = "durationMs") => rows.filter(row => row.name === name).reduce((total, row) => total + (row[field] ?? 0), 0);
    const sample = { strategy, run, kbId, importVisibleMs, embeddingMs: sum("embedding.batch"), apiRoundTripMs: sum("network.document-write"), dbWriteMs: sum("seekdb.write"), refreshMs: sum("seekdb.index-refresh"), visibilityMs: sum("seekdb.index-refresh", "visibleMs"), verification: [] };
    evidence.samples.push(sample);
    await page.getByRole("button", { name: "智能检索" }).click();
    await page.getByRole("tab", { name: "向量", exact: true }).click();
    for (const [filename, text] of docs) {
      await page.getByLabel("检索内容").fill(text);
      const [response] = await Promise.all([page.waitForResponse(r => r.url().endsWith(`/api/kbs/${kbId}/search`) && r.request().method() === "POST", { timeout: 60000 }), page.getByRole("button", { name: "开始检索" }).click()]);
      const body = await response.json();
      sample.verification.push({ filename, status: response.status(), found: body.results?.some(row => row.metadata?.filename === filename) ?? false });
    }
    if (sample.verification.some(row => !row.found || row.status !== 200)) throw new Error(`Visibility verification failed: ${strategy} run ${run}`);
  }
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile(`${outputDir}/import-perf.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ samples: evidence.samples, errors: evidence.errors }, null, 2));
}
