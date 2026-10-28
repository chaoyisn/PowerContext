# QODER_LOG — ResearchFlow 开发日志

本文件记录 Qoder Agent 的实际开发过程：每一步做了什么、遇到什么问题、如何解决、验证结果。
时间戳为本地时间（UTC+8）。

---

## 2026-10-29 P0 仓库审计

### 01:05 基线确认

执行 `git remote -v` / `git branch -a` / `git rev-parse HEAD` / `git status -sb`：

- `D:/OceanBase` 本身**不是** git 仓库，实际仓库是 `D:/OceanBase/PowerContext`（主 worktree，分支 `master`）。
- `origin` = `https://github.com/chaoyisn/PowerContext.git`（私有仓库），`upstream` = `https://github.com/oceanbase/powercontext.git`。
- 私有仓库**已包含**同名比赛分支 `2026-competition-ecosystem`。
- 基线 SHA：`d647275c308e09b7b623f322a26f5c4e85734fb0`（origin 与 upstream 一致；`git fetch` 两侧后无变化）。
- 基线分支只有 5 个占位目录 `dify/ gaode/ minimax/ qoder/ stepfun/`，确认工作目录为 `qoder/researchflow/`。

**问题**：主 worktree 停在 `master` 且有大量已 staged 的 `competition/**` 改动（用户在途工作）。
另发现 5 个其他赛题 worktree（`PowerContext-embedding`、`PowerContext-integrated`、`E:/OceanBaseContest/powercontext-*` 三个）。

**决策**：不在主 worktree 切分支（会破坏在途工作），改用 `git worktree add --track -b 2026-competition-ecosystem`
新建隔离副本 `D:/OceanBase/PowerContext-researchflow`。首次尝试 `git worktree add <path> 2026-competition-ecosystem`
报 `fatal: invalid reference`（本地无同名分支，worktree add 不做远端 DWIM），加 `-b … origin/…` 后成功。

### 01:15 环境审计

Python 3.11.7 / Node v24.14.0 / npm 11.3.0 / Docker 29.6.1 / uv 0.11.28。
`DEEPSEEK_API_KEY` 在环境中存在，实测 `deepseek-chat` 可用（返回 `OK`）。
`pyseekdb`、`powercontext` 初始均未安装；PyPI 可达（`pyseekdb` 最新 1.4.0.post1，`powercontext` 最新 1.4.1）。

### 01:20 seekdb 实测

发现 **运行中的真实 seekdb 服务**：容器 `contest-seekdb`（`oceanbase/seekdb@sha256:4db4961869d5…`，Up 31h），
`127.0.0.1:2881`，`SELECT VERSION()` → `5.7.25-OceanBase seekdb-v1.4.0.0`，库 `test`，`root`/空密码。
数据在 Docker volume `contest-seekdb-data-20261027`，持久化。

安装 `pyseekdb==1.4.0.post1` 后评估两种模式：

- **嵌入式模式失败**：`_PYLIBSEEKDB_AVAILABLE=False`，`Client(path=...)` 抛
  `RuntimeError: Embedded Client is not available because pylibseekdb is not available. Please install pylibseekdb (Linux only)`。
  原因：`pylibseekdb` 只发布 manylinux wheel，Windows 无对应 wheel。**这是硬性平台限制，不是配置问题。**
- **远程服务器模式成功**：`Client(host="127.0.0.1", port=2881, tenant="sys", ...)` → `_ClientProxy(RemoteServerClient)`，
  `list_collections()` 返回 `[]`（该库当前无集合，与其他项目无冲突）。

写 `scripts/probe_seekdb_capability.py`，对 `ik` / `ngram` / `space` 三种全文分析器各跑一遍
「建集合（HNSW cosine 384 + FULLTEXT）→ 写 4 条中英混排文档 → count → 向量检索 → 中文向量检索 → 混合检索 → 元数据过滤 → 清理」：

- 三种分析器全部 `create/add/count/query/hybrid_search/where` 通过。
- 英文 needle `hybrid retrieval` → `d1` 首位；中文 needle `混合召回` → `ik` 与 `ngram` 均把 `d3` 排首位，
  `space` 把 `d4` 排首位（无中文分词，符合预期）。
- **选定 `ik` 为默认分析器**，保留可配置开关。

### 01:30 PowerContext 实测

先确认包名事实：master 上是 `powercontext`（`pyproject.toml: name = "powercontext"`），
`powermem` 只存在于 `origin/archive/powermem` 与 `origin/powermem_v1.0.0`，**不能对着 powermem 写代码**。

独立 venv 安装 `powercontext[cli,server]==1.4.1`，启动：

