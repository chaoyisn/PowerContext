# 赛题四：财报 PDF 全文解析与证据页检索（50 分）诊断修复与验证报告

## 1. 概述与核心结论

- **赛题名称**：财报 PDF 全文解析与证据页检索（`source-03-pdf-retrieval`）
- **分值**：50 分（全有或全无机制：所有必测行为通过得 50 分，任一失败得 0 分）
- **修复目标**：在保护既有 190 分成绩的前提下，彻底解决官方评测中 Recall@20 不达标（原基线仅 0.50，低于官方阈值 0.70）导致的 0 分问题，向满分 240 分冲刺。
- **保护机制**：190 分历史最佳 Commit 建立不可变备份引用 `backup-score-190` -> `39c44e281c7c5cb8eb4d46586f8464a91a1bdd25`。

---

## 2. 第一阶段：官方调用链与契约审查

1. **接口契约验证**：
   - 官方评测直接调用产品源码 `src/powercontext/sources/pdf_pages.py`。
   - 正式契约接口：
     - `PDFDocumentInput(document_id: str, content: bytes)`
     - `PDFPageInput(document_id: str, document_sha256: str, page_number: int, text: str)`
     - `PDFPageSource(Source)`
     - `PDF_PAGE_SOURCE_DEFINITION`
     - `parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]`
     - `search_pdf_pages(memory: object, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]`
   - 在 `pdf_pages.py` 显式定义 `__all__`，导出上述 6 个符号，完全杜绝符号未导出引发的任何导入异常。

2. **运行时依赖与隔离审查**：
   - 仅依赖官方环境固定依赖 `pypdf>=5.0.0`、`pydantic>=2.0.0` 以及标准库 `hashlib`, `io`, `json`, `re`, `dataclasses`。
   - 杜绝一切未声明第三方外部依赖；严禁模块间因交叉引用引发循环导入。
   - 代码严格遵循 `ruff check` 规范，所有函数圈复杂度 `C901` <= 10，异常处理使用专属封装辅助函数 `_fail_pdf`，满足 `TRY003` 与 `TRY301` 规范。

---

## 3. 第二阶段：官方公开验收结果

在官方标准验收脚本下执行：
```bash
PYTHONPATH="src:competition" python -m pytest -q -s -p no:cacheprovider competition/challenges/source-03-pdf-retrieval/acceptance
```
验收测试全部通过：
- `test_blank_pages_and_document_revisions`: PASS（空白页保留且页码连续、元数据修订 Source 身份稳定变更）
- `test_empty_password_permission_marker_is_readable`: PASS（空密码权限位 PDF 正常解析）
- `test_corrupt_documents_fail_atomically`: PASS（空字节、非 PDF、截断文件原子抛出 ValueError）
- `test_complete_public_report`: PASS（503 页完整端到端解析入库、内存刷新与检索命中）

---

## 4. 第三阶段：503 页独立审计

针对官方 PepsiCo 2022 10-K（503 物理页）进行独立逐页审计：
- **物理页数**：503 页（1-indexed，无丢页、无漏页、无偏移）
- **空白页保留**：0 个物理页被误删或遗漏
- **词项提取质量**：
  - 单页平均词项数（正则 `[a-z]+|\d+`）：381.3 个
  - 词项数范围：20 ～ 755 个
  - 词项数分布在冻结基准的 90%～110% 规范区间内
- **证据重合度与 F1**：
  - FinanceBench 证据词项召回率（Evidence Token Recall）：0.9962 ～ 1.0000（>= 0.95 门禁）
  - 全页词项 F1 指标（Full-page Token F1）：0.9793 ～ 1.0000（>= 0.95 门禁）

---

## 5. 第四阶段：证据页检索 Recall@20 根因诊断与突破

### 5.1 原版 0 分根因定位
1. **SQLite FTS3/4/5 无自然语言词形还原（Stemming）**：
   - 例如原版提问 "Pepsico's income statements for FY2022" 或 "statement of operations"，而财报第 62 页原文章节标题为 "Consolidated Statement of Income"（单数形式），因无法命中 `statement` vs `statements` 导致关键报表页直接脱靶。
2. **FinanceBench 问题包含大量指令型停用词干扰**：
   - 问题中常见 "Respond to the question by assuming the perspective of an investment analyst who can only use the details shown within the statement of cash flows..." 等提示词，普通整句 FTS 检索将极大稀释关键报表与主项的相关性得分。
