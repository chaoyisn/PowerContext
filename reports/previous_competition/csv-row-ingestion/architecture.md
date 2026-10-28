# 赛题二：CSV 行级 Source 架构设计文档

## 一、系统架构图

```
                +---------------------------------------+
                |           CSVDocumentInput            |
                |  (document_id, primary_key, content)  |
                +---------------------------------------+
                                   |
                                   v  parse_csv_document(...)
                +---------------------------------------+
                |        tuple[CSVRowInput, ...]        |
                | (doc_id, pk, pk_val, columns, values) |
                +---------------------------------------+
                                   |
                                   v  registry.resolve(...)
                +---------------------------------------+
                |             CSVRowSource              |
                |   identity: csv:{enc_doc}:{enc_pk}    |
                |     materialization: CAPTURED         |
                +---------------------------------------+
                   |                                 |
                   v                                 v
       +-----------------------+         +-----------------------+
       |   SourceDefinition    |         |   TextEvidence Proj   |
       |     name: csv-row     |         | name: text-evidence   |
       |      version: 1       |         | source_type: csv-row  |
       +-----------------------+         | content: compact JSON |
                   |                     | metadata: 5 fixed keys|
                   v                     +-----------------------+
       +-----------------------+                     |
       | SourceObservation     |                     v
       | (payload, projections)<---------------------+
       +-----------------------+
                   |
                   v  runtime.ingestion.submit(...)
       +-----------------------------------------------+
       |             Runtime Persistence               |
       |         (SQLite / Context Journal)            |
       +-----------------------------------------------+
                   |                                 |
                   v (flush)                         v (contexts.get)
       +-----------------------+         +-----------------------+
       |     Memory Entry      |         |  Persisted Source     |
       |    (FTS searchable)   |         |     Observation       |
       +-----------------------+         +-----------------------+
                   |                                 |
                   v                                 v
       +-----------------------+                     |
       |    MemoryCitation     |---------------------+
       | (exact target lookup) |
       +-----------------------+
```

---

## 二、模块分层与核心职责

1. **协议层与数据模型 (`powercontext.sources.csv_rows`)**：
   - `CSVDocumentInput`：承载输入离线文件与提取配置。
   - `CSVRowInput`：离线解析后的单行中间规整模型，包含列名元组与字段值元组。
   - `CSVRowSource`：实现项目核心 `Source` 抽象基类，标记为 `materialization = CAPTURED`，实现单行证据的离线不可篡改性。
2. **身份机制 (`csv_row_source_id`)**：
   - 使用两段 URI Safe 编码：`csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}`。
   - 彻底避免文档名与主键中包含冒号、斜杠、空格等导致的分隔符混淆碰撞。
   - 设防 256 字符上限，完全兼容关系型数据库主键/索引长度约束。
3. **文本投影适配器 (`CSVRowTextEvidenceProjection`)**：
   - 遵循 `SourceProjection[CSVRowSource]` 协议。
   - 输出契约模型为 `TextEvidence`（`SourceProjectionKey("powercontext.text-evidence", "1")`）。
   - 保留原始字典列序（Python 3.7+ 字典保序），通过 `json.dumps(..., ensure_ascii=False, separators=(',', ':'))` 序列化为紧凑 JSON 文本，为 Memory FTS 检索管道提供无损原文。
4. **运行时与持久化集成 (`CSVRowSourceDefinition`)**：
   - 实现 `SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput]`。
   - 支持生成满足 RFC 8785 确定性哈希签名的 `SourceDefinitionManifest`。
   - 通过 `project_source_for_transport` 封装为 `SourceObservation`，实现零外部代码依赖的无损持久化序列化。
   - 供 `open_builtin_runtime` 管道提取与写入 SQLite，并支持在服务重启后通过 `MemoryCitation` 完成精确回查。