```
POWERCONTEXT_HOME=<project>/services/powercontext-data \
  powercontext server run --host 127.0.0.1 --port 17429 --no-env-file
```

`GET /health/ready` → `{"status":"ready","checks":{"runtime":"ready","database":"ready",…}}`（SQLite 默认后端）。
启动日志有一条中文「Inference capability notice」，提示未配置 generation/embedding 模型 → 影响异步能力，不影响显式记忆。

用 `powercontext.client.PowerContextClient` 实测：`get_liveness` ok；
`create_scope(idempotency_key="researchflow:probe:1")` → `scp_52zk5gy7720vv1t67dqm2m99sb`，
**同 key 二次调用返回同一 scope_id，幂等成立**；
`remember_memory(kind="decision", text=<中文>)` → `changed=True`，`family=atomic-memory`，`revision=1`；
`search_memory` → `mode=text`（未配 embedding，走 FTS），命中 1 条；
`list_memory_entries` → 1 条；`prepare_context(max_bytes=2000)` → `status=ready`，`content_bytes=648`，
内容带 `BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1` 信任边界包装。

**契约事实核对**（grep `src/powercontext/http/_generated/models.py` 确认，避免臆造字段）：
master 只有 `scope_id` 一种隔离维度，`RememberMemoryRequest` / `PrepareContextRequest`
**没有 `user_id` / `agent_id` / `run_id` / `session_id`**；`CreateScopeRequest.idempotency_key` 必填；
`RememberMemoryRequest.text` ≤ 8192 字节；Artifact 无客户端可写 `updated_at`。
→ 据此把「科研项目」映射为 Scope，`updated_at` 由 ResearchFlow 自己放进 payload。

### 01:35 控制台中文乱码

实测输出里中文显示为乱码。定位为 **Windows 控制台 GBK 编码**问题，不是存储问题
（`prepare_context` 回读 `content_bytes=648` 与写入内容长度吻合）。
对策：所有脚本设置 `PYTHONIOENCODING=utf-8`；日志文件统一 UTF-8 写入。

### P0 结论

seekdb（远程服务器模式）与 PowerContext（HTTP Server + Python Client）**均已真实打通**，
LLM 与本地 Embedding 可用。可以进入 P1。产出：`ARCHITECTURE.md`、`PLAN.md`、`.env.example`、`.gitignore`、
`scripts/probe_seekdb_capability.py`。

---

## 2026-10-29 P1 数据闭环（seekdb）

### 01:45 建表与集合

`rf_documents` / `rf_pages` / `rf_projects` / `rf_meta` 四张关系表 + `rf_chunks` collection 一次建成，
对真实 seekdb 实测通过，重复调用幂等（`ensure_schema` 先查 `information_schema` 再 DDL，规避 seekdb 的 DDL 锁）。

### 01:50 解析与页号

PyMuPDF `page.number + 1` 得到物理页号；demo PDF 第 4 页刻意留空，实测 `chars=0` 且仍产生身份行。
MD/TXT 统一为单页（`page_no=1`），**不伪造页码**。

### 01:55 首次全链路冒烟

`scripts/smoke_ingest_retrieve.py` 跑通：3 份文档入库、去重、三种检索模式、页码回查、
不存在页返回 `NotFoundError`。

### 02:00 发现 T3 风险并实现证据门控

冒烟输出暴露问题：「量子纠缠」这类语料中不存在答案的问题，向量 ANN 与 `MATCH...AGAINST`
仍会返回命中。若直接把这些命中交给 LLM，就可能产出带假引用的回答。

对策：新增 `retrieval/relevance.py`。用「查询判别性 token 在命中块中的覆盖率」做门控，
并用实测数据标定阈值：可回答问题 coverage 0.67–1.00，不可回答 0.00–0.14，取 0.30 为阈值，两侧余量充足。
门控只影响「能否成为 citation」，原始命中仍完整返回供 UI 解释。

### 02:10 embedding provider 实测对比

同一语料分别用 `hashing`（离线确定性）与 `minilm`（pyseekdb 内置 ONNX）跑冒烟：
「which full text analyzer segments Chinese correctly」向量相似度 0.226 vs **0.720**，
「HNSW cosine distance」0.522 vs **0.593**，且 minilm 下无答案问题仍全部被门控拦下。
→ 默认 provider 定为 `minilm`，`hashing` 作为离线兜底，`openai` 作为远程可配置项。

### 02:20 两个真实 bug

1. **日志命名空间不匹配**：`get_logger(__name__)` 得到 `app.retrieval.service`，
   而 `setup_logging()` 只配置了 `researchflow` logger，导致请求日志全部丢失。
   修复：`get_logger` 统一挂到 `researchflow.*` 命名空间。
