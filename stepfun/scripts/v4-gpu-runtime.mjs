import { chromium } from "playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";

const qualityDir = process.env.EDGESEEK_QUALITY_DIR || "benchmark/results/v3";
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
await mkdir(outputDir, { recursive: true });
const q8 = JSON.parse(await readFile(`${qualityDir}/quality-int8.json`, "utf8"));
const evidence = { at: new Date().toISOString(), channel: "msedge", headed: true, failureType: "test-only controlled runtime injection; not actual device loss", errors: [] };
let browser;
try {
  browser = await chromium.launch({ channel: "msedge", headless: false, ignoreDefaultArgs: ["--enable-unsafe-swiftshader"] });
  evidence.version = browser.version();
  async function routeWorker(context, condition) {
    await context.route("**/src/embedding-worker.ts?*", async route => {
      const response = await route.fetch();
      const body = await response.text();
      const target = "embeddings.push(...await infer(texts.slice(offset, offset + batchSize)));";
      if (!body.includes(target)) throw new Error("Runtime test injection target missing");
      await route.fulfill({ response, body: body.replace(target, `if (status.backend === "WebGPU" && ${condition}) throw new Error("Controlled GPU inference failure"); ${target}`) });
    });
  }
  const batchContext = await browser.newContext();
  await routeWorker(batchContext, "offset > 0");
  const lab = await batchContext.newPage();
  await lab.goto("http://127.0.0.1:5174/embedding-lab.html");
  await lab.locator("#precision").selectOption("fp16");
  await lab.locator("#run").click();
  const output = await lab.waitForFunction(() => { const t = document.querySelector("#output")?.textContent?.trim(); return t?.startsWith("{") ? t : false; }, null, { timeout: 140000 });
  const data = JSON.parse(await output.jsonValue());
  evidence.midBatch = { backend: data.backend, dtype: data.dtype, reason: data.fallbackReason, vectors: data.vectors, repeatInputL2: data.repeatInputL2, differentInputL2: data.differentInputL2 };
  evidence.midBatch.pass = data.backend === "WASM" && data.dtype === "q8" && data.fallbackReason === "Controlled GPU inference failure" && data.vectors?.every(row => row.dimension === 384 && row.finite) && data.repeatInputL2 < 1e-5;
  await lab.screenshot({ path: `${outputDir}/gpu-runtime.png`, timeout: 5000 }).catch(error => { evidence.screenshotError = String(error); });
  await batchContext.close();

  const context = await browser.newContext();
  await routeWorker(context, 'texts[0].includes("runtime failure probe")');
  await context.addInitScript(() => localStorage.setItem("edgeseek.precision", "fp16"));
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  let searchRequests = 0;
  page.on("request", request => { if (request.url().endsWith("/search")) searchRequests++; });
  await page.goto("http://127.0.0.1:5174/");
  await page.getByText("seekdb 已连接").waitFor();
  await page.getByRole("button", { name: "新建知识库" }).click();
  const name = `v4-gpu-failure-${Date.now()}`;
  await page.locator(".modal-card input").fill(name);
  await page.locator(".modal-card").getByRole("button", { name: "创建知识库" }).click();
  await page.getByRole("status").getByText(`已创建知识库「${name}」`).waitFor({ timeout: 120000 });
  evidence.fp16Kb = await page.getByLabel("切换知识库").inputValue();
  await page.locator('input[type="file"]').setInputFiles({ name: "gpu-source.md", mimeType: "text/markdown", buffer: Buffer.from("Local browser embeddings protect private documents and support semantic search.") });
  await page.getByText("已导入 1 份新文档", { exact: false }).waitFor({ timeout: 120000 });
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill("runtime failure probe: how does browser embedding protect privacy?");
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.getByRole("alert").getByText(/向量空间不一致/).waitFor({ timeout: 120000 });
  evidence.mismatch = { error: await page.getByRole("alert").innerText(), noSearchSent: searchRequests === 0, actualBackend: await page.locator(".model-pill").innerText() };
  await page.screenshot({ path: `${outputDir}/gpu-mismatch.png`, timeout: 5000 }).catch(error => { evidence.uiScreenshotError = String(error); });
  await page.getByRole("button", { name: "性能记录" }).click();
  await page.getByText("Controlled GPU inference failure").waitFor();
  evidence.mismatch.displayedFallbackReason = await page.locator(".fallback-note").innerText();
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("切换知识库").selectOption(q8.kbId);
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.locator(".result-card").first().waitFor({ timeout: 120000 });
  evidence.q8CollectionRecovery = { searchRequests, results: await page.locator(".result-source").allTextContents() };
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile(`${outputDir}/gpu-runtime.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify(evidence, null, 2));
}
