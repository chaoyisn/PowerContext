import { createHash, randomUUID } from "node:crypto";
import { performance } from "node:perf_hooks";
import { FulltextIndexConfig, Schema, SeekdbClient, VectorIndexConfig } from "seekdb";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { AsyncLocalStorage } from "node:async_hooks";
import { embeddingSpace } from "../frontend/src/embedding-space.mjs";

const model = JSON.parse(readFileSync(fileURLToPath(new URL("../model.json", import.meta.url)), "utf8"));
const client = new SeekdbClient({
  host: process.env.SEEKDB_HOST ?? "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT ?? 2882),
  user: process.env.SEEKDB_USER ?? "root",
  password: process.env.SEEKDB_PASSWORD ?? "",
  database: process.env.SEEKDB_DATABASE ?? "test",
});
const tracing = new AsyncLocalStorage();
if (process.env.EDGESEEK_TRACE_SQL === "1") {
  const internal = client._delegate._internal;
  const execute = internal.execute.bind(internal);
  const digest = value => createHash("sha256").update(String(value)).digest("hex");
  const redact = sql => String(sql).replace(/\[(?:\s*[-+\d.eE]+\s*,?){20,}\]/g, "[VECTOR_REDACTED]");
  internal.execute = async (statement, params) => {
    const trace = tracing.getStore();
    if (!trace) return execute(statement, params);
    const start = performance.now();
    const rows = await execute(statement, params);
    const generated = String(statement).includes("DBMS_HYBRID_SEARCH.GET_SQL") ? rows?.[0]?.query_sql : null;
    trace.push({ sql: redact(statement), sqlSha256: digest(statement), paramCount: params?.length ?? 0,
      paramsSha256: params ? digest(JSON.stringify(params)) : null, elapsedMs: performance.now() - start,
      rowCount: rows?.length ?? 0, generatedSql: generated ? redact(String(generated).trim().replace(/^['"]|['"]$/g, "")) : undefined,
      generatedSqlSha256: generated ? digest(String(generated).trim().replace(/^['"]|['"]$/g, "")) : undefined,
      rows: generated ? undefined : (rows ?? []).map(row => Object.fromEntries(Object.entries(row).filter(([key]) => /^(_?id|document|metadata|_score|score|distance|_distance)$/i.test(key)))) });
    return rows;
  };
}

export async function initializeDatabase() {
  await client.execute(`CREATE TABLE IF NOT EXISTS edgeseek_kbs (
    id CHAR(32) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    model_key VARCHAR(512) NOT NULL,
    dimension INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )`);
  await client.execute(`CREATE TABLE IF NOT EXISTS edgeseek_documents (
    id CHAR(64) PRIMARY KEY,
    kb_id CHAR(32) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    content LONGTEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    chunk_count INT NOT NULL,
    status VARCHAR(24) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY edgeseek_kb_sha (kb_id, sha256)
  )`);
  console.info(JSON.stringify({ event: "seekdb.ready", sdk: "seekdb@1.4.0", database: process.env.SEEKDB_DATABASE ?? "test" }));
}

export async function health() {
  const rows = await client.execute("SELECT 1 AS ready");
  return { ok: Number(rows?.[0]?.ready) === 1, sdk: "seekdb@1.4.0", database: process.env.SEEKDB_DATABASE ?? "test" };
}

export async function listKnowledgeBases() {
  const rows = await client.execute(`SELECT k.id, k.name, k.model_key, k.dimension, k.created_at,
    (SELECT COUNT(*) FROM edgeseek_documents d WHERE d.kb_id = k.id AND d.status = 'imported') AS document_count
    FROM edgeseek_kbs k ORDER BY k.created_at DESC`);
  return (rows ?? []).map(toKnowledgeBase);
}

export async function createKnowledgeBase(name, modelKey) {
  const cleanName = String(name ?? "").trim().slice(0, 255);
  if (!cleanName) throw new HttpError(400, "请输入知识库名称");
  if (![embeddingSpace(model.modelKey, model.revision, "WASM", "q8"), embeddingSpace(model.modelKey, model.revision, "WASM", "fp32"), embeddingSpace(model.modelKey, model.revision, "WebGPU", "fp16")].includes(modelKey)) throw new HttpError(409, "知识库需要明确的模型精度与后端配置");
  const id = randomUUID().replaceAll("-", "");
  const collection = collectionName(id);
  const schema = new Schema({
    fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
    vectorIndex: new VectorIndexConfig({
      hnsw: { dimension: model.dimension, distance: "cosine" },
      embeddingFunction: null,
    }),
  });
  await client.execute("INSERT INTO edgeseek_kbs (id, name, model_key, dimension) VALUES (?, ?, ?, ?)", [
    id, cleanName, modelKey, model.dimension,
  ]);
  try {
    await client.createCollection({ name: collection, schema, embeddingFunction: null });
  } catch (error) {
    await client.execute("DELETE FROM edgeseek_kbs WHERE id = ?", [id]);
    throw error;
  }
  return { id, name: cleanName, modelKey, dimension: model.dimension, documentCount: 0, createdAt: new Date().toISOString() };
}

export async function findDuplicateDocuments(kbId, hashes) {
  const kb = await getKnowledgeBase(kbId);
  if (!hashes.length) return [];
  const placeholders = hashes.map(() => "?").join(",");
  const rows = await client.execute(
    `SELECT sha256, status FROM edgeseek_documents WHERE kb_id = ? AND sha256 IN (${placeholders})`,
    [kb.id, ...hashes],
  );
  return (rows ?? []).filter((row) => row.status === "imported").map((row) => row.sha256);
}

export async function listDocuments(kbId) {
  const kb = await getKnowledgeBase(kbId);
  const rows = await client.execute(`SELECT id, filename, sha256, chunk_count, status, created_at
    FROM edgeseek_documents WHERE kb_id = ? ORDER BY created_at DESC`, [kb.id]);
  return (rows ?? []).map((row) => ({
    id: row.id,
    filename: row.filename,
    sha256: row.sha256,
    chunkCount: Number(row.chunk_count),
    status: row.status,
    createdAt: isoDate(row.created_at),
  }));
}

export async function getDocument(kbId, documentId) {
  const kb = await getKnowledgeBase(kbId);
  const rows = await client.execute(`SELECT id, filename, content, sha256, chunk_count, status, created_at
    FROM edgeseek_documents WHERE kb_id = ? AND id = ?`, [kb.id, documentId]);
  if (!rows?.length) throw new HttpError(404, "找不到文档");
  const row = rows[0];
  return {
    id: row.id, filename: row.filename, content: row.content, sha256: row.sha256,
    chunkCount: Number(row.chunk_count), status: row.status, createdAt: isoDate(row.created_at),
  };
}

export async function importDocument(kbId, input) {
  const batch = await importDocuments(kbId, [input]);
  return { ...batch.results[0], refreshMs: batch.refreshMs, visibilityMs: batch.visibilityMs };
}

export async function importDocuments(kbId, inputs) {
  const kb = await getKnowledgeBase(kbId);
  if (!Array.isArray(inputs) || !inputs.length || inputs.length > 100) throw new HttpError(400, "批次须包含 1 至 100 份文档");
  const collection = await getCollection(kb.id);
  const results = [];
  const pending = [];
  const seen = new Set();
  for (const input of inputs) {
    if (!input || typeof input !== "object") throw new HttpError(400, "文档数据无效");
    const expectedSpace = embeddingSpace(model.modelKey, model.revision, input.backend, input.dtype);
    if (!expectedSpace || input.modelKey !== kb.modelKey || input.modelKey !== expectedSpace || kb.dimension !== model.dimension) {
      throw new HttpError(409, "文档向量模型或维度与该知识库不一致");
    }
    const content = String(input.content ?? "");
    const sha256 = createHash("sha256").update(content, "utf8").digest("hex");
    if (!content.trim() || sha256 !== input.sha256) throw new HttpError(400, "文档内容校验失败");
    if (!Array.isArray(input.chunks) || !input.chunks.length) throw new HttpError(400, "没有可写入的文本分块");
    if (input.chunks.length > 8000) throw new HttpError(413, "单份文档超过 8000 个分块");
    for (const [index, chunk] of input.chunks.entries()) {
      if (!chunk || typeof chunk.text !== "string" || !chunk.text.trim() || !Array.isArray(chunk.embedding)) {
        throw new HttpError(400, `第 ${index + 1} 个分块数据无效`);
      }
      validateVector(chunk.embedding);
    }

    const documentId = createHash("sha256").update(`${kb.id}\0${sha256}`).digest("hex");
    const prior = await client.execute("SELECT status FROM edgeseek_documents WHERE kb_id = ? AND sha256 = ?", [kb.id, sha256]);
    if (seen.has(sha256) || prior?.[0]?.status === "imported") {
      results.push({ duplicate: true, documentId, chunks: 0 });
      continue;
    }
    seen.add(sha256);

    await client.execute(`INSERT INTO edgeseek_documents (id, kb_id, filename, content, sha256, chunk_count, status)
      VALUES (?, ?, ?, ?, ?, ?, 'processing')
      ON DUPLICATE KEY UPDATE filename = VALUES(filename), content = VALUES(content), chunk_count = VALUES(chunk_count), status = 'processing'`,
    [documentId, kb.id, safeFilename(input.filename), content, sha256, input.chunks.length]);

    const ids = input.chunks.map((_, index) => createHash("sha256").update(`${documentId}:${index}`).digest("hex"));
    const metadata = input.chunks.map((_, index) => ({
      documentId, filename: safeFilename(input.filename), sha256, chunkIndex: index,
      chunkCount: input.chunks.length, modelKey: kb.modelKey, dtype: String(input.dtype ?? "unknown"),
    }));
    const writeStarted = performance.now();
    await collection.upsert({
      ids,
      documents: input.chunks.map((chunk) => chunk.text),
      embeddings: input.chunks.map((chunk) => chunk.embedding),
      metadatas: metadata,
    });
    const writeMs = performance.now() - writeStarted;
    const entry = { duplicate: false, documentId, chunks: ids.length, writeMs };
    results.push(entry);
    pending.push({ input, documentId, ids });
  }

  if (!pending.length) return { results, refreshMs: 0, visibilityMs: 0 };

  const refreshStarted = performance.now();
  await collection.refresh_index();
  const refreshMs = performance.now() - refreshStarted;

  const visibleStarted = performance.now();
  for (const { input, ids } of pending) {
    const readback = await collection.get({ ids, include: ["embeddings"] });
    const visibleIds = firstDimension(readback.ids);
    const visibleVectors = Array.isArray(readback.embeddings) ? readback.embeddings : [];
    if (visibleIds.length !== ids.length || visibleVectors.length !== ids.length) {
      throw new Error("seekdb 写入后回读数量不一致，文档保持 processing 状态，可重新导入恢复");
    }
    for (let row = 0; row < ids.length; row++) {
      const expected = input.chunks[row].embedding;
      if (visibleIds[row] !== ids[row] || visibleVectors[row].length !== expected.length ||
          visibleVectors[row].some((value, col) => Math.abs(value - expected[col]) > 1e-4)) {
        throw new Error("seekdb 向量回读校验失败，文档保持 processing 状态，可重新导入恢复");
      }
    }
  }
  const visibilityMs = performance.now() - visibleStarted;
  for (const { documentId } of pending) await client.execute("UPDATE edgeseek_documents SET status = 'imported' WHERE id = ?", [documentId]);
  return { results, refreshMs, visibilityMs };
}

export async function search(kbId, input) {
  const kb = await getKnowledgeBase(kbId);
  if (!input || typeof input !== "object") throw new HttpError(400, "查询数据无效");
  const expectedSpace = embeddingSpace(model.modelKey, model.revision, input.backend, input.dtype);
  if (!expectedSpace || input.modelKey !== kb.modelKey || input.modelKey !== expectedSpace || kb.dimension !== model.dimension) {
    throw new HttpError(409, "查询向量模型或维度与该知识库不一致");
  }
  const query = String(input.query ?? "").trim();
  validateVector(input.embedding);
  const nResults = Math.max(1, Math.min(20, Number(input.topK) || 5));
  const collection = await getCollection(kb.id);
  const start = performance.now();
  let result;
  if (input.mode === "vector") {
    result = await collection.query({ queryEmbeddings: [input.embedding], nResults, include: ["documents", "metadatas", "distances"] });
  } else if (input.mode === "fulltext") {
    result = await collection.hybridSearch({
      query: { whereDocument: { $contains: query } },
      nResults,
      include: ["documents", "metadatas", "distances"],
    });
  } else if (input.mode === "hybrid") {
    const trace = [];
    result = await tracing.run(trace, () => collection.hybridSearch({
      query: { whereDocument: { $contains: query } },
      knn: { queryEmbeddings: [input.embedding] },
      rank: { rrf: { rankWindowSize: Math.max(20, nResults * 4), rankConstant: 60 } },
      nResults,
      include: ["documents", "metadatas", "distances"],
    }));
    if (process.env.EDGESEEK_TRACE_SQL === "1") console.info(JSON.stringify({ event: "seekdb.hybrid.trace", kbId: kb.id, trace }));
  } else {
    throw new HttpError(400, "检索方式必须是 vector、fulltext 或 hybrid");
  }
  const dbMs = performance.now() - start;
  const ids = firstDimension(result.ids);
  const documents = firstDimension(result.documents);
  const metadatas = firstDimension(result.metadatas);
  const distances = firstDimension(result.distances);
  const results = ids.map((id, index) => ({
    id,
    document: documents[index] ?? "",
    metadata: metadatas[index] ?? null,
    score: Number.isFinite(Number(distances[index])) ? Number(distances[index]) : null,
  }));
  console.info(JSON.stringify({ event: "seekdb.search", mode: input.mode, sdk: "seekdb@1.4.0", resultCount: results.length, dbMs }));
  return { results, dbMs, mode: input.mode };
}

async function getKnowledgeBase(id) {
  const rows = await client.execute("SELECT id, name, model_key, dimension, created_at FROM edgeseek_kbs WHERE id = ?", [id]);
  if (!rows?.length) throw new HttpError(404, "知识库不存在");
  return toKnowledgeBase(rows[0]);
}

async function getCollection(kbId) {
  return client.getCollection({ name: collectionName(kbId), embeddingFunction: null });
}

function collectionName(id) {
  if (!/^[a-f0-9]{32}$/.test(id)) throw new HttpError(400, "知识库 ID 无效");
  return `edgeseek_kb_${id}`;
}

function validateVector(vector) {
  if (!Array.isArray(vector) || vector.length !== model.dimension || vector.some((value) => typeof value !== "number" || !Number.isFinite(value))) {
    throw new HttpError(422, `向量必须包含 ${model.dimension} 个有限数值`);
  }
  const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  if (Math.abs(norm - 1) > 0.02) throw new HttpError(422, `向量未归一化 (norm=${norm.toFixed(5)})`);
}

function firstDimension(value) {
  if (!Array.isArray(value)) return [];
  return Array.isArray(value[0]) ? value[0] : value;
}

function safeFilename(value) {
  const filename = String(value ?? "document.txt").replace(/[\\/\0-\x1f]/g, "_").trim().slice(0, 255);
  return filename || "document.txt";
}

function toKnowledgeBase(row) {
  return {
    id: row.id, name: row.name, modelKey: row.model_key, dimension: Number(row.dimension),
    documentCount: Number(row.document_count ?? 0), createdAt: isoDate(row.created_at),
  };
}

function isoDate(value) {
  return value instanceof Date ? value.toISOString() : new Date(value ?? Date.now()).toISOString();
}

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
