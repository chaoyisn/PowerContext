import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";

const evidence = { at: new Date().toISOString(), kind: "test-only uncaught Worker initialization failure", errors: [] };
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
await mkdir(outputDir, { recursive: true });
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext();
  await context.addInitScript(() => localStorage.setItem("edgeseek.precision", "int8"));
  const pattern = "**/src/embedding-worker.ts?*";
  await context.route(pattern, async route => {
    const response = await route.fetch();
    await route.fulfill({ response, body: `${await response.text()}\nthrow new Error("Controlled Worker crash");\n` });
  });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:5174/");
  await page.getByRole("button", { name: "加载模型" }).click();
  await page.getByRole("alert").waitFor({ timeout: 30000 });
  evidence.errorShown = await page.getByRole("alert").innerText();
  evidence.fakeSuccess = (await page.locator(".model-pill").innerText()).includes("WASM");
  await context.unroute(pattern);
  await page.getByRole("button", { name: "加载模型" }).click();
  await page.getByText("浏览器模型已就绪").waitFor({ timeout: 120000 });
  evidence.retryBackend = await page.locator(".model-pill").innerText();
  evidence.retryPass = /WASM.*q8/.test(evidence.retryBackend);
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile(`${outputDir}/worker-fault.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify(evidence, null, 2));
}
