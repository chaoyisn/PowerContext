import { chromium } from "playwright";
import { readFile, writeFile } from "node:fs/promises";

const previous = JSON.parse(await readFile("benchmark/results/v3/chrome-workflow.json", "utf8"));
const other = JSON.parse(await readFile("benchmark/results/v3/quality-int8.json", "utf8"));
const result = { at: new Date().toISOString(), kbId: previous.kbId, errors: [] };
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:5174/probe.html");
  await page.evaluate(id => { localStorage.setItem("edgeseek.precision", "int8"); localStorage.setItem("edgeseek.active-kb", id); }, previous.kbId);
  await page.goto("http://127.0.0.1:5174/");
  await page.getByLabel("切换知识库").selectOption(previous.kbId);
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill("How can browser embeddings improve privacy?");
  await page.getByRole("button", { name: "开始检索" }).click();
  await page.locator(".result-card").first().waitFor({ timeout: 120000 });
  result.results = await page.locator(".result-card").allTextContents();
  result.pass = result.results.some(row => row.includes("privacy.md"));
  await page.getByLabel("切换知识库").selectOption(other.kbId);
  await page.getByLabel("检索内容").fill("garden tomatoes");
  let [response] = await Promise.all([page.waitForResponse(r => r.url().endsWith("/search") && r.request().method() === "POST"), page.getByRole("button", { name: "开始检索" }).click()]);
  let rows = (await response.json()).results;
  result.otherKbHasGarden = rows.some(row => row.metadata.filename === "garden.md");
  await page.getByLabel("切换知识库").selectOption(previous.kbId);
  [response] = await Promise.all([page.waitForResponse(r => r.url().endsWith("/search") && r.request().method() === "POST"), page.getByRole("button", { name: "开始检索" }).click()]);
  rows = (await response.json()).results;
  result.originalKbExcludesGarden = rows.every(row => row.metadata.filename !== "garden.md");
  await context.close();
} catch (error) { result.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile("benchmark/results/v3/restart-probe.json", JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify(result, null, 2));
}
