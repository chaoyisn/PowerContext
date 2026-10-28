# ResearchFlow — 科研知识与任务连续性助手

> OceanBase × Qoder 2026 数据库比赛 · Qoder 赛道参赛作品
> 基线分支：`2026-competition-ecosystem` @ `d647275c308e09b7b623f322a26f5c4e85734fb0`
> 代码位置：`qoder/researchflow/`

ResearchFlow 是一个「带证据的知识库 + 长期任务记忆 + 科研进度恢复」的科研工作台，
面向研究生、科研人员与 AI Infra 工程师。它不是 ChatPDF：

| 普通 ChatPDF | ResearchFlow |
| --- | --- |
| 回答来源不可核对 | 每条引用都能点开 seekdb 中存储的**原文物理页** |
| 结论与资料混在一起 | 每条论断标注「资料直接支持 / 模型推断 / 尚无证据」 |
| 新会话从零开始 | 按 `project_id` 从 PowerContext 恢复「上次做到了哪里、接下来该做什么」 |
| 检索与记忆耦合 | seekdb 管文献证据，PowerContext 管任务记忆，**两者可独立断开验证** |

---

## 1. 它能做什么

**A. 文档知识库（seekdb）**
- 上传 PDF / Markdown / TXT；文件内容 SHA-256 作为 `doc_id`，重复上传自动去重。
- PDF 保留**真实物理页号（从 1 开始）**；空白页也保留页级身份记录，不产生 chunk。
- 原文、文档元数据、页、chunk、embedding 全部写入 seekdb（Docker 容器 `contest-seekdb`，v1.4.0.0）。
- 三种检索模式可切换、可并排对比：`vector`（HNSW ANN）、`fulltext`（ik 全文）、`hybrid`（RRF 融合）。
- 结果带文件名、物理页码、文本片段、score（含 `score_kind` 语义标注）、coverage、relevance 与稳定 `chunk_id`。
- 点击「查看原文」打开 seekdb 中存储的该页原文；不存在的页码返回 404，绝不合成。

**B. 带证据的科研问答（seekdb + LLM）**
- 先检索 seekdb，通过**证据门控**的命中才会成为候选证据。
- LLM（OpenAI 兼容接口，默认 DeepSeek）只能引用给出的证据编号；服务端把每个引用回查 seekdb：
  不在检索结果里的引用被剔除并上报，页码不存在的引用被剔除，失去引用的「资料直接支持」自动降级为「模型推断」。
- 语料中没有答案的问题返回 `no_evidence`，**不产生任何 citation**。
- 未配置 LLM 密钥时进入明确标注的「仅检索模式」，只返回原始证据，不冒充模型回答。

**C. 科研任务记忆（PowerContext）**
- 一个科研项目 = 一个 PowerContext Scope，用 `idempotency_key` 绑定，重启/重试安全。
- 显式保存研究进度：目标、已完成工作、已确认决策、关键证据指针、未解决问题、next_steps。
  **系统永不自动写入**；重复内容去重（`skipped_duplicates`），内容未变化不产生新快照。
- 新会话仅凭 `project_id` 恢复，并生成确定性的「上次做到了哪里 / 接下来该做什么」续研简报。
- 历史记忆在 UI 与 API 中始终标记为 `source="memory"`，永不冒充文献证据。

**D. 最小可用界面（React + Vite + TypeScript）**
四个页面：项目总览 / 知识库 / AI 工作台 / 任务记忆。中文为主，响应式，专业 SaaS 风格。

---

## 2. 架构一图流

```
Browser (React 18 + Vite + TS, 4 pages)
        │  HTTP/JSON
        ▼
FastAPI (backend/app/api)  ── OpenAPI at /docs
   ├─ ingestion   解析/分块/去重/落库        ─┐
   ├─ retrieval   向量+全文+混合(RRF)          ├─ pyseekdb 1.4.0.post1 ──► seekdb 127.0.0.1:2881 (db=test)
   ├─ agent       证据约束问答 + citation 校验 ─        │
   └─ memory      scope/进度快照/续研简报  ── powercontext.client 1.4.1 ──► PowerContext Server 127.0.0.1:17429
                                                                  │
                                                        LLM (OpenAI 兼容, 环境变量配置)
```

- **seekdb = 文献证据**：只有它能产生 citation。
- **PowerContext = 任务记忆**：断开它，检索与问答照常工作（验收用例 T7 实测）。
- 两个后端职责分离是设计目标，不是权宜之计。

