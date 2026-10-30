import assert from "node:assert/strict";
import test from "node:test";
import { FulltextIndexConfig, Schema, SeekdbClient, VectorIndexConfig } from "seekdb";
import { loadEnv } from "../../server/env.mjs";

loadEnv();

test("seekdb-js writes, reads, refreshes, and runs hybrid search in seekdb", async () => {
  const client = new SeekdbClient({
    host: process.env.SEEKDB_HOST ?? "127.0.0.1",
    port: Number(process.env.SEEKDB_PORT ?? 2882),
    user: process.env.SEEKDB_USER ?? "root",
    password: process.env.SEEKDB_PASSWORD ?? "",
    database: process.env.SEEKDB_DATABASE ?? "test",
  });
  const internal = client._delegate._internal;
  const execute = internal.execute.bind(internal);
  const sql = [];
  internal.execute = async (statement, params) => {
    if (String(statement).includes("DBMS_HYBRID_SEARCH")) sql.push(String(statement).replace(/\s+/g, " ").trim());
    return execute(statement, params);
  };

  try {
    const name = "edgeseek_it_external_vectors";
    let collection;
    try {
      collection = await client.getCollection({ name, embeddingFunction: null });
    } catch {
      collection = await client.createCollection({
        name,
        embeddingFunction: null,
        schema: new Schema({
          fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
          vectorIndex: new VectorIndexConfig({ hnsw: { dimension: 4, distance: "cosine" }, embeddingFunction: null }),
        }),
      });
    }
    assert.equal(collection.schema?.vectorIndex?.embeddingFunction, null);
    await collection.upsert({
      ids: ["edgeseek-it-hit", "edgeseek-it-other"],
      documents: ["seekdb server hybrid vector and full text search", "an unrelated storage note"],
      embeddings: [[1, 0, 0, 0], [0, 1, 0, 0]],
      metadatas: [{ filename: "hybrid.md", chunkIndex: 0 }, { filename: "other.md", chunkIndex: 0 }],
    });
    await collection.refresh_index();
    const readback = await collection.get({ ids: ["edgeseek-it-hit"], include: ["documents", "embeddings", "metadatas"] });
    assert.deepEqual(readback.ids, ["edgeseek-it-hit"]);
    assert.deepEqual(readback.embeddings?.[0], [1, 0, 0, 0]);
    assert.match(readback.documents?.[0] ?? "", /seekdb/);

    const result = await collection.hybridSearch({
      query: { whereDocument: { $contains: "seekdb hybrid" } },
      knn: { queryEmbeddings: [1, 0, 0, 0] },
      rank: { rrf: { rankWindowSize: 20, rankConstant: 60 } },
      nResults: 5,
      include: ["documents", "metadatas", "distances"],
    });
    const ids = Array.isArray(result.ids?.[0]) ? result.ids[0] : result.ids;
    assert.ok(ids?.includes("edgeseek-it-hit"));
    assert.ok(sql.some((statement) => statement.includes("DBMS_HYBRID_SEARCH.GET_SQL")));
    console.info(JSON.stringify({ test: "real-seekdb-hybrid", sdk: "seekdb@1.4.0", readbackVector: readback.embeddings[0], resultIds: ids, seekdbSql: sql }));
  } finally {
    await client.close();
  }
});
