import { chromium } from "playwright";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { performance } from "node:perf_hooks";

const runFile = promisify(execFile);
const precision = process.argv[2] || "int8";
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
await mkdir(outputDir, { recursive: true });
const gpu = precision === "fp16";
const qualityDir = process.env.EDGESEEK_QUALITY_DIR || "benchmark/results/v3";
const source = JSON.parse(await readFile(`${qualityDir}/quality-${precision}.json`, "utf8"));
const evidence = { at: new Date().toISOString(), precision, kbId: source.kbId, query: "How can local browser processing protect private documents?", samples: [], errors: [], note: "Browser and server timestamps use the same host system clock; outbound and inbound spans include scheduling, proxy and parsing, and may be affected by clock precision. Timing spans can overlap." };
const suffix = process.env.EDGESEEK_PERF_SUFFIX || "";
let browser;
try {
  const { stdout } = await runFile("powershell.exe", ["-NoProfile", "-Command", "(Get-NetTCPConnection -LocalPort 4174 -State Listen).OwningProcess"], { windowsHide: true, timeout: 10000 });
  evidence.apiPid = Number(stdout.trim());
  browser = await chromium.launch({ channel: gpu ? "msedge" : "chrome", headless: !gpu, timeout: 20000, ...(gpu ? { ignoreDefaultArgs: ["--enable-unsafe-swiftshader"] } : {}) });
  evidence.browserVersion = browser.version(); evidence.headed = gpu;
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  await page.goto("http://127.0.0.1:5174/probe.html");
  await page.evaluate(({ id, precision }) => { localStorage.setItem("edgeseek.active-kb", id); localStorage.setItem("edgeseek.precision", precision); }, { id: source.kbId, precision });
  await page.goto("http://127.0.0.1:5174/");
  await page.getByLabel("切换知识库").selectOption(source.kbId);
  await page.getByRole("button", { name: "智能检索" }).click();
  await page.getByLabel("检索内容").fill(evidence.query);
  async function run(index) {
    const before = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]").length);
    const start = performance.now();
    const [response] = await Promise.all([page.waitForResponse(r => r.url().endsWith("/search") && r.request().method() === "POST", { timeout: 120000 }), page.getByRole("button", { name: "开始检索" }).click()]);
    const body = await response.json();
    if (!response.ok()) throw new Error(`Search failed ${response.status()}: ${JSON.stringify(body)}`);
    await page.locator(".result-card").first().waitFor({ timeout: 30000 });
    const visibleMs = performance.now() - start;
    await page.waitForFunction(n => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]").slice(n).some(row => row.name === "query.end-to-end"), before);
    const rows = await page.evaluate(n => JSON.parse(localStorage.getItem("edgeseek.performance.v1") || "[]").slice(n), before);
    const get = name => rows.find(row => row.name === name);
    const timing = response.request().timing();
    const { stdout: rss } = await runFile("powershell.exe", ["-NoProfile", "-Command", `(Get-Process -Id ${evidence.apiPid}).WorkingSet64`], { windowsHide: true, timeout: 10000 });
    const search = get("seekdb.search");
    return { index, status: response.status(), backend: get("query.embedding")?.backend, dtype: get("query.embedding")?.dtype, workerQueueMs: get("worker.queue")?.durationMs, embeddingMs: get("query.embedding")?.durationMs, apiDbMs: body.dbMs, apiRoundTripMs: (search?.networkMs ?? 0) + body.dbMs, outboundMs: search?.outboundMs, serverMs: search?.serverMs, inboundHeadersMs: search?.inboundHeadersMs, inboundBodyParsedMs: search?.inboundBodyParsedMs, requestTiming: timing, responseTransferMs: timing.responseEnd >= 0 ? timing.responseEnd - timing.responseStart : null, pageVisibleMs: visibleMs, browserEndToEndMs: get("query.end-to-end")?.durationMs, resultIds: body.results.map(row => row.id), apiNodeWorkingSetBytes: Number(rss.trim()) };
  }
  evidence.warmup = await run(0);
  for (let i = 1; i <= 5; i++) evidence.samples.push(await run(i));
  await context.close();
} catch (error) { evidence.errors.push(error.stack || String(error)); }
finally {
  if (browser) await browser.close().catch(() => {});
  await writeFile(`${outputDir}/query-perf-${precision}${suffix}.json`, JSON.stringify(evidence, null, 2) + "\n");
  console.log(JSON.stringify({ precision, samples: evidence.samples, errors: evidence.errors }, null, 2));
}
