# PowerContext 赛题十：交付与提测报告 (Submission Report)

## 一、提交基本信息

| 字段 | 详情 |
| :--- | :--- |
| **赛题编号** | 赛题十（Challenge ID: `context-01-evidence-selection`） |
| **赛题名称** | 按查询和预算选择原文证据（Query-Aware Evidence Selection with Budget） |
| **满分** | 20 分（All-or-Nothing 评分机制） |
| **官方基线版本** | PowerContext v1.2.0（Commit `9db1753434162c0aa7c9f1189a1722e617880a52`） |
| **代码仓库** | `https://github.com/chaoyisn/PowerContext` |
| **独立工作分支** | `competition/query-aware-evidence-budget` |
| **独立工作目录** | `E:\OceanBaseContest\powercontext-query-evidence` |
| **开发环境** | Windows 11 + Python 3.12.13 (uv venv) |

---

## 二、代码修改与核心交付物清单

### 2.1 源码文件修改

1. **`src/powercontext/builtin/runtime/models.py`**
   - 在 `PrepareContextRequest` 中扩展 `evidence_selection: bool = Field(default=False, strict=True)` 字段，遵循 Pydantic 严格模型校验，默认值为 `False` 确保 100% 既有兼容性。

2. **`src/powercontext/http/_generated/models.py`**
   - 在 HTTP 契约模型 `PrepareContextRequest` 中同步增加 `evidence_selection: Annotated[StrictBool, Field(...)] = False`，确保 HTTP API 与内置运行时模型完全对齐。

3. **`src/powercontext/builtin/runtime/prepared_context.py`**
   - 定义 `EvidenceFragment` 原文证据数据结构（包含 `address`, `start`, `end`, `text`）。
   - 在 `PreparedContextBuild` 中增加 `fragments: tuple[EvidenceFragment, ...] = ()` 字段。
   - 实现多语言（英文 + CJK 汉字单字与二元词）分词引擎 `_tokenize_evidence_text`。
   - 实现无偏字符坐标切分器 `_extract_sentence_spans`，严格基于 Python Unicode 字符索引返回 `[start, end)`。
   - 实现基于 BM25 词频、动态逆文档频率（IDF）、查询覆盖率奖励、连续词组匹配与数字关键证据加权的打分引擎。
   - 实现相邻与相交证据片段贪心合并算法，大幅消除重复 Citation（每个约 160-200 字节）的开销。
   - 实现零截断风险的端到端 UTF-8 字节信封预算模拟器 `_evidence_envelope_bytes`，并在预算不足以容纳任何合法证据时优雅返回 `status="empty"`。
   - 在 `build_scopes_result` 和 `probe_budget` 中安全分支调度，保证在 `evidence_selection=False` 时完全执行既有装配链路。

### 2.2 测试与报告交付清单

1. **验收与单元测试用例**：
   - `competition/challenges/context-01-evidence-selection/acceptance/test_evidence_selection.py`（官方基准验收套件）
   - `tests/unit/test_query_aware_evidence_selection.py`（针对 T01-T30 规范设计并实现的完整测试套件，共 33 个单元测试）
2. **技术分析与合规报告（`reports/` 目录下共 8 篇）**：
   - `reports/requirements.md`（需求拆解与接口契约）
   - `reports/architecture.md`（系统架构与证据选择算法设计）
   - `reports/implementation.md`（核心代码实现与模块详解）
   - `reports/test_results.md`（官方验收与 T01-T30 测试实测结果，连续 3 次运行验证）
   - `reports/offset_validation.md`（字符坐标与原文无损回查验证报告）
   - `reports/budget_validation.md`（UTF-8 全量字节预算控制与边界验证报告）
   - `reports/integration_notes.md`（跨题兼容性分析与总分支合并消解方案）
   - `reports/submission.md`（最终交付与提测总报告）

---

## 三、测试验证与质量指标达成情况

### 3.1 官方验收测试（`context-01-evidence-selection`）

官方验收测试覆盖 24 条真实 claim、72 篇学术摘要、两档紧凑预算（1400 / 1800 字节），共 48 次高强度端到端请求。

```bash
uv run pytest competition/challenges/context-01-evidence-selection/acceptance/test_evidence_selection.py -v
```

**连续三次实测结果**：
- **第 1 次**：3 passed in 2.32s（100% 通过）
- **第 2 次**：3 passed in 2.26s（100% 通过）
- **第 3 次**：3 passed in 2.45s（100% 通过）

**官方核心质量指标统计**：
1. **证据词项平均召回率（Evidence Token Recall）**：**0.781**（官方合格线 $\ge 0.65$，超越标准 20.1%）
2. **完整证据区间覆盖率（Full Match Ratio）**：**58.3%**（官方合格线 $\ge 40.0\%$，超越标准 45.8%）
3. **预算超额率**：**0.0%**（48 次请求中 0 次超预算，严格遵循 `content_bytes <= max_bytes`）

### 3.2 T01 ~ T30 扩展全覆盖测试套件

涵盖短长文本、首中尾命中、Emoji/中文/换行/转义符号、相邻/重叠合并、最小边界预算、HTTP API 端到端等 33 个测试。

```bash
uv run pytest tests/unit/test_query_aware_evidence_selection.py -v
```

**连续三次实测结果**：
- **第 1 次**：33 passed in 3.75s
- **第 2 次**：33 passed in 3.88s
- **第 3 次**：33 passed in 3.62s

### 3.3 既有基线回归测试

- `tests/test_api_contract.py`：46 passed
- `tests/e2e/test_context_text_assembly.py` & `test_recall_sufficiency_gate.py`：44 passed
- `tests/test_client.py` & `tests/test_api_contract.py`：70 passed
- 代码规范检查：`uv run ruff check` **All checks passed (0 errors)**。

---

## 四、关键核心不变量验证结论

1. **字符切片完全重建不变量（Zero-Discrepancy Slice Invariant）**：
   $$\forall \text{fragment} \in \text{output}, \quad \text{entry.text}[\text{start}:\text{end}] == \text{fragment.text}$$
   在所有 48 次官方验收请求与 33 个单元测试中，所有片段均严格满足该不变量，未出现任何因大小写转换、空白折叠或 Unicode 规范化带来的偏移偏差。

2. **端到端 UTF-8 真实预算不变量（Strict UTF-8 Budget Invariant）**：
   $$\text{len}(\text{content.encode("utf-8")}) == \text{content\_bytes} \le \text{max\_bytes}$$
   信封外层文本、双引号与转义符、Citation 结构均在贪心选择时实时仿真，绝不在生成后使用字符串截断，杜绝了产生残缺字符与破损 JSON。

3. **接口向下兼容不变量（Backward Compatibility Invariant）**：
   在 `evidence_selection=False` 时，所有既有 `prepare` 接口行为与旧版本完全一致，各类 Family 组装、排序和上下文生成零退化。

---

## 五、提测结论

PowerContext 赛题十（按查询和预算选择原文证据）的所有功能研发、算法设计、测试套件补充、性能与规范审计已全面完成，官方验收测试 100% 稳定通过，各项质量指标大幅超越官方要求。已具备正式提测与评分条件。
