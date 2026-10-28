# ResearchFlow — 执行计划

基线：`2026-competition-ecosystem` @ `d647275c308e09b7b623f322a26f5c4e85734fb0`
工作目录：`qoder/researchflow/`（隔离 worktree `D:/OceanBase/PowerContext-researchflow`）

---

## P0 仓库审计 — 已完成

- [x] `git remote -v` / `git branch -a` / `git rev-parse HEAD` / `git status -sb` 全部记录
- [x] 确认 `origin` 与 `upstream` 的 `2026-competition-ecosystem` 同为 `d647275c…`，fetch 后无变化
- [x] 建立隔离 worktree，不影响 `master` 及其他 5 个赛题 worktree
- [x] 实测 seekdb（运行中，v1.4.0.0，127.0.0.1:2881）与 pyseekdb 三种分析器
- [x] 实测 PowerContext Server 1.4.1 全链路（scope / remember / search / prepare_context）
- [x] 实测 LLM（DeepSeek）与本地 Embedding（all-MiniLM-L6-v2 ONNX 384 维）
- [x] `ARCHITECTURE.md` / `PLAN.md` / `.env.example` / `.gitignore`

## P1 数据闭环（seekdb）— 已完成

- [x] `db/seekdb.py`：pymysql 连接、`rf_documents` / `rf_pages` 建表、`rf_chunks` collection、健康检查
- [x] `ingestion/parsers.py`：PyMuPDF 真实物理页（`page.number + 1`，空页保留身份）、MD、TXT
- [x] `ingestion/chunking.py`：页内分块，保留 `char_start` / `char_end`
- [x] `ingestion/service.py`：SHA-256 去重、幂等 upsert、失败写 `status=failed` + `error_message`
- [x] `retrieval/embeddings.py`：`minilm` / `hashing` / `openai` 三 provider
- [x] `retrieval/service.py`：`vector` / `fulltext` / `hybrid` 三模式 + `compare`
- [x] 证据查看接口：按 `doc_id` + `page_no` 回原文，页码不存在则 404
- [x] 单测 + 集成测试：**T1 / T2 / T3 / T8**

## P2 记忆闭环（PowerContext）— 已完成

- [x] `memory/client.py`：连接、健康探测、失败显式报错
- [x] `memory/service.py`：`ensure_scope`（幂等 key）、`save_progress`、`restore`、`list_history`
- [x] 记忆条目按 `kind` 分类写入；进度快照写 Atomic Memory（含 seq/updated_at/fingerprint）
- [x] 恢复视图区分「历史记忆」与「文献证据」两种来源标签
- [x] 测试：**T4 / T5 / T6 / T7**

## P3 最小产品 — 已完成

- [x] `agent/`：证据约束问答、三级结论（`supported` / `inferred` / `no_evidence`）、citation 服务端回查校验、retrieval-only 模式
- [x] FastAPI 全量路由 + OpenAPI 文档 + CORS + 结构化日志 + request_id
- [x] 上传校验：扩展名白名单、大小上限、文件名路径穿越防护
- [x] 前端四页面（React + Vite + TS）：项目总览 / 知识库 / AI 工作台 / 任务记忆
- [x] 浏览器实测四页面主流程与边界

## P4 交付与验收 — 已完成

- [x] `demo/`：多页 PDF（可按真实页码核对，含空白页）+ Markdown 研究计划 + 结构化实验记录
- [x] T1–T8 端到端跑通，逐条记录 输入 / 预期 / 实际 / PASS-FAIL / 日志位置（**不预填结果**）
- [x] `README.md` / `RUN.md` / `VERIFICATION.md` / `QODER_LOG.md` / `ARCHITECTURE.md` / `.env.example`
- [x] `git diff` 复核：仅新增/修改 `qoder/researchflow/**`，四个生态目录与其他赛题零改动
- [x] Qoder Sites 部署可行性分析与后续接入方案（本轮不发布）
- [x] 人工截图取证清单（QODER_LOG.md 末尾）

**最终结果：pytest 88 通过；验收 T1–T8 + T9-LLM 全部 PASS（150 项校验 0 失败）；浏览器四页实测通过。**

---

## 验收用例映射

| 编号 | 场景 | 验证手段 | 阶段 |
| --- | --- | --- | --- |
| T1 | 上传 PDF，全部物理页有稳定记录，seekdb 保存正确 | 直查 `rf_pages` 行数 == PDF 页数（含空页），`page_no` 连续从 1 起 | P1 |
| T2 | 明确问题 → 检索返回正确资料与真实页码 | 三种模式检索，断言命中 doc/page 与人工核对一致 | P1 |
| T3 | 不存在答案的问题 → 不伪造 citation | 断言零命中或 `no_evidence`，且 `citations == []` | P1/P3 |
| T4 | 新建项目，保存已确认决策与 next_steps，PowerContext 实际写入 | `list_memory_entries` + `get_artifact` 回读，revision ≥ 1 | P2 |
| T5 | 结束并重建会话，恢复决策与 next_steps | 新 client / 新进程按 `project_id` 恢复，字段逐一比对 | P2 |
| T6 | 重启服务后数据库与记忆仍可查询 | 重启 PowerContext Server（SQLite）+ seekdb 容器，复跑 T2/T5 | P2 |
| T7 | 断开 PowerContext，对比任务恢复能力 | 停服 → 记忆接口 503、检索问答仍可用 → 恢复服务再对比 | P2 |
| T8 | 断开 seekdb，检索接口报真实错误 | 指向错误端口 → 断言 503 + 真实异常文本，且响应体不含任何预置结果 | P1 |

---

## 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| seekdb 容器 `contest-seekdb` 被其他赛题共用 | 误删他人数据 | 所有对象加 `rf_` 前缀；测试只操作自己的表/集合；不执行 `DROP DATABASE` |
| seekdb v1.4.0.0 已知 IK 词典竞态 / 非 ASCII 大小写折叠缺陷（见 `D:/OceanBase/fts-validation-summary.md`） | 中文全文召回偶发偏差 | 分析器可配置（`ik`/`ngram`/`space`）；默认混合检索，向量腿兜底 |
| DDL 锁：即使 `IF NOT EXISTS` 也会取 seekdb DDL 锁 | 建表偶发 1205 | 建表前先查 `information_schema`，存在即跳过；1205/1061 幂等重试 |
| all-MiniLM 中文语义弱 | 纯向量模式中文召回差 | 默认 hybrid；提供 `openai` embedding provider 切换位 |
| HF 模型下载失败（离线环境） | 服务起不来 | 启动时探测，失败自动回退 `hashing` 并在健康检查里报告 |
| PowerContext 未配 embedding → `search_memory` 只走 FTS | 记忆语义召回弱 | 用 `prepare_context` + 按 `kind` 精确列举作为主恢复路径，FTS 仅作辅助 |
| Windows 无 `pylibseekdb` | 无法嵌入式部署 | 已确认走远程服务器模式；`RUN.md` 写明 Linux/macOS 可切嵌入式 |
| Qoder Sites 不托管本地 FastAPI/seekdb | 无法一键公网演示 | P4 输出可行性分析与三种接入方案，本轮不发布 |
