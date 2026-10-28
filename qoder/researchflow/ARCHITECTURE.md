# ResearchFlow — Architecture

科研知识与任务连续性助手：带证据的知识库（seekdb）+ 长期任务记忆（PowerContext）+ 科研进度恢复。

本文件记录 **P0 仓库审计的真实结论** 与 **P1 起采用的架构**。所有能力均为实测，未实测的项目显式标注为「未验证」。

---

## 1. 比赛基线（P0 审计）

| 项目 | 值 |
| --- | --- |
| 上游仓库 | `https://github.com/oceanbase/powercontext.git` (`upstream`) |
| 私有仓库 | `https://github.com/chaoyisn/PowerContext.git` (`origin`) |
| 基线分支 | `2026-competition-ecosystem` |
| **基线 SHA（40 位）** | **`d647275c308e09b7b623f322a26f5c4e85734fb0`** |
| 基线 commit | `chore: initialize 2026 competition ecosystem directories` / Chojan Shang / 2026-10-23 |
| origin 与 upstream 一致性 | 两侧 `2026-competition-ecosystem` 同为 `d647275c…`，`git fetch` 后无变化 |
| 基线分支内容 | 仅 5 个占位目录：`dify/ gaode/ minimax/ qoder/ stepfun/`（各含 `.gitkeep`），无源代码 |
| 本项目目录 | `qoder/researchflow/` |
| 工作副本 | `D:/OceanBase/PowerContext-researchflow`（`git worktree`，独立于其他赛题） |

### 1.1 不可改动的资产（红线）

`D:/OceanBase` 下并存多个赛题 worktree，**本项目一律不读改**：

| 路径 | 分支 | 说明 |
| --- | --- | --- |
| `D:/OceanBase/PowerContext` | `master` | 主 worktree，含大量已 staged 的 `competition/**` 改动 |
| `D:/OceanBase/PowerContext-embedding` | `competition/embedding-singleflight-cache` | 其他赛题 |
| `D:/OceanBase/PowerContext-integrated` | `competition/powercontext-integrated` | 其他赛题 |
| `E:/OceanBaseContest/powercontext-*` | `competition/query-aware-evidence-budget` 等 | 其他赛题 |
| `D:/OceanBase/powercontext-pdf-retrieval` | `competition/pdf-page-retrieval` | 其他赛题（独立 clone） |
| `D:/OceanBase/*.py, *.sh, fts-*` | — | 内核赛题的构建/评测产物 |

基线分支上的 `dify/ gaode/ minimax/ stepfun/` 四个目录属于其他生态赛道，**只读，不写**。
本项目所有提交只新增 `qoder/researchflow/**`。

### 1.2 为什么用独立 worktree

主 worktree `D:/OceanBase/PowerContext` 停在 `master` 且有未提交的暂存改动。
在同一目录切分支会破坏用户的在途工作，因此用 `git worktree add --track -b 2026-competition-ecosystem` 新建隔离副本，
基线 SHA 与远端完全一致，且不影响任何其他 worktree。

---

## 2. 依赖可行性实测结论

### 2.1 seekdb

**运行中的真实服务**（非 mock）：

```
容器  contest-seekdb   镜像 oceanbase/seekdb@sha256:4db4961869d5…   Up 31 hours
端口  127.0.0.1:2881 -> 2881/tcp
版本  SELECT VERSION() → 5.7.25-OceanBase seekdb-v1.4.0.0
库    information_schema, mysql, oceanbase, test
账号  root / 空密码 / tenant=sys
数据卷 contest-seekdb-data-20261027 → /var/lib/seekdb（持久化）
```

**pyseekdb SDK 评估结果**（`pyseekdb==1.4.0.post1`，官方 SDK）：

| 模式 | 结论 | 证据 |
| --- | --- | --- |
| 嵌入式 `Client(path=...)` | **Windows 不可用** | `_PYLIBSEEKDB_AVAILABLE=False`；调用抛 `RuntimeError: Embedded Client is not available because pylibseekdb is not available. Please install pylibseekdb (Linux only)`。`pylibseekdb` 仅发布 manylinux wheel |
| 远程服务器 `Client(host=…, port=2881)` | **可用，本项目采用** | `_ClientProxy` → `RemoteServerClient`（pymysql），`list_collections()` 实测返回 `[]` |

