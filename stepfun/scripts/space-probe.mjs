import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";

const q8 = JSON.parse(await readFile("benchmark/results/v3/quality-int8.json", "utf8"));
const fp32 = JSON.parse(await readFile("benchmark/results/v3/quality-fp32.json", "utf8"));
const evidence = { at: new Date().toISOString(), q8Kb: q8.kbId, fp32Kb: fp32.kbId, errors: [] };
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  let searches = 0;
  page.on("request", request => { if (request.url().endsWith("/search")) searches++; });
  await page.goto("http://127.0.0.1:5174/probe.html");
  await page.evaluate(id => { localStorage.setItem("edgeseek.precision", "fp32"); localStorage.setItem("edgeseek.active-kb", id); }, q8.kbId);
  await page.goto("http://127.0.0.1:5174/");
  await page.getByLabel("切换知识库").selectOption(q8.kbId);
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill("How can browser embeddings improve privacy?");
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.getByRole("alert").getByText(/向量空间不一致/).waitFor({ timeout: 120000 });
  evidence.fp32QueryAgainstQ8Blocked = searches === 0;
  evidence.mismatchMessage = await page.getByRole("alert").innerText();
  await page.getByRole("button", { name: "性能记录" }).click();
  await page.getByLabel("精度").selectOption("int8");
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.locator(".result-card").first().waitFor({ timeout: 120000 });
  evidence.q8QueryWorks = searches === 1;
  evidence.q8Results = await page.locator(".result-source").allTextContents();
  await page.reload();
  await page.waitForFunction(id => document.querySelector('select[aria-label="切换知识库"]')?.value === id, q8.kbId, { timeout: 30000 });
  evidence.refreshRestoredKb = await page.getByLabel("切换知识库").inputValue() === q8.kbId;
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill("How can browser embeddings improve privacy?");
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.locator(".result-card").first().waitFor({ timeout: 120000 });
  evidence.queryAfterRefresh = true;
  await page.getByLabel("切换知识库").selectOption(fp32.kbId);
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.getByRole("alert").getByText(/向量空间不一致/).waitFor({ timeout: 120000 });
  evidence.q8QueryAgainstFp32Blocked = true;
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile("benchmark/results/v3/space-probe.json", JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify(evidence, null, 2));
}
