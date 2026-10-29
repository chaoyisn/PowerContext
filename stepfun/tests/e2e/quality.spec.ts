import { expect, test } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { meanReciprocalRank, recallAtK } from "../../benchmark/quality.mjs";

const corpus = JSON.parse(readFileSync(resolve("benchmark/corpus.json"), "utf8")) as { filename: string; content: string }[];
const queries = JSON.parse(readFileSync(resolve("benchmark/queries.json"), "utf8")) as { id: string; query: string; relevant: string[] }[];

test("browser-local embeddings feed real seekdb results across modes", async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  const externalRequests: string[] = [];
  page.context().on("request", (request) => {
    const url = new URL(request.url());
    if (!/^(localhost|127\.0\.0\.1)$/.test(url.hostname)) externalRequests.push(url.href);
  });
  await page.goto("/");
  await expect(page.getByText("seekdb 已连接")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "新建知识库" }).click();
  const knowledgeBaseName = `quality-${testInfo.project.name}-${Date.now()}`;
  await page.locator(".modal-card input").fill(knowledgeBaseName);
  await page.getByRole("button", { name: "创建知识库" }).click();
  await expect(page.getByText(knowledgeBaseName)).toBeVisible();
  const primaryKbId = await page.getByLabel("切换知识库").inputValue();

  const input = page.locator('input[type="file"]');
  for (const document of corpus) {
    await input.setInputFiles({ name: document.filename, mimeType: "text/markdown", buffer: Buffer.from(document.content) });
    await expect(page.getByText(new RegExp(`已导入 1 份新文档`))).toBeVisible({ timeout: 180_000 });
  }
  const batchCountBeforeDuplicate = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") ?? "[]").filter((row: { name: string }) => row.name === "embedding.batch").length);
  await input.setInputFiles({ name: corpus[0].filename, mimeType: "text/markdown", buffer: Buffer.from(corpus[0].content) });
  await expect(page.getByText("所选 1 份文档都已导入，未重复计算向量")).toBeVisible({ timeout: 30_000 });
  const batchCountAfterDuplicate = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") ?? "[]").filter((row: { name: string }) => row.name === "embedding.batch").length);
  expect(batchCountAfterDuplicate).toBe(batchCountBeforeDuplicate);

  const incremental = { name: "incremental-extra.md", mimeType: "text/markdown", buffer: Buffer.from("incremental visibility check: seekdb refreshes the index after new data is written") };
  await input.setInputFiles(incremental);
  await expect(page.getByText(/已导入 1 份新文档/)).toBeVisible({ timeout: 120_000 });

  await page.getByRole("button", { name: "智能检索" }).click();
  const observations: { queryId: string; mode: string; resultFiles: string[]; recallAt1: number; reciprocalRank: number }[] = [];
  for (const query of queries) {
    for (const [mode, label] of [["hybrid", "混合检索"], ["vector", "向量"], ["fulltext", "全文"]] as const) {
      await page.getByLabel("检索内容").fill(query.query);
      await page.getByRole("tab", { name: label }).click();
      await page.getByRole("button", { name: "开始检索" }).click();
      await expect(page.locator(".result-card").first()).toBeVisible({ timeout: 60_000 });
      const resultFiles = await page.locator(".result-source").allTextContents();
      const rankedFiles = resultFiles.map((value) => corpus.find((doc) => value.includes(doc.filename))?.filename ?? "");
      const relevantRank = rankedFiles.findIndex((filename) => query.relevant.includes(filename)) + 1;
      observations.push({ queryId: query.id, mode, resultFiles, recallAt1: recallAtK(rankedFiles, query.relevant, 1), reciprocalRank: meanReciprocalRank([relevantRank]) });
    }
  }

  await page.getByRole("button", { name: "新建知识库" }).click();
  const isolatedKbName = `isolated-${testInfo.project.name}-${Date.now()}`;
  await page.locator(".modal-card input").fill(isolatedKbName);
  await page.getByRole("button", { name: "创建知识库" }).click();
  const isolatedInput = page.locator('input[type="file"]');
  await isolatedInput.setInputFiles({ name: "isolated.md", mimeType: "text/markdown", buffer: Buffer.from("tenant-only bluejay isolation token: 74f6. This text exists in this knowledge base only.") });
  await expect(page.getByText(/已导入 1 份新文档/)).toBeVisible({ timeout: 120_000 });
  await page.getByLabel("检索内容").fill("bluejay isolation token 74f6");
  await page.getByRole("tab", { name: "混合检索" }).click();
  await page.getByRole("button", { name: "开始检索" }).click();
  await expect(page.locator(".result-card").first()).toBeVisible();
  expect((await page.locator(".result-source").first().innerText()).includes("isolated.md")).toBeTruthy();
  await page.getByLabel("切换知识库").selectOption(primaryKbId);
  await page.getByLabel("检索内容").fill("bluejay isolation token 74f6");
  await page.getByRole("button", { name: "开始检索" }).click();
  await expect(page.getByText(/显示 \d+ 条数据库返回结果|输入查询后/)).toBeVisible({ timeout: 60_000 });
  const primaryResults = await page.locator(".result-source").allTextContents();
  expect(primaryResults.some((value) => value.includes("isolated.md"))).toBeFalsy();

  await page.getByRole("button", { name: "性能记录" }).click();
  await page.getByLabel("精度").selectOption("fp32");
  await page.getByRole("button", { name: "加载并计时" }).click();
  await expect(page.getByText(/WASM · fp32 实测完成/)).toBeVisible({ timeout: 180_000 });
  await page.getByLabel("精度").selectOption("int8");
  await page.getByRole("button", { name: "加载并计时" }).click();
  await expect(page.getByText(/WASM · int8 实测完成/)).toBeVisible({ timeout: 180_000 });

  const inferenceRequests = externalRequests.filter((url) => /api-inference|router\.huggingface\.co|api\.openai\.com|api\.cohere\.ai|api\.voyageai\.com/i.test(url));
  expect(inferenceRequests).toEqual([]);
  expect(externalRequests.some((url) => /huggingface\.co|\.hf\.co/.test(new URL(url).hostname))).toBeTruthy();
  expect(externalRequests.filter((url) => !/(^|\.)huggingface\.co$|(^|\.)hf\.co$/i.test(new URL(url).hostname))).toEqual([]);
  expect(observations.every((row) => row.reciprocalRank > 0)).toBeTruthy();

  const performance = await page.evaluate(() => JSON.parse(localStorage.getItem("edgeseek.performance.v1") ?? "[]"));
  expect(performance.some((row: { name: string; dimension?: number }) => row.name === "embedding.batch" && row.dimension === 384)).toBeTruthy();
  expect(performance.some((row: { name: string }) => row.name === "seekdb.search")).toBeTruthy();
  expect(performance.some((row: { name: string; file?: string; bytes?: number }) => row.name === "model.asset" && row.file?.includes("model.onnx") && Number(row.bytes) > 0)).toBeTruthy();
  expect(performance.some((row: { name: string; file?: string; bytes?: number }) => row.name === "model.asset" && row.file?.includes("model_int8.onnx") && Number(row.bytes) > 0)).toBeTruthy();
  expect(performance.some((row: { name: string; fp32ToInt8Ratio?: number }) => row.name === "model.compression" && Number(row.fp32ToInt8Ratio) > 0)).toBeTruthy();
  const sanitizedRemoteResources = [...new Set(externalRequests.map((value) => { const url = new URL(value); return `${url.origin}${url.pathname}`; }))];
  const actualRun = { at: new Date().toISOString(), browser: testInfo.project.name, model: "Xenova/all-MiniLM-L6-v2", revision: "751bff37182d3f1213fa05d7196b954e230abad9", externalModelResources: sanitizedRemoteResources, inferenceRequests, observations, performance };
  mkdirSync(resolve("benchmark/results"), { recursive: true });
  writeFileSync(resolve(`benchmark/results/${testInfo.project.name}-actual.json`), `${JSON.stringify(actualRun, null, 2)}\n`);
  console.info(JSON.stringify({ browser: testInfo.project.name, externalModelResources: sanitizedRemoteResources, observations, performanceRows: performance.length }));
});