`scripts/probe_seekdb_capability.py` 对 **运行中的 seekdb** 实测（每种分析器建表→写入→查询→清理）：

| 能力 | ik | ngram | space |
| --- | --- | --- | --- |
| `create_collection`（HNSW cosine 384 + FULLTEXT） | ok | ok | ok |
| `add`（4 条中英混排文档） | ok 1.19s | ok 0.78s | ok 0.88s |
| `count()` | 4 | 4 | 4 |
| 向量检索 `query(query_texts=…)` | ok，d1 命中首位，distance 0.3753 | ok | ok |
| 中文向量检索 `query("科研任务记忆 决策")` | ok，d4 首位 | ok | ok |
| **混合检索** `hybrid_search(query+knn+rrf)` | ok，RRF 分数 0.0328/0.0161/… | ok | ok |
| 中文全文腿 `where_document.$contains="混合召回"` | ok，**d3 排首位**（中文分词正确） | ok，d3 首位 | ok，d4 首位（无中文分词） |
| 元数据过滤 `where={"tag":{"$eq":…}}` | ok（无匹配返回空，不报错） | ok | ok |

**选定：`ik` 分析器**（中文排序最准），可通过 `RF_SEEKDB_FTS_ANALYZER` 切换。

seekdb 侧已验证的 SQL 能力（用于混合检索与排障）：
`VECTOR(n)` 列、`l2_distance/cosine_distance/inner_product`、
`ORDER BY … APPROXIMATE LIMIT n PARAMETERS(ef_search=k)`、
`CREATE FULLTEXT INDEX … WITH PARSER ik|ngram|space`、`MATCH … AGAINST`。

### 2.2 PowerContext

```
包名  powercontext（非 powermem；powermem 已归档在 origin/archive/powermem）
版本  1.4.1（PyPI 正式发布版，OpenAPI contract 1.4.1）
服务  powercontext server run --host 127.0.0.1 --port 17429
状态  GET /health/ready → {"status":"ready","checks":{"runtime":"ready","database":"ready",…}}
存储  SQLite（默认），数据目录由 POWERCONTEXT_HOME 指定 → services/powercontext-data/
```

实测 SDK 全链路（`powercontext.client.PowerContextClient`）：

| 调用 | 实测结果 |
| --- | --- |
| `get_liveness()` | `ok` |
| `get_server_info()` | `package_version=1.4.1`, `api_contract_version=1.4` |
| `create_scope(idempotency_key=…)` | `scp_52zk5gy7720vv1t67dqm2m99sb`；**同 key 二次调用返回同一 scope_id（幂等成立）** |
| `remember_memory(kind="decision", text=…)` | `changed=True`，`family=atomic-memory`，`revision=1` |
| `search_memory(query=…)` | `mode=text`（未配 embedding 模型 → 走 FTS），命中 1 条，score 0.0164 |
| `list_memory_entries()` | 1 条 |
| `prepare_context(max_bytes=2000)` | `status=ready`，`content_bytes=648`，内容带 `BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1` 信任边界包装 |

**关键契约事实（影响设计，不可臆造）：**

1. master 上 **只有 `scope_id` 一种隔离维度**，`RememberMemoryRequest` / `PrepareContextRequest`
   **没有 `user_id` / `agent_id` / `run_id` / `session_id` 字段**（mem0 风格三元组属于已归档的 powermem）。
   → ResearchFlow 用「一个科研项目 = 一个 Scope」建模。
2. `RememberMemoryRequest.text` ≤ 8192 UTF-8 字节，`kind` 为 1–128 字符自由字符串。
3. `CreateScopeRequest.idempotency_key` **必填**，是重启/重试安全的关键。
4. Artifact 系列 API 提供带 `revision` + ETag 的不可变版本历史，**没有客户端可写的 `updated_at`**（时间戳由服务端拥有）。
   → ResearchFlow 自己保存 `updated_at` 业务字段，写进 memory 文本/Artifact payload。
