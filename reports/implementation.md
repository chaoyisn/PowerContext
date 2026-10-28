# 赛题二：修改文件及实现原理

## 一、修改与新增文件清单

1. **新增核心源码**：`src/powercontext/sources/csv_rows.py`
   - 实现 `CSVDocumentInput`、`CSVRowInput`、`CSVRowSource`。
   - 实现 `csv_row_source_id` 身份算法与严格长度校验。
   - 实现 `parse_csv_document` 解析器与原子级防御性校验。
   - 实现 `CSVRowTextEvidenceProjection` 文本证据投影。
   - 实现 `CSVRowSourceDefinition` 及导出常量 `CSV_ROW_SOURCE_DEFINITION`。
2. **修改模块导出**：`src/powercontext/sources/__init__.py`
   - 显式导出 `CSV_ROW_SOURCE_DEFINITION`、`CSVDocumentInput`、`CSVRowInput`、`CSVRowSource`、`csv_row_source_id`、`parse_csv_document`。
3. **新增单元与回归测试**：`tests/test_csv_rows_comprehensive.py`
   - 补充中文 Unicode、空字段保真、跨文档同主键隔离、长度边界、Scope 隔离及服务重启回查测试。

---

## 二、关键实现原理

### 1. 容错与无损解码
在 `_decode_csv_content` 中，首先检测 UTF-8 BOM 标记（`\xef\xbb\xbf`）并进行安全切片剥除，然后以严格 UTF-8 解码为文本。如果输入非合法 UTF-8 字节（如非法序列 `\xff`），触发 `UnicodeDecodeError` 并统一包装为 `CSVRowError`（`ValueError` 的子类）抛出，满足题目“遇到任何错误均以 ValueError 失败且不返回部分行”的要求。

### 2. 字段序与原样保持
标准库 `csv.reader` 结合 `io.StringIO(text, newline="")` 使用，保留字段内的原始换行（如 `\r\n`）与转义双引号。列名与值均直接以 `tuple[str, ...]` 封装，禁止任何 strip 或类型推导（如数值转换、布尔转换），百分之百还原原始数据。

### 3. 表头与数据一致性原子校验
- 表头必须存在且至少包含 1 列，表头字段均不可为空或纯空白，且不允许重复。
- `primary_key` 必须严格包含在表头中，区分大小写与包含的有效空格。
- 数据行中的字段数必须严格与表头宽度一致，过滤完全空物理行。
- 每行主键必须非空、非纯空白，且在当前文档作用域内全局去重；若出现重复或空值，全文档解析原子回滚抛错。

### 4. 投影序列化规范
在 `CSVRowTextEvidenceProjection.project` 中，通过 `dict(zip(source.columns, source.values, strict=True))` 构造保序键值字典，使用标准紧凑分隔符 `separators=(',', ':')` 和 `ensure_ascii=False` 生成 JSON 字符串。元数据字典严格仅包含 `document_id`、`primary_key`、`primary_key_value`、`columns` 和 `row` 5 个键。

### 5. 存储与进程重启一致性
`CSVRowSource` 声明为 `materialization: CAPTURED`，持久化时不依赖本地文件系统原始 CSV 文件，所有行内容均内联封装在 `SourceObservation.payload` 和 projections 中。在运行时服务停止并重启（模拟不同进程周期）后，从 SQLite 重新加载的 Source 依然能重建出完全一致的 `TextEvidence`，支撑精确引用追踪。