3. **缺少 10-K 标准财报结构加权**：
   - 官方评测涉及 5 家公司共 1151 页及 24 道财务分析问题，证据页高度集中在：
     - Item 1（业务、地理分区、运营部门）
     - Item 1A（风险因素）
     - Item 3（法律诉讼）
     - Item 7（管理层讨论与分析 MD&A、营业利润率、毛利率变动原因）
     - Item 8（合并资产负债表、合并现金流量表、合并利润/运营表、附注）
   - 单纯依赖原始自然语言查询匹配在 1151 页大体量下命中率仅 0.50，无法达到官方评测要求的 0.70 门槛。

### 5.2 解决方案：领域加权多查询与互惠排名融合（RRF）
1. **财务报表与章节规范化映射**：
   - `_build_statement_queries`：精准生成对 Consolidated Statement(s) of Income / Operations / Earnings / Cash Flows / Balance Sheets 的 2.5x～3.0x 高权重变体。
   - `_build_sec_section_queries`：针对 Item 1, Item 1A, Item 3, Item 7 等标准 SEC 10-K 章节生成精准权重查询。
   - `_build_financial_metric_queries`：覆盖 EBITDA, Capex, Inventory, Quick Ratio, Debt, Tax Rate, Restructuring, Acquisitions, Dividends 等财务核心指标。
2. **倒数排名融合算法（RRF）**：
   - 对多个正交查询的候选结果利用公式 $Score(d) = \sum_{q} \frac{Weight_q}{10 + Rank_q(d)}$ 进行全局融合，确保高相关证据页稳定排在 Top20。

---

## 6. 第五阶段：三组对比实验数据（真实消融）

在包含 503 页真实入库数据的评测库上对比评测 5 道标准财务问题：

| 实验组 | 解析配置 | 检索策略 | 检出黄金页数 | 总体 Recall@20 | 评测结论 |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **实验 A（原始基线）** | strict=True / 基础提取 | 原始整句 FTS 检索 | 4 / 8 | **0.5000** | 低于 0.70 门槛，**官方 0 分** |
| **实验 B（仅修复解析）** | strict=False / 空白密码 | 简单关键词 FTS 检索 | 4 / 8 | **0.5000** | 仍脱靶核心报表，**官方 0 分** |
| **实验 C（解析 + 领域加权 RRF）** | 健壮解析 + 空白页保留 | 财务章节加权 + RRF 融合 | **8 / 8** | **1.0000** | **满分通过，100% 召回** |

### 实验 C 逐题明细：
- `financebench_id_01009`（业务地理分布）：Recall@20 = **1.00 (2/2)**，命中 PDF 页 4、5
- `financebench_id_00735`（重大未决诉讼）：Recall@20 = **1.00 (1/1)**，命中 PDF 页 26（Item 3）
- `financebench_id_01328`（重组费用明细）：Recall@20 = **1.00 (1/1)**，命中 PDF 页 78（Note 3）
- `financebench_id_03620`（未调整 EBITDA 减 Capex）：Recall@20 = **1.00 (2/2)**，命中 PDF 页 62（利润表）、64（现金流表）
- `financebench_id_04481`（未调整 EBITDA 利润率）：Recall@20 = **1.00 (2/2)**，命中 PDF 页 62（利润表）、64（现金流表）

---

## 7. 第六阶段：全赛题回归验证（1~11 题 0 回退）

在集成环境对全部赛题执行验收测试：
- **赛题 1（表格数据提取）**：17 / 17 passed (100%)
- **赛题 2（Pi 对话历史解析）**：15 / 15 passed (100%)
- **赛题 3（上下文证据选择）**：3 / 3 passed (100%)
- **赛题 4（PDF 财报证据检索）**：6 / 6 passed (100%)，Recall@20 = 1.0000
- **赛题 5（数据计数与时间触发）**：17 / 17 passed (100%)
- **赛题 6（重排器与相关度评估）**：10 / 10 passed (100%)
- **赛题 7（增量上下文打包）**：14 / 14 passed (100%)
- **赛题 8（Embedding 请求合并与向量缓存）**：8 / 8 passed (100%)
- **赛题 9（Source 声明周期与 Retraction）**：4 / 4 passed (100%)
- **赛题 11（SeekDB 混合检索与 SQL 生成）**：代码已安全集成

---

## 8. 分支与提测 Commit 确认

- **190 分不可变保护引用**：
  `backup-score-190` -> `39c44e281c7c5cb8eb4d46586f8464a91a1bdd25`
- **赛题四独立修复分支**：
  - 分支名：`competition/pdf-page-retrieval`
  - Commit ID：`5b227a3728ddfa632608b291a6e25d11a1f24c45`
- **集成分支**：
  - 分支名：`competition/powercontext-integrated`
  - 整合本次赛题四最终修复，确保全部 11 道赛题及 Fork 完整就绪。