5. 未配置 generation/embedding 模型时，PowerContext 的自动抽取与向量检索不可用，
   但**显式 `remember_memory` + FTS 检索完全可用**。本项目正是走显式记忆路径
   （符合「用户显式保存研究进度，避免把模型猜测写成事实」的要求），因此这是**设计选择而非降级**。

### 2.3 LLM 与 Embedding

| 组件 | 实测 | 说明 |
| --- | --- | --- |
| LLM | **可用** | `DEEPSEEK_API_KEY` 存在；`deepseek-chat` @ `https://api.deepseek.com` 实测返回 `OK` |
| Embedding（本地） | **可用** | pyseekdb `DefaultEmbeddingFunction` = all-MiniLM-L6-v2 ONNX，384 维，首次下载 86.2MB 后本地缓存，实测 17.5s 完成 |
| Embedding（离线兜底） | 已实现 | `hashing` provider：确定性字符 n-gram 哈希，384 维，零下载 |
| Embedding（远程） | 可配置 | `openai` provider：任意 OpenAI 兼容 `/embeddings` |

> all-MiniLM-L6-v2 使用英文 WordPiece 词表，中文语义向量质量有限。
> 因此检索默认走 **混合模式**：中文召回主要由 seekdb `ik` 全文腿承担，英文/技术术语由向量腿承担。
> 需要更强中文向量时，把 `RF_EMBEDDING_PROVIDER=openai` 指向任意中文 embedding 服务即可，代码无需改动。

---

## 3. 系统架构

```
┌─────────────────────────────  Browser  ─────────────────────────────┐
│  React 18 + Vite + TypeScript                                       │
│  ① 项目总览   ② 知识库   ③ AI 工作台   ④ 任务记忆                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP / JSON (CORS)
┌───────────────────────────────▼─────────────────────────────────────┐
│  FastAPI  (backend/app/api)                                         │
│  /api/health  /api/projects  /api/documents  /api/retrieval         │
│  /api/qa      /api/memory    /api/evidence                          │
├──────────────┬───────────────┬──────────────┬───────────────────────┤
│  ingestion   │   retrieval   │    memory    │        agent          │
│  解析/分块/   │  向量+全文+    │  PowerContext│  证据约束问答 +        │
│  去重/落库    │  混合检索      │  scope/记忆   │  三级结论标注          │
└──────┬───────┴───────┬───────┴──────┬───────┴───────────┬───────────┘
       │               │              │                   │
       │        pyseekdb 1.4.0.post1  │        powercontext.client 1.4.1
       │               │              │                   │
       │        ┌──────▼──────────┐   │        ┌──────────▼──────────┐
       └───────►│     seekdb      │   └───────►│  PowerContext Server│
     pymysql    │ 127.0.0.1:2881  │   HTTP     │  127.0.0.1:17429    │
     (关系表)    │ db=test         │            │  SQLite 持久化       │
                └─────────────────┘            └─────────────────────┘
                                                        │
                                                ┌───────▼───────┐
                                                │ LLM (OpenAI 兼容)│
                                                │ DeepSeek / 任意 │
                                                └───────────────┘
```

**两个后端各司其职、可独立断开验证（对应验收 T7 / T8）：**

- **seekdb = 文献证据**。文档原文、页、chunk、embedding、全文索引。**只有 seekdb 能产生 citation。**
- **PowerContext = 任务记忆**。研究目标、已完成工作、已确认决策、关键证据指针、未解决问题、next_steps。
  **PowerContext 的内容一律标记为「历史记忆」，永不冒充原文证据。**

---

## 4. 数据模型

### 4.1 seekdb — 关系表（pymysql 直连，同一 `test` 库）

所有表名带 `RF_SEEKDB_PREFIX`（默认 `rf_`），不触碰同库其他项目对象。