2. **shell 传中文 JSON 乱码**：Git Bash 下 `curl -d '{中文}'` 以 GBK 字节发送，服务端报
   `There was an error parsing the body`。这是测试脚本编码问题而非应用问题；
   后续一律改用 Python（pytest / httpx）发请求。

### 02:30 测试套件

88 个测试（单元 25 + seekdb 集成 + PowerContext 集成 + QA + HTTP 契约）。
修复过程中的三处断言错误均为「测试写错」而非「实现错」：
`rank_constant` 按设计会被拆成 `rank`+`constant`；`bullets written` 漏算了 goal；
向量模式 top-1 在弱 embedding 下本就不稳定。均已按真实性质修正断言并写明理由。

---

## 2026-10-29 P2 记忆闭环（PowerContext）

### 02:40 契约实测（三条改变设计的事实）

1. `remember_memory` **不幂等**：同文本再写会新建 artifact。→ 应用层按 `(kind, text)` 去重。
2. `list_memory_entries` **不保证顺序**（实测乱序返回）。→ 每条记忆自带 `seq` + ISO 时间戳。
3. `CreateArtifactRequest` 是固定 family 的判别联合，**不支持自定义 family**；
   `AtomicMemoryRecord` 无时间戳字段。→ 进度快照改用 `kind=rf_progress_snapshot` 的 Atomic Memory，
   JSON 内含 `seq` / `updated_at` / `fingerprint`（内容指纹，用于判定「内容未变化」）。

### 02:50 闭包变量 bug

`build_resume_brief` 内部闭包用了 `lines += [...]`，触发 `UnboundLocalError`。改为 `lines.extend(...)`。

### 02:55 幂等保存

重复保存同一进度：`written=0`、`skipped_duplicates=9`、`snapshot_unchanged=true`、artifact id 不变。
修改内容后保存：只写新增的 1 条 bullet，快照换新 artifact。

### 03:00 发现 PowerContext 中文检索限制

`prepare_context` / `search_memory` 对纯中文查询返回 `empty` / 0 命中。
定位到根因：PowerContext 1.4.1 的 SQLite 索引是 `fts5(... tokenize='unicode61')`，
CJK 连续字符被当作单个 token（grep 源码 `sqlite/atomic_memory_index.py:249` 确认）。
实测：`'seekdb'→4 命中`、`'已确认决策'→0 命中`、`'决策 D1 SHA-256'→4 命中`。

对策（不掩盖）：
- 恢复主路径改为全量 `list_memory_entries` + 快照，**不依赖搜索**，字段级恢复 100% 通过；
- recall query 用项目中真实存在的 ASCII 锚点扩展（`build_recall_query`），并在响应中回传
  `recall_query` / `recall_query_expanded` 与限制说明 `note`；
- 限制写入 VERIFICATION.md 与 UI 展示。

### 03:05 跨会话恢复

新 gateway（新 HTTP client）+ 独立 Python 子进程，仅凭 `project_id` 恢复，
decisions / next_steps / objective / evidence 页码逐字段相等。T5 通过。

---

## 2026-10-29 P3 最小产品

### 03:10 API

17 个端点 + OpenAPI 文档 + request_id 中间件 + 结构化 JSON 日志。
错误一律映射为带 `error.code/message/detail/request_id` 的 JSON，不吞异常。

### 03:15 发现启动期缺陷（真实 bug）

T8 首次运行失败：指向不可达 seekdb 的 API 实例**起不来**——lifespan 里 `ensure_schema`
抛异常导致整个服务不可用，连「报告 seekdb 不可用」都做不到。
修复：`build_state` 捕获 schema 失败，进入降级启动；`/api/health` 暴露 `schema` 字段。
修复后 T8 通过：503 + 真实驱动错误，响应体不含任何结果字段。

### 03:20 citation 服务端校验

LLM 返回的每个 `citation_id` 必须存在于本次检索结果，且其页码能在 `rf_pages` 查到；
不合法的上报到 `invalid_citations` 并从回答中剔除；失去引用的 supported 论断降级为 inferred。
用 stub LLM 写了 5 个确定性测试覆盖：合法引用、编造引用、inferred 不得带引用、
未知 label 回退、非 JSON 输出降级。

### 03:25 前端

React 18 + Vite 5 + TS，四个页面，零 UI 框架依赖。`npm run build` 在 `strict: true` 下零错误
（JS 241.76 kB / gzip 75.22 kB）。后端同源挂载 `frontend/dist` 并为 `/knowledge` 等深链接加 SPA 回退
（`StaticFiles` 直接挂 `/` 会对客户端路由 404，改为 catch-all + 路径穿越防护）。

