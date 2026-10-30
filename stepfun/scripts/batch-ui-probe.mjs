import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";

const texts = ["A browser computes private semantic embeddings.", "A database indexes and searches vector documents.", "An incremental import refreshes newly added chunks.", "A hybrid search combines text and vector relevance."];
const evidence = { at: new Date().toISOString(), browser: "chrome headless", errors: [] };
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
  await page.getByRole("button", { name: "新建知识库" }).click();
  await page.locator(".modal-card input").fill(`v3-batch-ui-${Date.now()}`);
  await page.locator(".modal-card").getByRole("button", { name: "创建知识库" }).click();
  await page.getByRole("status").getByText(/已创建知识库/).waitFor({ timeout: 120000 });
  evidence.kbId = await page.getByLabel("切换知识库").inputValue();
  const files = texts.map((text, i) => ({ name: `batch-${i}.md`, mimeType: "text/markdown", buffer: Buffer.from(text) }));
  const started = Date.now();
  const responsePromise = page.waitForResponse(r => r.url().endsWith("/documents/batch") && r.request().method() === "POST", { timeout: 120000 });
  await page.locator('input[type="file"]').setInputFiles(files);
  const response = await responsePromise;
  const body = await response.json();
  const sent = response.request().postDataJSON().documents;
  evidence.request = sent.map(doc => ({ filename: doc.filename, backend: doc.backend, dtype: doc.dtype, vectors: doc.chunks.map(chunk => ({ dimension: chunk.embedding.length, sha256: createHash("sha256").update(JSON.stringify(chunk.embedding)).digest("hex") })) }));
  evidence.response = { status: response.status(), ...body };
  await page.getByRole("status").getByText(/已导入 4 份新文档/).waitFor({ timeout: 30000 });
  evidence.importWallMs = Date.now() - started;
  await page.locator('input[type="file"]').setInputFiles(files);
  await page.getByText("所选 4 份文档都已导入，未重复计算向量").waitFor();
  evidence.duplicateSkipped = true;
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill("How does hybrid search combine text and vectors?");
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.locator(".result-card").first().waitFor({ timeout: 60000 });
  evidence.results = await page.locator(".result-source").allTextContents();
  evidence.pass = response.ok() && body.results.filter(row => !row.duplicate).length === 4 && sent.every(doc => doc.dtype === "q8" && doc.backend === "WASM") && evidence.results.some(row => row.includes("batch-3.md"));
  await page.screenshot({ path: "benchmark/results/v3/batch-ui.png", timeout: 15000 });
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile("benchmark/results/v3/batch-ui.json", JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify(evidence, null, 2));
}