`rf_documents`

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `doc_id` | `CHAR(64) PK` | 文件内容 SHA-256（hex），**内容寻址，天然去重** |
| `filename` | `VARCHAR(512)` | 原始文件名 |
| `content_type` | `VARCHAR(32)` | `pdf` / `markdown` / `text` |
| `size_bytes` | `BIGINT` | |
| `page_count` | `INT` | PDF 为真实物理页数；MD/TXT 恒为 1 |
| `chunk_count` | `INT` | |
| `title` | `VARCHAR(512)` | |
| `status` | `VARCHAR(16)` | `ready` / `failed` |
| `error_message` | `TEXT NULL` | 失败原因，**不吞异常** |
| `created_at` / `updated_at` | `DATETIME(6)` | |

`rf_pages` — **页级身份记录，空页也保留一行**

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `page_id` | `VARCHAR(96) PK` | `{sha256[:16]}:p{page_no:04d}` |
| `doc_id` | `CHAR(64)` | |
| `page_no` | `INT` | **物理页号，从 1 开始**（PyMuPDF `page.number + 1`） |
| `char_count` | `INT` | |
| `is_empty` | `TINYINT(1)` | 空页标记，仍保留身份行 |
| `content` | `MEDIUMTEXT` | 该页原文，用于「查看原文」 |
| `created_at` | `DATETIME(6)` | |
| — | `UNIQUE KEY (doc_id, page_no)` | 保证重复上传不产生重复页 |

### 4.2 seekdb — pyseekdb Collection `rf_chunks`

`Schema(vector_index=VectorIndexConfig(hnsw=HNSWConfiguration(dimension=384, distance="cosine"),
embedding_function=<provider>), fulltext_index=FulltextIndexConfig(analyzer="ik"))`

| 字段 | 内容 |
| --- | --- |
| `id` | `{sha256[:16]}:p{page_no:04d}:c{chunk_idx:03d}` — **稳定，重复上传幂等** |
| `document` | chunk 原文（同时进 FULLTEXT 索引） |
| `metadata` | `doc_id, filename, content_type, page_no, page_id, chunk_index, char_start, char_end, sha256` |
| `embedding` | 384 维向量（HNSW cosine） |

### 4.3 ID 稳定性保证

`doc_id` 由内容 SHA-256 决定 → 同一文件重复上传得到同一 `doc_id`；
`page_id` / `chunk_id` 由 `doc_id` + 页号 + 块序号决定 → 全部可复算。
重复上传走 **upsert**（`rf_pages` 唯一键 + `collection.upsert`），不产生无限重复数据。

### 4.4 PowerContext 映射

| ResearchFlow 概念 | PowerContext 原语 |
| --- | --- |
| 科研项目 `project_id` | **Scope**，`idempotency_key = "researchflow:project:{project_id}"` |
| 一条研究进度记录 | **Atomic Memory**，`kind` ∈ `goal` / `completed_work` / `decision` / `evidence` / `open_question` / `next_step` |
| 完整进度快照 | **Artifact** `family="research-progress"`，带 `revision` + ETag，天然形成历史版本 |
| 新会话恢复 | `prepare_context(scope_id, query, max_bytes)` + `list_memory_entries` + `get_artifact(latest revision)` |
| 记忆检索 | `search_memory(scope_id, query, limit, mode)` |

进度快照 payload（JSON，服务端不可写字段由 ResearchFlow 自己维护）：

```json
{
  "project_id": "…", "title": "…", "objective": "…",
  "completed_work": ["…"], "decisions": [{"text":"…","confirmed_by":"user","confirmed_at":"…"}],
  "key_evidence": [{"doc_id":"…","page_no":3,"chunk_id":"…","quote":"…"}],
  "open_questions": ["…"], "next_steps": ["…"], "updated_at": "2026-10-29T01:40:00+08:00"
}
```

`key_evidence` 只存 **指向 seekdb 的指针 + 摘录**，不复制原文；
渲染时明确区分「文献证据（seekdb，可点开原文页）」与「历史记忆（PowerContext）」。

