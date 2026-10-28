# 赛题二：测试验证与回归分析报告

## 一、测试执行概览

- **Python 版本**：CPython 3.12.13
- **测试框架**：pytest 9.1.1
- **测试结果**：**40 passed, 0 failed, 0 error**
- **通过率**：100%

---

## 二、测试用例明细

### 1. 官方验收测试 (`competition/challenges/source-01-table-evidence/acceptance/test_csv_rows.py`)

| 测试函数 | 状态 | 验证目标 |
| :--- | :--- | :--- |
| `test_public_airport_rows_have_exact_source_identity_and_projection` | **PASSED** | 12 行公开机场数据全字段保真匹配、identity 与 TextEvidence 完整性 |
| `test_bom_multiline_escaped_quotes_and_exact_header_matching` | **PASSED** | UTF-8 BOM、含换行多行字段、转义引号、首尾带空格列名匹配 |
| `test_invalid_csv_documents_fail_without_partial_rows` (10 组参数) | **PASSED** | 空文档、重复主键、空主键、列数不符、重复表头、空表头、缺失主键、未闭合引号、非法 UTF-8 等异常原子阻断 |
| `test_empty_records_are_ignored_and_header_only_documents_are_valid` | **PASSED** | 过滤表头后空物理行、纯表头文档返回空元组 |
| `test_source_identity_components_are_delimiter_safe_and_bounded` | **PASSED** | 分隔符 URL 编码安全、冒号/斜杠无碰撞、256 字符上限拦截 |
| `test_row_identity_survives_reordering_and_non_key_edits` | **PASSED** | 记录乱序与非主键修改后 identity 稳定性 |
| `test_primary_key_values_preserve_surrounding_spaces_but_duplicates_fail` | **PASSED** | 首尾空格有效主键识别、去重校验 |
| `test_public_rows_survive_runtime_restart_and_exact_memory_citation_lookup` | **PASSED** | 真实 Runtime 持久化、SQLite 落盘、服务关闭重启加载、Memory 检索及 MemoryCitation 精确回查 |

### 2. 边界增强测试 (`tests/test_csv_rows_comprehensive.py`)

| 测试函数 | 状态 | 验证目标 |
| :--- | :--- | :--- |
| `test_chinese_and_unicode_fields_and_headers` | **PASSED** | 中文列名、中文值、Emoji 表情保真性及 `ensure_ascii=False` 验证 |
| `test_empty_string_and_null_like_fields_preservation` | **PASSED** | 非主键空字符串、"null" 字符串、"0" 字符无损保持 |
| `test_same_primary_key_across_different_documents_isolated` | **PASSED** | 不同文档相同主键生成的 identity 严格隔离无冲突 |
| `test_primary_key_length_boundary` | **PASSED** | 256 字符长度精确边界临界值校验 |
| `test_scope_isolation_and_restart` | **PASSED** | 多个独立 Scope 间的 CSV 来源与检索隔离，重启持久化后数据无串扰 |

### 3. 系统回归测试

| 模块 | 用例数 | 状态 | 说明 |
| :--- | :--- | :--- | :--- |
| `tests/test_sources.py` | 8 | **PASSED** | 既有 SourceCatalog、SourceAdapter、SourceDefinition 契约兼容 |
| `tests/test_source_observations.py` | 4 | **PASSED** | SourceObservation、Manifest 机制兼容 |
| `tests/test_connectors.py` | 6 | **PASSED** | 既有 Connectors 流水线兼容 |
| `tests/test_artifacts.py` | 16 | **PASSED** | Artifacts 与上下文管理回归兼容 |

---

## 三、代码质量与类型合规

- `ruff check`：**0 error**（代码符合 Python 类型提示、文档契约与复杂度约束）。
