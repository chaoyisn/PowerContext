import { chromium } from "playwright";
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";

const evidence = { started: new Date().toISOString(), events: [], errors: [] };
const evidenceDir = process.env.EDGESEEK_EVIDENCE_DIR || "benchmark/results/v2";
const channel = process.env.EDGESEEK_BROWSER || "chrome";
const headed = process.env.EDGESEEK_HEADED === "1";
evidence.channel = channel;
evidence.headed = headed;
await mkdir(evidenceDir, { recursive: true });
const docs = [
  ["vectors.md", "The database supports vector search. Semantic similarity finds documents by meaning."],
  ["privacy.md", "Browser-side embeddings can improve privacy. The browser computes vectors locally before storage."],
  ["indexes.md", "A seekdb index refresh makes newly inserted document chunks available for hybrid search."],
];
let browser;
try {
  browser = await chromium.launch({ channel, headless: !headed, timeout: 20000 });
  evidence.version = browser.version();
  const context = await browser.newContext();
  await context.addInitScript(() => localStorage.setItem("edgeseek.precision", "int8"));
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on("pageerror", error => evidence.errors.push(error.stack || error.message));
  page.on("request", request => {
    if (!request.url().includes("/api/")) return;
    let body;
    try { body = request.postDataJSON(); } catch { /* GET or no JSON */ }
    const documents = Array.isArray(body?.documents) ? body.documents : [body];
    const vectors = documents.flatMap(doc => doc?.chunks?.map(chunk => chunk.embedding) ?? (doc?.embedding ? [doc.embedding] : []));
    evidence.events.push({ kind: "request", method: request.method(), url: request.url(), filename: body?.filename, filenames: body?.documents?.map(doc => doc.filename), mode: body?.mode, modelKey: body?.modelKey, dtype: body?.dtype, vectors: vectors.map(vector => ({ dimension: vector.length, finite: vector.every(Number.isFinite), norm: Math.sqrt(vector.reduce((sum, x) => sum + x*x, 0)), sha256: createHash("sha256").update(JSON.stringify(vector)).digest("hex") })) });
  });
  page.on("response", async response => {
    if (!response.url().includes("/api/")) return;
    try {
      const body = await response.json();
      evidence.events.push({ kind: "response", url: response.url(), status: response.status(), body: /\/api\/kbs(?:\?|$)/.test(response.url()) ? undefined : body });
    } catch { /* navigation may close */ }
  });
  await page.goto("http://127.0.0.1:5174/", { waitUntil: "load" });
  await page.getByText("seekdb 已连接").waitFor();
  await page.getByRole("button", { name: "新建知识库" }).click();
  const kbName = `v21-real-${Date.now()}`;
  await page.locator(".modal-card input").fill(kbName);
  await page.locator(".modal-card").getByRole("button", { name: "创建知识库" }).click();
  await page.getByLabel("切换知识库").selectOption({ label: kbName });
  evidence.kbId = await page.getByLabel("切换知识库").inputValue();
  for (const [name, content] of docs) {
    await page.locator('input[type="file"]').setInputFiles({ name, mimeType: "text/markdown", buffer: Buffer.from(content) });
    await page.getByText("已导入 1 份新文档", { exact: false }).waitFor({ timeout: 120000 });
    await page.getByRole("button", { name: "关闭提示" }).click();
  }
  await page.locator('input[type="file"]').setInputFiles({ name: docs[0][0], mimeType: "text/markdown", buffer: Buffer.from(docs[0][1]) });
  await page.getByText("所选 1 份文档都已导入，未重复计算向量").waitFor();
  evidence.duplicate = "PASS";
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill("How can browser embeddings improve privacy?");
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.locator(".result-card").first().waitFor({ timeout: 60000 });
  evidence.results = await page.locator(".result-card").allTextContents();
  evidence.performance = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]"));
  await page.screenshot({ path: `${evidenceDir}/${channel}-workflow.png`, timeout: 15000 });
  evidence.completed = true;
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  evidence.events = evidence.events.filter(event => !/\/api\/kbs\/[^/]+\//.test(event.url) || (evidence.kbId && event.url.includes(`/api/kbs/${evidence.kbId}/`)));
  evidence.finished = new Date().toISOString();
  await writeFile(`${evidenceDir}/${channel}-workflow.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ completed: evidence.completed, kbId: evidence.kbId, results: evidence.results, errors: evidence.errors }, null, 2));
}
