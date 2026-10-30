import { chromium } from "playwright";
import { writeFile } from "node:fs/promises";

const channel = process.argv[2] || "msedge";
const result = { channel, started: new Date().toISOString(), layers: {}, console: [], errors: [], network: [] };
let browser;
try {
  browser = await chromium.launch({ channel, headless: true, timeout: 20000 });
  result.version = browser.version();
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("console", msg => result.console.push({ type: msg.type(), text: msg.text() }));
  page.on("pageerror", error => result.errors.push({ stage: "pageerror", message: error.stack || error.message }));
  page.on("requestfailed", request => result.network.push({ url: request.url(), failure: request.failure() }));
  page.on("response", response => result.network.push({ url: response.url(), status: response.status(), contentType: response.headers()["content-type"], contentLength: response.headers()["content-length"] }));
  page.setDefaultTimeout(20000);
  await page.goto("http://127.0.0.1:5174/probe.html", { waitUntil: "load", timeout: 20000 });
  result.layers.L0 = { status: (await page.textContent("body")).includes("static page reachable") ? "PASS" : "FAIL", url: page.url() };
  await page.goto("http://127.0.0.1:5174/embedding-lab.html", { waitUntil: "load", timeout: 20000 });
  result.layers.L1 = { status: await page.title() === "EdgeSeek V2 · Browser Embedding Lab" ? "PASS" : "FAIL", url: page.url() };
  const workerResult = await page.evaluate(() => new Promise((resolve, reject) => {
    const url = URL.createObjectURL(new Blob(["onmessage = e => postMessage(e.data + 1)"], { type: "text/javascript" }));
    const worker = new Worker(url);
    worker.onmessage = event => { worker.terminate(); URL.revokeObjectURL(url); resolve(event.data); };
    worker.onerror = reject;
    worker.postMessage(41);
  }));
  result.layers.L2 = { status: workerResult === 42 ? "PASS" : "FAIL", reply: workerResult };
  await page.locator("#text-a").fill("The database supports vector search.");
  await page.locator("#text-b").fill("Browser-side embeddings can improve privacy.");
  await page.locator("#run").click();
  await page.waitForFunction(() => document.querySelector("#output")?.textContent?.trim().startsWith("{"), null, { timeout: 140000 });
  result.lab = JSON.parse(await page.locator("#output").textContent());
  result.layers.L3 = { status: result.lab.backend === "WASM" && result.lab.dtype === "q8" ? "PASS" : "BLOCKED", note: "PASS requires actual WASM model initialization and inference" };
  await page.screenshot({ path: `benchmark/results/v2/${channel}-lab.png`, timeout: 15000 });
  await context.close();
} catch (error) {
  result.errors.push({ stage: "launch-or-layer", message: error.stack || String(error) });
} finally {
  if (browser) await browser.close().catch(error => result.errors.push({ stage: "close", message: String(error) }));
  result.finished = new Date().toISOString();
  for (const layer of ["L0", "L1", "L2", "L3"]) result.layers[layer] ||= { status: "BLOCKED" };
  await writeFile(`benchmark/results/v2/${channel}-probe.json`, JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify({ channel, version: result.version, layers: result.layers, errors: result.errors }, null, 2));
}
