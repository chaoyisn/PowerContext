import { chromium } from "playwright";
import { writeFile } from "node:fs/promises";

const evidence = { at: new Date().toISOString(), headed: true, channel: "msedge", console: [], network: [], errors: [] };
let browser;
try {
  browser = await chromium.launch({ channel: "msedge", headless: false, timeout: 20000, ignoreDefaultArgs: ["--enable-unsafe-swiftshader"] });
  evidence.version = browser.version();
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("console", msg => evidence.console.push({ type: msg.type(), text: msg.text() }));
  page.on("pageerror", error => evidence.errors.push(error.stack || error.message));
  page.on("response", response => evidence.network.push({ url: response.url(), status: response.status() }));
  await page.goto("http://127.0.0.1:5174/embedding-lab.html", { waitUntil: "load", timeout: 30000 });
  evidence.gpu = await page.evaluate(async () => {
    if (!navigator.gpu) return { available: false, reason: "navigator.gpu unavailable" };
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) return { available: false, reason: "requestAdapter returned null" };
    const info = adapter.info ? { vendor: adapter.info.vendor, architecture: adapter.info.architecture, device: adapter.info.device, description: adapter.info.description, isFallbackAdapter: adapter.info.isFallbackAdapter } : null;
    const features = [...adapter.features];
    const device = await adapter.requestDevice();
    device.destroy();
    return { available: true, info, features, shaderF16: features.includes("shader-f16") };
  });
  await page.locator("#precision").selectOption("auto");
  await page.locator("#run").click();
  await page.waitForFunction(() => document.querySelector("#output")?.textContent?.trim().startsWith("{"), null, { timeout: 140000 });
  evidence.lab = JSON.parse(await page.locator("#output").textContent());
  await page.screenshot({ path: "benchmark/results/v3/edge-gpu.png", timeout: 15000 });
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile("benchmark/results/v3/edge-gpu.json", JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ version: evidence.version, gpu: evidence.gpu, backend: evidence.lab?.backend, dtype: evidence.lab?.dtype, fallbackReason: evidence.lab?.fallbackReason, errors: evidence.errors }, null, 2));
}
