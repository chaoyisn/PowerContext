# 赛题二：CSV 行级采集与原始记录回查 - 需求分析与评分规范

## 一、题目概述

- **题目编号**：`source-01-table-evidence`
- **题目名称**：CSV 行级采集与原始记录回查
- **满分**：20 分
- **冻结基线**：PowerContext v1.2.0 (`commit 9db1753434162c0aa7c9f1189a1722e617880a52`)
- **基线分支**：`2026-competition` (`commit dab240063bfcfa7917898dc44da4baadb3747bd0`)
- **开发分支**：`competition/csv-row-ingestion`
- **提交形式**：产品仓库公开/已授权 HTTPS URL + 40 位完整 Commit SHA

---

## 二、功能契约要求

1. **接口定义 (`powercontext.sources.csv_rows`)**：
   - `CSVDocumentInput(document_id: str, primary_key: str, content: bytes)`
   - `CSVRowInput(document_id: str, primary_key: str, primary_key_value: str, columns: tuple[str, ...], values: tuple[str, ...])`
   - `CSVRowSource(Source)`：继承自基础 `Source`，`source_id` 与 `name` 为行 identity，`materialization=CAPTURED`，保留组成字段与原列/值。
   - `csv_row_source_id(document_id: str, primary_key_value: str) -> str`
   - `parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]`
   - `CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput]`
2. **CSV 解析与数据校验规则**：
   - 接收完整的离线字节流，严格以 UTF-8 解码，自动剥除 UTF-8 BOM（`\xef\xbb\xbf`）。
   - 遵循 Python `csv.reader` 标准库规则：逗号分隔、`"` 为引用符、`""` 双引号转义、`strict=True` 严格语法。
   - 表头检查：第一行为表头，列名非空、非纯空白且唯一；列名区分大小写并精确比较，首尾空格有效；`primary_key` 必须精确匹配其中一列且非空。
   - `document_id` 必须非空且首尾无空白字符。
   - 数据记录：字段数必须完全等于表头宽度；主键值非空且非纯空白，文档内唯一；首尾空格主键按原值精确处理。
   - 空物理行：表头之后的完全空行忽略；纯表头文档返回空元组 `()`；空文件或无有效表头直接抛出 `ValueError`。
   - 原子性：全文档先完成校验再返回，遇到任何错误立即抛出 `ValueError`，不得返回部分行。
3. **身份编码格式**：
   - 固定格式：`csv:{percent-encoded document_id}:{percent-encoded primary_key_value}`
   - 两个组件分别使用 `urllib.parse.quote(component, safe="")` 进行安全编码。
   - 生成的 `source_id` 长度上限严格限制为不超过 256 字符。
4. **证据投影 (`TextEvidence`)**：
   - 提供标准 `powercontext.text-evidence` 投影。
   - `source_type="csv-row"`, `source_id` 与 Source identity 相同。
   - `content`：按原表头顺序构造的 JSON 对象字符串，采用 `ensure_ascii=False` 与紧凑分隔符 `(',', ':')`。
   - `metadata`：必须恰好包含 `document_id`、`primary_key`、`primary_key_value`、`columns`、`row` 五个键，`row` 保留列顺序。
5. **持久化与精确回查**：
   - 支持通过 `SourceDefinitionRegistry` resolve/read、生成 manifest 与 observation，并经 Runtime ingestion 写入存储。
   - 服务重启或数据库重新加载后，全部 projection 保持一致。
   - Memory 检索结果可通过精确 `MemoryCitation` 追溯并定位到原始单行证据。

---

## 三、评分项与测试矩阵

| 评分组 | 分值 | 必测项 | 验收标准 |
| :--- | :--- | :--- | :--- |
| **CSV 解析和原子校验** | 6 分 | 12 行公开机场数据、BOM、多行字段、引号转义、空行过滤、表头校验、主键校验、字段宽度、UTF-8 编码 | 全部边界输入均满足契约，格式错误原子失败抛出 `ValueError` |
| **稳定 identity 与 TextEvidence** | 7 分 | 编码安全性、URL 转义隔离、256 字符长度限制、列序与值保真、TextEvidence 结构 | `source_id` 稳定无碰撞，`metadata` 包含全部 5 个键且保真 |
| **Runtime 持久化和引用回查** | 7 分 | Manifest 注册、Observation 提交、SQLite 存储、进程重启、Memory FTS 检索、Citation 原始回查 | 真实入库与持久化，重启后所有 projection 匹配，citation 精确命中目标行 |
