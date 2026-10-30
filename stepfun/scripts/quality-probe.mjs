import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";

const dataset = JSON.parse(await readFile("benchmark/v3-quality.json", "utf8"));
const precision = process.argv[2] || "int8";
const evidence = { at: new Date().toISOString(), precision, cases: [], errors: [], dataset: "benchmark/v3-quality.json", note: "Small independently labelled set; seven candidates make Recall@10 non-discriminating." };
let browser;
try {
  const useGpu = precision === "fp16";
  browser = await chromium.launch({ channel: useGpu ? "msedge" : "chrome", headless: !useGpu, timeout: 20000, ...(useGpu ? { ignoreDefaultArgs: ["--enable-unsafe-swiftshader"] } : {}) });
  evidence.browser = browser.version();
  const context = await browser.newContext();
  await context.addInitScript(value => localStorage.setItem("edgeseek.precision", value), precision);
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  await page.goto("http://127.0.0.1:5174/", { waitUntil: "load" });
  await page.getByText("seekdb 已连接").waitFor();
  await page.getByRole("button", { name: "新建知识库" }).click();
  const name = `v3-quality-${precision}-${Date.now()}`;
  await page.locator(".modal-card input").fill(name);
  await page.locator(".modal-card").getByRole("button", { name: "创建知识库" }).click();
  await page.getByLabel("切换知识库").selectOption({ label: name }, { timeout: 120000 });
  if (useGpu) {
    const loads = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]").filter(row => row.name === "model.load"));
    if (loads.at(-1)?.backend !== "WebGPU" || loads.at(-1)?.dtype !== "fp16") throw new Error("FP16 quality run fell back; refusing to label it WebGPU");
  }
  evidence.kbId = await page.getByLabel("切换知识库").inputValue();
  for (const doc of dataset.documents) {
    await page.locator('input[type="file"]').setInputFiles({ name: doc.name, mimeType: "text/markdown", buffer: Buffer.from(doc.text) });
    await page.getByText("已导入 1 份新文档", { exact: false }).waitFor({ timeout: 120000 });
    await page.getByRole("button", { name: "关闭提示" }).click();
  }
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.locator(".composer-tools select").selectOption("10");
  for (const query of dataset.queries) {
    for (const [mode, label] of [["vector", "向量"], ["hybrid", "混合检索"]]) {
      await page.getByLabel("检索内容").fill(query.text);
      await page.getByRole("tab", { name: label, exact: true }).click();
      const [response] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith("/search") && r.request().method() === "POST", { timeout: 60000 }),
        page.getByRole("button", { name: "开始检索" }).click(),
      ]);
      const body = await response.json();
      if (!response.ok()) throw new Error(`Search failed: ${JSON.stringify(body)}`);
      const ranking = body.results.map(row => row.metadata.filename);
      const relevant = new Set(query.relevant);
      const recall = k => ranking.slice(0, k).filter(name => relevant.has(name)).length / relevant.size;
      const dcg = ranking.slice(0, 10).reduce((sum, name, i) => sum + (relevant.has(name) ? 1 / Math.log2(i + 2) : 0), 0);
      const ideal = [...relevant].reduce((sum, _, i) => sum + 1 / Math.log2(i + 2), 0);
      evidence.cases.push({ id: query.id, language: query.language, mode, ranking, recall5: recall(5), recall10: recall(10), ndcg10: dcg / ideal, dbMs: body.dbMs });
    }
  }
  evidence.performance = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]"));
  evidence.complete = true;
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile(`benchmark/results/v3/quality-${precision}.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ precision, complete: evidence.complete, kbId: evidence.kbId, cases: evidence.cases, errors: evidence.errors }, null, 2));
}
