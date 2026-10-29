# ResearchFlow — 科研知识与任务连续性助手

> OceanBase × Qoder 2026 数据库比赛 · Qoder 赛道参赛作品
> 基线分支：`2026-competition-ecosystem` @ `d647275c308e09b7b623f322a26f5c4e85734fb0`
> 代码位置：`qoder/researchflow/`
> **在线展示站（已公开发布）**：<https://researchflow-5esfsogn38f.qoder.zone>
> 静态展示版，含真实运行截图与真实验证数据；不连接数据库、不提供模拟查询。完整可交互系统按 [RUN.md](./RUN.md) 本地启动。

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

- `pytest`：**149 个测试**全部通过（单元、seekdb 集成、PowerContext 集成、安全、保留集、中文记忆）。
- `scripts/run_acceptance.py`：T1–T8 端到端验收 + 真实 LLM 用例 T9，共 **150 项校验 0 失败**，
  自带独立 PowerContext 与 API 实例，真实执行服务重启与断连。
- `scripts/fresh_env_e2e.py`：**全新环境**评审旅程（新 venv、新 seekdb 容器与卷、新 PowerContext
  数据目录）20/20 步通过，结束自动清理。
- `scripts/bench_memory_zh.py` / `bench_retrieval.py` / `bench_workflow.py`：中文记忆、中英检索、
  工作流提效三项基准，结果见 [BENCHMARK.md](./BENCHMARK.md)。
- 比赛网站：`site/public/`（静态展示版，含真实运行截图与真实验证数据），**已公开发布**于
  <https://researchflow-5esfsogn38f.qoder.zone>，发布与匿名验证证据见 [SITE_DEPLOYMENT.md](./SITE_DEPLOYMENT.md)。
- 全部证据与失败案例见 [VERIFICATION.md](./VERIFICATION.md) 与 [SECURITY.md](./SECURITY.md)。

---

## 5. 目录结构

```
qoder/researchflow/
├── ARCHITECTURE.md        P0 审计结论 + 架构与数据模型（含实测证据）
├── PLAN.md                分阶段计划与验收映射
├── QODER_LOG.md           Qoder 开发日志（做了什么、踩了什么坑、怎么修的）
├── VERIFICATION.md        seekdb / PowerContext 真实使用证据、T1-T9、部署可行性、风险
├── BENCHMARK.md           中文记忆 / 中英检索 / 工作流提效的方法与原始结果
├── SECURITY.md            安全审计结论与公网部署前置条件
├── SITE_DEPLOYMENT.md     Sites 能力复核、发布结果（真实 URL）、匿名验证清单
├── PUSH_PRECHECK.md       推送前检查结论、敏感内容处理与待授权方案
├── DEMO_SCRIPT.md         2–3 分钟演示视频分镜、旁白稿、录制步骤与截图清单
├── SUBMISSION.md          提交材料清单与需人工补充项
├── RUN.md                 启动、演示、验证命令（Windows 与 Linux/WSL）
├── .env.example           全部配置项（不含真实密钥）
├── site/public/           比赛展示网站（静态，真实截图与真实验证数据）
├── verification/          已提交的验收运行原始记录 + 线上站点发布验证记录
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
│   └── tests/                     149 个测试（单元 + seekdb/PowerContext 集成 + 安全 + 保留集 + HTTP）
├── frontend/              React 18 + Vite 5 + TS，四个页面
├── demo/                  可复现样例：多页 PDF（含空白页）/ Markdown 计划 / 结构化实验记录
└── scripts/
    ├── build_demo_assets.py   生成 demo 语料
    ├── probe_seekdb_capability.py  P0 的 seekdb 能力实测
    ├── smoke_ingest_retrieve.py / smoke_memory.py
    ├── seed_demo.py           通过 HTTP API 灌入演示数据
    ├── reset_store.py         只清理本项目的 rf_ 前缀对象
    └── run_acceptance.py      T1-T9 验收运行器（150 项校验）
```

---

## 6. 诚实声明

- 嵌入式 seekdb（`pylibseekdb`）在 Windows 上**不可用**（官方只发 manylinux wheel），
  本项目使用官方 `pyseekdb` 的**远程服务器模式**。Linux/macOS 可切嵌入式，见 `.env.example`。
- PowerContext 1.4.1 的默认 SQLite 索引使用 `fts5 unicode61` 分词，**纯中文记忆检索命中不到**；
  V2 增加了 CJK 感知的本地匹配 + kind 定向读取作为召回层修复（数据仍来自 PowerContext），
  并在响应中明示实际作答的后端；限制本身在 VERIFICATION.md 与 BENCHMARK.md 中如实记录。
- 默认 embedding 为 all-MiniLM-L6-v2（英文词表）。V2 新增可选 `multilingual` provider
  （paraphrase-multilingual-MiniLM-L12-v2 量化 ONNX），跨语言相似度实测 0.79–0.81 vs 0.17–0.44；
  其召回优先阈值会引入 1/2 负例误报，故默认仍为精度优先配置，权衡见 BENCHMARK.md §2.3。
- 中英混合检索仍有 2 条「英文改写问中文原文」在默认阈值下被门控拦下，属当前能力边界，已记录。
- Qoder Sites **不能**托管 FastAPI / seekdb / PowerContext（无持久进程、无 Python 运行时）；
  因此线上是静态展示版（已公开发布：<https://researchflow-5esfsogn38f.qoder.zone>），
  页面数据由真实验收报告与真实 pytest 运行导出，在线版不提供任何模拟查询，
  能力边界与发布证据见 SITE_DEPLOYMENT.md 与 verification/site-public/PUBLISH_VERIFICATION.md。