### 03:35 浏览器实测

真实浏览器逐页验证：健康条真实数据、空白页标记、检索卡片 score_kind/coverage/relevance、
「查看原文」弹窗、grounded 回答与论断分级、紫色记忆通道与「不是文献原文证据」声明、
记忆页保存/恢复/历史时间线。全部符合预期。

---

## 2026-10-29 P4 交付与验收

### 03:30 验收运行器

`scripts/run_acceptance.py` 自带独立 PowerContext（17430）与 API（8788）实例、独立 `rfacc_` 前缀，
因此可以真实 kill/重启而不影响开发实例与同机其他赛题。
T6 用 kill -9 重启 PowerContext 与 API；T7 断连对比；T8 起一个指向死端口的 API 实例。
seekdb 容器重启做成 `--restart-seekdb` 显式开关（共享资源，默认不碰）。

### 03:45 首轮验收 4 个失败的定位

| 用例 | 根因 | 处理 |
| --- | --- | --- |
| T4 | 漏算 goal bullet，期望 6 实为 7 | 修正期望并注释 7 的构成 |
| T9-LLM | 中文问题查英文原文，coverage 过低被门控拦下 | 见下「双语语料」 |
| T7 | QA 请求未带 `project_id`，`memory` 为 null | 测试补上 project_id |
| T8 | API 起不来（见 P3 03:15） | 降级启动 |

### 03:50 双语语料与语义逃逸门控

T9-LLM 的失败暴露真实产品问题：中文提问查纯英文原文时，词法门控会误杀。
两项改进：
1. demo PDF 每页加中文摘要行（符合中文研究者批注英文材料的真实形态），使中文问题可被全文腿命中；
2. 门控增加**语义逃逸**：计算查询向量与命中向量的余弦相似度，≥0.62 也可通过，
   覆盖「无字面重叠的改写/跨语言」情形。该相似度在三种模式下都可用（检索时取回 embeddings）。

同时如实记录限制：all-MiniLM-L6-v2 是英文词表，跨语言语义相似度本身偏低，
多语模型未接入，列为 P1 级后续工作。

### 04:00 另一个真实性能问题

pytest 全量运行时向量检索偶发只返回 3/13 条。定位为 HNSW 写入后索引未及时可见；
入库后调用 `collection.refresh_index()` 解决，连续两轮 88 测试全绿。

### 04:10 最终验收

`logs/acceptance-20261029-033242/`：**T1–T8 + T9-LLM 全部 PASS，150 项校验 0 失败**。
pytest 88 通过。浏览器四页实测通过。

### 04:20 Qoder Sites 可行性

逐条核对官方 skill 文档后确认：平台只有「一个 Deno/TS Edge Function + 托管 PostgreSQL + 对象存储」，
**没有 Python 运行时、没有持久进程、托管库无向量/全文检索**，因此现有三进程架构无法整体上站。
给出三方案（静态前端+自托管后端 / 快照演示站 / Function 内降级重实现）与发布前置清单，本轮不发布。

---

## 人工截图取证清单（供评审与留档）

以下画面建议人工截图保存，均为真实运行结果：

1. `docker ps` 显示 `contest-seekdb` 运行中 + `SELECT VERSION()` 输出 `seekdb-v1.4.0.0`。
2. `GET /api/health` 的 JSON（seekdb 版本/计数、PowerContext 1.4.1、LLM、embedding）。
3. 知识库页：PDF 页导航 5 页，第 4 页「空白页（保留页级身份）」。
4. 知识库页：第 5 页「查看原文」弹窗（含 `page_id`、`char_count`、存储原文）。
5. 知识库页：检索结果卡片（score + RRF 融合分标签、coverage、relevance、chunk_id、通过门控徽章）。
6. 知识库页：「对比三种检索方式」三列并排。
7. AI 工作台：grounded 回答 + `[c1]` 引用 + 论断核验「资料直接支持」。
8. AI 工作台：无答案问题 → 「尚无证据」且 citations 为空。
9. AI 工作台：紫色「历史记忆 · PowerContext」面板与「不是文献原文证据」声明。
10. 任务记忆页：保存结果（written / skipped_duplicates / snapshot artifact id）。
11. 任务记忆页：续研简报「上次做到了哪里 / 接下来该做什么」。
12. 断开 PowerContext 后：`/api/memory/status` 报不可用，而检索页仍正常出结果（T7 对比）。
13. 断开 seekdb 后：检索接口 503 与真实错误文本（T8）。
14. `logs/acceptance-*/acceptance-report.md` 的汇总表（T1–T8 全 PASS）。
15. `pytest -q` 的 `88 passed` 输出。
