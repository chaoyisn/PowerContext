import { FulltextIndexConfig, Schema, SeekdbClient, VectorIndexConfig } from "seekdb";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));

const client = new SeekdbClient({
  host: process.env.SEEKDB_HOST ?? "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT ?? 2882),
  user: process.env.SEEKDB_USER ?? "root",
  password: process.env.SEEKDB_PASSWORD ?? "",
  database: process.env.SEEKDB_DATABASE ?? "test",
});
console.log("[P0] seekdb client constructed");
const internalClient = client._delegate._internal;
const execute = internalClient.execute.bind(internalClient);
const sqlEvidence = [];
internalClient.execute = async (sql, params) => {
  if (String(sql).includes("DBMS_HYBRID_SEARCH")) sqlEvidence.push(String(sql).replace(/\s+/g, " ").trim());
  return execute(sql, params);
};

try {
  let collection;
  try {
    console.log("[P0] loading existing collection");
    collection = await client.getCollection({ name: "edgeseek_p0_external_vectors", embeddingFunction: null });
  } catch {
    console.log("[P0] creating collection");
    collection = await client.createCollection({
      name: "edgeseek_p0_external_vectors",
      embeddingFunction: null,
      schema: new Schema({
        fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
        vectorIndex: new VectorIndexConfig({
          hnsw: { dimension: 4, distance: "cosine" },
          embeddingFunction: null,
        }),
      }),
    });
  }

  console.log("[P0] upserting external vectors");
  await collection.upsert({
    ids: ["p0-seekdb-hit", "p0-other"],
    documents: [
      "seekdb combines OceanBase vector data and full text search",
      "A separate note about unrelated storage systems",
    ],
    embeddings: [[1, 0, 0, 0], [0, 1, 0, 0]],
    metadatas: [{ source: "p0", chunk: 0 }, { source: "p0", chunk: 1 }],
  });

  console.log("[P0] reading vector back");
  const readback = await collection.get({ ids: ["p0-seekdb-hit"], include: ["documents", "metadatas", "embeddings"] });
  console.log("[P0] running seekdb hybridSearch");
  const result = await collection.hybridSearch({
    query: { whereDocument: { $contains: "seekdb" } },
    knn: { queryEmbeddings: [1, 0, 0, 0] },
    rank: { rrf: { rankWindowSize: 20, rankConstant: 60 } },
    nResults: 5,
    include: ["documents", "metadatas", "distances"],
  });

  const vector = readback.embeddings?.[0];
  const ids = Array.isArray(result.ids?.[0]) ? result.ids[0] : result.ids ?? [];
  const evidence = {
    sdk: "seekdb@1.4.0",
    embeddingFunctionDisabled: collection.schema?.vectorIndex?.embeddingFunction === null,
    readback: {
      ids: readback.ids,
      document: readback.documents?.[0],
      vector: vector,
      metadata: readback.metadatas?.[0],
    },
    hybrid: {
      ids,
      documents: result.documents?.[0],
      distances: result.distances?.[0],
    },
    seekdbSqlPath: sqlEvidence,
  };
  const resultsDirectory = resolve(root, "benchmark/results");
  const evidencePath = resolve(resultsDirectory, "seekdb-p0-actual.json");
  mkdirSync(resultsDirectory, { recursive: true });
  writeFileSync(evidencePath, `${JSON.stringify({ measuredAt: new Date().toISOString(), source: "real seekdb server; 4D SDK fixture vectors", ...evidence }, null, 2)}\n`);
  console.log(JSON.stringify(evidence, null, 2));

  if (!Array.isArray(vector) || vector.length !== 4 || ids[0] !== "p0-seekdb-hit") process.exitCode = 1;
  if (!sqlEvidence.some((sql) => sql.includes("DBMS_HYBRID_SEARCH.GET_SQL"))) process.exitCode = 1;
} finally {
  await client.close();
}
