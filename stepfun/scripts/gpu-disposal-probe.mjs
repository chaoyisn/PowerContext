import { chromium } from "playwright";
import { writeFile } from "node:fs/promises";

const evidence = { at: new Date().toISOString(), headed: true, testOnlyInjection: "throw immediately after successful WebGPU pipeline load", errors: [], network: [] };
let browser;
try {
  browser = await chromium.launch({ channel: "msedge", headless: false, ignoreDefaultArgs: ["--enable-unsafe-swiftshader"], timeout: 20000 });
  evidence.version = browser.version();
  const context = await browser.newContext();
  await context.route("**/src/embedding-worker.ts?*", async route => {
    const response = await route.fetch();
    const body = await response.text();
    const target = 'await load("webgpu", "fp16", requestId);';
    if (!body.includes(target)) throw new Error("WebGPU test injection target missing");
    await route.fulfill({ response, body: body.replace(target, `${target} throw new Error("Simulated failure after GPU model load");`) });
  });
  const page = await context.newPage();
  page.on("response", response => evidence.network.push({ url: response.url(), status: response.status() }));
  await page.goto("http://127.0.0.1:5174/embedding-lab.html");
  await page.locator("#precision").selectOption("auto");
  await page.locator("#run").click();
  const output = await page.waitForFunction(() => { const value = document.querySelector("#output")?.textContent?.trim(); return value?.startsWith("{") ? value : false; }, null, { timeout: 140000 });
  const lab = JSON.parse(await output.jsonValue());
  evidence.result = { backend: lab.backend, dtype: lab.dtype, fallbackReason: lab.fallbackReason, vectors: lab.vectors, differentInputL2: lab.differentInputL2, repeatInputL2: lab.repeatInputL2 };
  evidence.gpuWeightRequested = evidence.network.some(row => row.status === 200 && row.url.includes("model_fp16.onnx"));
  evidence.pass = evidence.gpuWeightRequested && lab.backend === "WASM" && lab.dtype === "q8" && lab.fallbackReason === "Simulated failure after GPU model load" && lab.vectors?.every(v => v.dimension === 384 && v.finite);
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile("benchmark/results/v3/gpu-disposal.json", JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ pass: evidence.pass, gpuWeightRequested: evidence.gpuWeightRequested, result: evidence.result, errors: evidence.errors }, null, 2));
}
