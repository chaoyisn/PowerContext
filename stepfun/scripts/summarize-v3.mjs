import { readFile, writeFile } from "node:fs/promises";

const read = async path => JSON.parse(await readFile(path, "utf8"));
const quality = {};
for (const precision of ["fp32", "int8", "fp16"]) {
  const run = await read(`benchmark/results/v3/quality-${precision}.json`);
  quality[precision] = {};
  for (const mode of ["vector", "hybrid"]) {
    const cases = run.cases.filter(row => row.mode === mode);
    const mean = key => cases.reduce((sum, row) => sum + row[key], 0) / cases.length;
    quality[precision][mode] = { queries: cases.length, recall5: mean("recall5"), recall10: mean("recall10"), ndcg10: mean("ndcg10") };
  }
}
const batch = await read("benchmark/results/v3/batch-q8.json");
const batches = [1, 4, 8, 16].map(size => {
  const rows = batch.samples.filter(row => row.batchSize === size);
  const sorted = rows.map(row => row.elapsedMs).sort((a, b) => a - b);
  return { batchSize: size, runs: rows.length, medianMs: sorted[Math.floor(sorted.length / 2)], medianItemsPerSecond: 16000 / sorted[Math.floor(sorted.length / 2)] };
});
const strategies = await read("benchmark/results/v3/index-strategies.json");
const deferred = await read("benchmark/results/v3/index-deferred.json");
const indexStrategies = [...strategies.samples, ...deferred.samples].reduce((acc, row) => {
  (acc[row.strategy] ??= []).push(row.writeAndRefreshMs);
  return acc;
}, {});
for (const [strategy, values] of Object.entries(indexStrategies)) {
  values.sort((a, b) => a - b);
  indexStrategies[strategy] = { samples: values.length, medianMs: values[Math.floor(values.length / 2)] };
}
const result = { quality, batches, indexStrategies, caveats: ["Seven candidates; Recall@10 cannot discriminate configurations.", "Batch groups were measured in fixed order on one device; browser peak memory unavailable.", "Index strategy timings exclude collection creation, API and browser network overhead."] };
await writeFile("benchmark/results/v3/summary.json", JSON.stringify(result, null, 2) + "\n");
console.log(JSON.stringify(result, null, 2));