详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

---

## 3. 快速开始

完整命令见 [RUN.md](./RUN.md)。最短路径（本机已具备 seekdb 容器与 PowerContext venv）：

```bash
# 1. PowerContext 记忆服务
POWERCONTEXT_HOME=$PWD/services/powercontext-data \
  services/.venv-powercontext/Scripts/powercontext.exe server run --host 127.0.0.1 --port 17429 --no-env-file

# 2. ResearchFlow 后端（同时同源提供前端构建产物）
cd backend && RF_LLM_API_KEY="$DEEPSEEK_API_KEY" .venv/Scripts/python -m app.api.main

# 3. 灌入 demo 语料与一个示例项目
python scripts/seed_demo.py

# 4. 打开浏览器
#    http://127.0.0.1:8787/            项目总览
#    http://127.0.0.1:8787/knowledge   知识库
#    http://127.0.0.1:8787/workbench   AI 工作台
#    http://127.0.0.1:8787/memory      任务记忆
#    http://127.0.0.1:8787/docs        OpenAPI
```

---

## 4. 验证与验收

- `pytest`：**88 个测试**全部通过（含针对真实 seekdb 与真实 PowerContext 的集成测试）。
- `scripts/run_acceptance.py`：T1–T8 端到端验收，自带独立 PowerContext 与 API 实例，
  真实执行服务重启与断连，逐条记录 输入 / 预期 / 实际 / PASS-FAIL / 日志位置，**不预填结果**。
- 全部证据与失败案例见 [VERIFICATION.md](./VERIFICATION.md)。

---

## 5. 目录结构

```
qoder/researchflow/
├── ARCHITECTURE.md        P0 审计结论 + 架构与数据模型（含实测证据）
├── PLAN.md                分阶段计划与验收映射
├── QODER_LOG.md           Qoder 开发日志（做了什么、踩了什么坑、怎么修的）
├── VERIFICATION.md        seekdb / PowerContext 真实使用证据、T1-T8、部署可行性、风险
├── RUN.md                 启动、演示、验证命令
├── .env.example           全部配置项（不含真实密钥）
├── backend/
│   ├── pyproject.toml     固定兼容版本
│   └── app/
│       ├── config.py / errors.py / logging_setup.py
│       ├── db/seekdb.py           pymysql + pyseekdb 双通道、建表、健康检查
│       ├── ingestion/             hashing / parsers / chunking / service
│       ├── retrieval/             embeddings / relevance(证据门控) / service
│       ├── memory/                models / client / service（PowerContext）
│       ├── agent/                 llm / prompts / service（证据问答）
│       └── api/                   FastAPI 路由 + schemas + OpenAPI
│   └── tests/                     88 个测试（单元 + 集成 + HTTP）
├── frontend/              React 18 + Vite 5 + TS，四个页面
├── demo/                  可复现样例：多页 PDF（含空白页）/ Markdown 计划 / 结构化实验记录
└── scripts/
    ├── build_demo_assets.py   生成 demo 语料
    ├── probe_seekdb_capability.py  P0 的 seekdb 能力实测
    ├── smoke_ingest_retrieve.py / smoke_memory.py
    ├── seed_demo.py           通过 HTTP API 灌入演示数据
    ├── reset_store.py         只清理本项目的 rf_ 前缀对象
    └── run_acceptance.py      T1-T8 验收运行器
```

---

## 6. 诚实声明

- 嵌入式 seekdb（`pylibseekdb`）在 Windows 上**不可用**（官方只发 manylinux wheel），
  本项目使用官方 `pyseekdb` 的**远程服务器模式**。Linux/macOS 可切嵌入式，见 `.env.example`。
- PowerContext 1.4.1 的默认 SQLite 索引使用 `fts5 unicode61` 分词，**纯中文记忆检索命中不到**；
  完整记忆恢复不依赖搜索（走 `list_memory_entries` 全量读取），且 UI 会展示该限制说明。
- 默认 embedding 为 all-MiniLM-L6-v2（英文词表），中文查询命中纯英文原文时语义相似度偏低；
  已通过「双语 demo 语料 + 混合检索 + 语义逃逸门控 + 可切换 embedding provider」缓解，
  限制本身在 VERIFICATION.md 中如实记录。
- Qoder Sites **不能**托管 FastAPI / seekdb / PowerContext（无持久进程、无 Python 运行时）；
  公开部署方案见 VERIFICATION.md 第 6 节，本轮未发布。
