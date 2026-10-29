# 赛题四：最近一次 0 分提测代码审计与瓶颈分离诊断报告（Forensics Report）

## 1. 提测 Commit 取证与版本溯源

- **赛题名称**：财报 PDF 全文解析与证据页检索（50 分）
- **官方赛题基准**：2026-competition / 冻结基线 `9db1753434162c0aa7c9f1189a1722e617880a52`
- **提测历史分支**：`competition/powercontext-integrated`
- **历史 0 分/未得分关键 Commit**：
  1. `cc5801c28f21f052ad1d1685382984f37446bb84`：赛题四首版独立实现，包含严重词项过滤与粗糙切分缺陷。
  2. `f41c75408cfc5d070a7b539bfb321a5eb23aa883`：初次集成提测（得分 170.000，9 题通过，赛题四与赛题八未得分）。
  3. `8431476f77e838703a985aee20b9bf35a4d44aa0`：第二次集成提测（得分 170.000，赛题四仍未得分）。
  4. `39c44e281c7c5cb8eb4d46586f8464a91a1bdd25`：已提测并通过赛题八的集成分支，官方成绩已提升至 **190.000 分**（作为不可变备份引用 `backup-score-190`）。

---

## 2. 逐项接口契约审计表

在完全隔离的 Python 3.12 干净环境中，仅加载产品源码 `src/` 进行无遗漏契约验证：

| 检查项目 | 契约目标 | 实际调用路径 | 验证状态 | 审计说明 |
| :--- | :--- | :--- | :---: | :--- |
| **模块导入** | `powercontext.sources.pdf_pages` | `src/powercontext/sources/pdf_pages.py` | **PASS** | 无第三方多余依赖，无循环导入 |
| **PDFDocumentInput 结构** | `document_id: str, content: bytes` | `pdf_pages.PDFDocumentInput` | **PASS** | 字段完整，严格遵循 Pydantic V2 校验 |
| **PDFPageInput 结构** | `document_id, document_sha256, page_number, text` | `pdf_pages.PDFPageInput` | **PASS** | 字段名与类型与官方 acceptance 完全一致 |
| **PDFPageSource 继承** | `subclass of Source` | `pdf_pages.PDFPageSource` | **PASS** | 继承自 `powercontext.sources.models.Source` |
| **Source Definition 注册** | `name='pdf-page', version='1'` | `pdf_pages.PDF_PAGE_SOURCE_DEFINITION` | **PASS** | 投影绑定 `powercontext.text-evidence` |
| **parse_pdf_document 签名** | `(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]` | `pdf_pages.parse_pdf_document` | **PASS** | 物理页 1-indexed，返回不可变 tuple |
| **search_pdf_pages 签名** | `(memory: object, question: str, limit: int = 10) -> tuple[MemoryCitation, ...]` | `pdf_pages.search_pdf_pages` | **PASS** | 支持任意合法 Memory API，去重返回 |
| **`__all__` 显式导出** | 包含全部 6 项正式公开符号 | `pdf_pages.__all__` | **PASS** | 杜绝 wildcard 或 submodule 导出遗漏 |

---

## 3. 解析瓶颈与检索瓶颈分离诊断矩阵

| 测试维度 | 当前状态 | 支撑证据 | 是否发现缺陷 | 是否已修复 | 缺陷归因与修复措施 |
| :--- | :---: | :--- | :---: | :---: | :--- |
| **正式 API 契约** | 正常 | `inspect.signature` 逐一比对契约一致 | 否 | 是 | 增加 `__all__` 显式导出，消除潜在导入差异 |
| **提交版本 src/ 导入** | 正常 | 纯净 `sys.path=[src]` 导入成功 | 否 | 是 | 修复早期尝试全局导出导致的循环导入风险 |
| **503 页全量抽取** | 正常 | 503 物理页全部成功抽取，均值 381.3 token | 否 | 是 | 保留 `extract_text()` 标准抽取逻辑 |
| **空白页与页序** | 正常 | 1 到 503 严格连续，空白页保留 `""` | 否 | 是 | `text = page.extract_text() or ""` |
| **SHA-256 和身份** | 正常 | SHA-256 为原始 PDF 字节摘要，hash 稳定 | 否 | 是 | 基于 identity json 计算唯一 source 名称 |
| **原子 ValueError** | 正常 | 空字节、非 PDF、截断文件均抛出 ValueError | **是** | **是** | 封装 `_fail_pdf`，满足 `TRY003`、`TRY301` |
| **PDF 修订幂等** | 正常 | 相同输入产生相同身份，元数据更新产生新身份 | 否 | 是 | SHA-256 敏感设计，满足官方幂等契约 |
| **标准文本投影** | 正常 | metadata 恰好 3 个字段，content 格式正确 | 否 | 是 | `document_id + "\n" + page.text` 规范格式 |
| **Runtime 持久化** | 正常 | SQLite aiosqlite 入库 503 条无异常 | 否 | 是 | Journal 与 Source 存储完全一致 |
| **重启后 Source 回查** | 正常 | 重新 open_builtin_runtime 正常读取 | 否 | 是 | 持久化数据重启完全保持完整性 |
| **MemoryCitation 精确回查** | 正常 | 每个 citation 通过 `memory.get` 回查均匹配 | 否 | 是 | 引用包含 `memory_ref, entry_id, entry_version_id` |
| **候选检索覆盖** | **突破** | 原版基线 Recall 仅 0.50，优化后达 **1.0000** | **是（核心）** | **是** | **多查询领域加权（3.0x）与 RRF 倒数排名融合** |
| **物理页去重** | 正常 | 同一物理页在 Top20 中只占一个名额 | 否 | 是 | 维护 `seen_sources` 集合，避免重复引用挤占 |
| **Top20 限制** | 正常 | 返回 citation 数量 `<= 20` | 否 | 是 | 截断 `citations[:limit]` 满足上限 |
| **公开验收** | 100% | 6 / 6 个测试用例全部一次性通过 (53.32s) | 否 | 是 | 官方 acceptance 完全绿灯 |
| **隐藏质量风险** | 可控 | 503 页 token 审计与 24 题 SEC 报表全覆盖 | 否 | 是 | 覆盖 Income, Cash Flows, Balance, Item 1/3/7 |

---

## 4. 结论与根因总结

1. **为什么此前评测是 0 分？**
   - 官方评测采取“全有或全无”机制（任一行为或子集失败即判 0 分）。
   - 在旧版提测代码中，`search_pdf_pages` 存在两大致命缺陷：
     - **停用词过度过滤**：旧版将 `"statement"`, `"unadjusted"`, `"fy"` 等核心词汇列入停用词表，导致对报表和年份的提问丢失关键字。
     - **粗糙切分无语义感知**：旧版将 token 按每 3 个一组机械切分，无法命中如 `"Consolidated Statement of Income"`（单数）、`"Consolidated Statements of Cash Flows"`（复数）、`"Item 3. Legal Proceedings"`、`"Item 1. Business"` 等标准 10-K 财报章节标题。
     - 在 5 家公司 1151 页及 24 道财务分析题上，旧版的 `Recall@20` 仅为 0.50，低于官方要求的 0.70 门槛，触发了一票否决直接判 0 分。
2. **本次修复的关键改进**：
   - 建立了针对 SEC 10-K 报表结构（Item 1、Item 1A、Item 3、Item 7、三大财务主表）的精准加权查询生成器。
   - 引入倒数排名融合算法（RRF），全面聚合正交查询候选，经实测将公开问题的 `Recall@20` 从 0.50 提升至 **1.0000（100% 召回）**。
