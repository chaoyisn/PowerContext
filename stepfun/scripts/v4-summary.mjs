import { readFile, writeFile } from "node:fs/promises";
const outputDir = process.env.EDGESEEK_V4_OUTPUT_DIR || "benchmark/results/v4";
const read = async name => JSON.parse(await readFile(`${outputDir}/${name}.json`, "utf8"));
const stats = values => {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  return { n: sorted.length, median: sorted.length ? sorted[Math.floor(sorted.length / 2)] : null, p95: sorted.length ? sorted[Math.ceil(sorted.length * 0.95) - 1] : null, max: sorted.at(-1) ?? null };
};
const summary = { at: new Date().toISOString(), quality: {}, model: {}, queries: {}, import: {}, notes: ["Five-sample P95 uses nearest rank and equals the maximum.", "Fresh isolated contexts begin with empty CacheStorage; separate cache proofs block model HTTP requests and verify a new Worker can still infer.", "Model acquisition is local HTTP; timing spans may overlap. Browser/server timing uses the same host clock and includes scheduling, proxy, and parsing.", "Browser memory is sampled sum of process working sets, with shared pages counted repeatedly; API memory is sampled working set, and GPU memory is UNKNOWN."] };
for (const precision of ["fp32", "int8", "fp16"]) {
  const quality = await read(`quality-${precision}`);
  summary.quality[precision] = {};
  for (const mode of ["vector", "hybrid"]) for (const language of ["all", "en", "zh", "cross"]) {
    const cases = quality.cases.filter(row => row.mode === mode && (language === "all" || row.language === language));
    summary.quality[precision][`${mode}-${language}`] = Object.fromEntries(["recall1", "recall5", "recall10", "mrr10", "ndcg10"].map(key => [key, cases.reduce((sum, row) => sum + row[key], 0) / cases.length]));
  }
  const model = await read(`model-perf-${precision}`);
  const weight = { int8: "onnx/model_quantized.onnx", fp32: "onnx/model.onnx", fp16: "onnx/model_fp16.onnx" }[precision];
  const phases = run => {
    const start = run.events.find(row => row.file === weight && row.status === "download")?.atMs;
    const done = run.events.find(row => row.file === weight && row.status === "done")?.atMs;
    return { weightReadMs: done - start, pipelineReadyMs: run.events.find(row => row.phase === "model-ready")?.atMs, firstInferenceMs: run.events.find(row => row.phase === "first-inference")?.elapsedMs, totalInitMs: run.initWallMs };
  };
  const cacheProof = await read(`cache-proof-${precision}`);
  summary.model[precision] = { actual: `${model.cold.state.backend}/${model.cold.state.dtype}`, cold: phases(model.cold), warmNewWorker: phases(model.warm), warmInference: stats(model.warm.subsequentInferenceMs), cacheBefore: model.cacheBefore, cacheAfterCold: model.cacheAfterCold, cacheProofPass: cacheProof.pass, sampledBrowserWorkingSetPeak: model.memorySummary.sampledPeakBytes, batch: Object.fromEntries([1, 4, 8, 16].map(size => [size, stats(model.samples.filter(row => row.batchSize === size).map(row => row.itemsPerSecond))])) };
  const query = await read(`query-perf-${precision}-instrumented`);
  summary.queries[precision] = Object.fromEntries(["workerQueueMs", "embeddingMs", "outboundMs", "serverMs", "inboundHeadersMs", "inboundBodyParsedMs", "apiDbMs", "apiRoundTripMs", "responseTransferMs", "pageVisibleMs", "browserEndToEndMs", "apiNodeWorkingSetBytes"].map(field => [field, stats(query.samples.map(row => row[field]))]));
}
const imports = await read("import-perf");
for (const strategy of ["single", "batch", "incremental"]) {
  const samples = imports.samples.filter(row => row.strategy === strategy);
  summary.import[strategy] = { allVisible: samples.every(row => row.verification.every(item => item.found)), ...Object.fromEntries(["importVisibleMs", "embeddingMs", "apiRoundTripMs", "dbWriteMs", "refreshMs", "visibilityMs"].map(field => [field, stats(samples.map(row => row[field]))])) };
}
const gpu = await read("gpu-stability");
summary.gpuStability = { samples: gpu.samples.length, maxL2: gpu.maxL2, minCosine: gpu.minCosine, rankingIdentical: gpu.rankingIdentical };
await writeFile(`${outputDir}/summary.json`, JSON.stringify(summary, null, 2) + "\n");
console.log(JSON.stringify(summary, null, 2));
