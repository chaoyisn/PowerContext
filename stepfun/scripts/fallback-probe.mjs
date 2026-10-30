import { chromium } from "playwright";
import { writeFile } from "node:fs/promises";

const evidence = { at: new Date().toISOString(), testOnlyInjection: true, cases: [] };
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true, timeout: 20000 });
  for (const mode of ["unavailable", "initialization-failure"]) {
    const item = { mode, errors: [] };
    evidence.cases.push(item);
    const context = await browser.newContext();
    try {
      await context.route("**/src/embedding-worker.ts?*", async route => {
        const response = await route.fetch();
        const body = await response.text();
        const original = "await self.navigator.gpu?.requestAdapter()";
        if (!body.includes(original)) throw new Error("Test injection target missing from worker");
        const replacement = mode === "unavailable" ? "null" : "await Promise.reject(new Error('Simulated WebGPU initialization failure'))";
        await route.fulfill({ response, body: body.replace(original, replacement) });
      });
      const page = await context.newPage();
      await page.goto("http://127.0.0.1:5174/embedding-lab.html", { waitUntil: "load" });
      await page.locator("#precision").selectOption("auto");
      await page.locator("#run").click();
      await page.waitForFunction(() => document.querySelector("#output")?.textContent?.trim().startsWith("{"), null, { timeout: 140000 });
      const lab = JSON.parse(await page.locator("#output").textContent());
      item.result = { backend: lab.backend, dtype: lab.dtype, fallbackReason: lab.fallbackReason, vectors: lab.vectors, differentInputL2: lab.differentInputL2, repeatInputL2: lab.repeatInputL2, initMs: lab.initMs, inferenceMs: lab.inferenceMs };
      item.pass = lab.backend === "WASM" && lab.dtype === "q8" && lab.vectors?.every(v => v.dimension === 384 && v.finite) && lab.differentInputL2 > 0 && lab.repeatInputL2 < 1e-5;
    } catch (error) { item.errors.push(error.stack || String(error)); }
    finally { await context.close(); }
  }
} catch (error) { evidence.error = error.stack || String(error); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile("benchmark/results/v3/fallback.json", JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify(evidence, null, 2));
}