---

## 5. 后端模块划分

```
backend/app/
  config.py            pydantic-settings，全部配置来自 .env
  logging_setup.py     结构化日志（JSON 行 + 控制台），带 request_id
  errors.py            领域异常 → HTTP 状态码映射，绝不吞异常
  db/seekdb.py         pymysql 连接 + pyseekdb Client 工厂 + 建表/建集合 + 健康检查
  ingestion/
    hashing.py         SHA-256
    parsers.py         PDF(PyMuPDF 真实物理页) / Markdown / TXT → list[PageText]
    chunking.py        页内分块，保留 char_start/char_end 与页号
    service.py         ingest(): 去重 → 解析 → 落 documents/pages → 向量化 → upsert chunks
  retrieval/
    embeddings.py      provider 抽象：minilm / hashing / openai
    service.py         search(mode=vector|fulltext|hybrid) → hits + citations + 对比信息
  memory/
    client.py          PowerContextClient 封装（连接失败 → 明确报错，不静默降级）
    service.py         ensure_scope / save_progress / restore / list_history
  agent/
    llm.py             OpenAI 兼容客户端；未配 key → 显式 retrieval-only
    prompts.py         证据约束提示词（含禁止编造页码规则）
    service.py         检索 → 组装可追踪上下文 → 生成 → 三级结论标注 + citation 校验
  api/                 FastAPI 路由 + Pydantic schemas + OpenAPI 文档
```

### 5.1 检索模式（可切换、可对比）

| 模式 | 实现 | 说明 |
| --- | --- | --- |
| `vector` | `collection.query(query_texts=…)` | 纯语义 ANN |
| `fulltext` | `collection.hybrid_search(query={where_document.$contains}, knn=None)` | 纯关键词/中文分词 |
| `hybrid` | `collection.hybrid_search(query=…, knn=…, rank={"rrf":{}})` | RRF 融合，默认 |

`/api/retrieval/search?compare=true` 一次返回三种模式结果，供前端并排对比。

### 5.2 问答的三级结论

LLM 被要求对每条论断打标：

| 标记 | 含义 | 约束 |
| --- | --- | --- |
| `supported` | 资料直接支持 | **必须**附至少一个真实 `chunk_id`，服务端会回查校验 |
| `inferred` | 模型推断 | 不得附 citation，需说明推断依据 |
| `no_evidence` | 尚无证据 | 明确说「知识库中没有相关材料」 |

**服务端强制校验**：回答中出现的每个 citation 必须存在于本次检索结果集里，
页码必须能在 `rf_pages` 中查到；不合法的 citation 直接剔除并在响应里报告 `invalid_citations`。
零命中时不进入 LLM，直接返回 `no_evidence`。

---

## 6. 可用性与降级策略（诚实报告，不假装成功）

| 依赖不可用 | 行为 |
| --- | --- |
| seekdb 连不上 | `/api/health` → `degraded`；检索/上传接口返回 **503 + 真实错误**，绝不返回预置答案（T8） |
| PowerContext 连不上 | 问答与检索**照常可用**；记忆接口返回 503；`/api/memory/status` 明确 `available=false`（T7 对比依据） |
| LLM 未配置 | 问答进入 **`mode="retrieval_only"`**，响应里显式标注，只返回检索证据，不冒充模型回答 |
| Embedding 模型下载失败 | 自动回退 `hashing` provider，`/api/health` 报告实际 provider |

---

## 7. 部署形态与 Qoder Sites 边界

本项目为 **本地可独立运行** 的三进程架构：seekdb（Docker）+ PowerContext Server + ResearchFlow FastAPI + Vite 前端。

Qoder Sites 托管的是**静态站点/函数**，不会自动托管本地 FastAPI、seekdb 容器或 PowerContext 进程。
因此第一阶段的结论是：**前端静态资源可发布到 Qoder Sites，后端需要一个可公网访问的部署位置**
（详见 `VERIFICATION.md` 的「Qoder Sites 部署可行性」章节）。本轮不实际发布。
