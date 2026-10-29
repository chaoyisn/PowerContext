# VERIFICATION.md — 真实使用证据与验收结果

本文件只记录**实际执行过**的验证。所有数字来自运行产物，未预填、未修饰。
失败与限制同样记录在案。

- 基线分支：`2026-competition-ecosystem`
- 基线 SHA：`d647275c308e09b7b623f322a26f5c4e85734fb0`
- 验证日期：2026-10-29（UTC+8）
- 验收运行目录：`logs/acceptance-20261029-100634/`

---

## 1. seekdb 真实写入 / 检索证据

### 1.1 服务真实性

```
容器   contest-seekdb   镜像 oceanbase/seekdb@sha256:4db4961869d5…
端口   127.0.0.1:2881   数据卷 contest-seekdb-data-20261027 → /var/lib/seekdb
SELECT VERSION()  →  5.7.25-OceanBase seekdb-v1.4.0.0
SELECT @@version_comment → OceanBase 4.3.5.3 seekdb (r1.4.0.0)
库     test（本项目对象全部带 rf_ / rft_ / rfacc_ 前缀，不触碰同库其他项目）
```

`GET /api/health` 实时回读（验收运行 T1 日志）：

```json
{"server_version":"5.7.25-OceanBase seekdb-v1.4.0.0","fts_analyzer":"ik",
 "counts":{"documents":3,"pages":7,"projects":1,"chunks":13}}
```

### 1.2 官方 SDK 使用方式（实测结论）

| 模式 | 结论 | 证据 |
| --- | --- | --- |
| 嵌入式 `Client(path=...)` | **Windows 不可用** | `_PYLIBSEEKDB_AVAILABLE=False`；抛 `RuntimeError: Embedded Client is not available because pylibseekdb is not available. Please install pylibseekdb (Linux only)` |
| 远程服务器 `Client(host=…, port=2881)` | **采用** | `scripts/probe_seekdb_capability.py` 对 ik/ngram/space 三种分析器各跑「建集合→写入→count→向量→中文向量→混合→元数据过滤→清理」，全部 ok |

使用的 SDK 能力（均为真实调用，非自拼 SQL 替代）：
`create_collection(Schema(vector_index=VectorIndexConfig(hnsw=HNSWConfiguration(dimension=384, distance="cosine"), embedding_function=None), fulltext_index=FulltextIndexConfig(analyzer="ik")))`、
`collection.upsert(ids, embeddings, documents, metadatas)`、
`collection.query(query_embeddings=…)`、
`collection.hybrid_search(query={where_document.$contains}, knn={query_embeddings}, rank={"rrf":{}})`、
`collection.get(where=…)`、`collection.delete(where=…)`、`collection.count()`、`collection.refresh_index()`。

### 1.3 写入证据（T1）

- 上传 `demo/seekdb_hybrid_retrieval_notes.pdf` → `page_count=5`，`rf_pages` 恰好 5 行，`page_no=[1,2,3,4,5]`。
- 第 4 页 `is_empty=true`、`char_count=0`，仍保留 `page_id=4d5da56c0b76197b:p0004`。
- 空白页不产生 chunk：按 `page_from=4&page_to=4` 过滤检索返回 `hits=[]`。
- 重复上传 → `deduplicated=true`，`rf_documents/rf_pages/rf_chunks` 行数不变。
- `force=true` 重灌 → 行数仍不变（upsert 而非追加）。
- 计数从数据库回读：`documents=3, pages=7 (5+1+1), chunks=13`。

### 1.4 检索证据（T2 / T3）

| 问题 | vector | fulltext | hybrid |
| --- | --- | --- | --- |
| which full text analyzer segments Chinese correctly | PDF p3 在 top3 | PDF p3 top2 | PDF p3 top2 |
| RRF rank constant 60 fusion score for a row first in both legs | PDF p5 top3 | PDF p5 top1 | PDF p5 top1 |
| HNSW cosine distance measured for the hybrid retrieval query | PDF p2 top3 | PDF p2 top2 | PDF p2 top2 |
| server VERSION() reported by the seekdb baseline environment | PDF p1 top3 | PDF p1 top2 | PDF p1 top2 |

- 每条 citation 的 `page_no` 都通过 `GET /api/documents/{doc_id}/pages/{page_no}` 回查成功（T2 内 28 项校验之一）。
- 不存在答案的问题（量子纠缠 / 巧克力布朗尼卡路里 / 图灵奖年份）在三种模式下
  `apply_gate=true` 后 `citations=[]`，最大 coverage 分别为 0.08 / 0.14 / 0.00，均低于门控阈值 0.30。
- 门控阈值标定（实测，非拍脑袋）：可回答问题 coverage 0.67–1.00；不可回答 0.00–0.14。
- RRF 分数可核对：demo PDF 第 5 页写明 `1/61+1/61=0.0328`，`hybrid_search` 实测返回 0.0328。

### 1.5 seekdb 断连证据（T8）

另起一个 API 实例指向 `127.0.0.1:2899`（无监听）：

- `GET /api/health` → `status=degraded`，`seekdb.available=false` 且带真实驱动错误。
- `POST /api/retrieval/search` → **503**，`error.code=seekdb_unavailable`，`detail.reason` 保留 pymysql 原始异常。
- `POST /api/documents/upload` → 503；`POST /api/qa/ask` → 503。
- 响应体中**不含**任何 `hits` / `citations` 字段，不存在预置答案。
- 同一时刻正常实例检索照常返回命中，证明失败是局部的。

---

## 2. PowerContext 真实写入 / 恢复证据

### 2.1 服务真实性

```
powercontext[cli,server]==1.4.1（PyPI 正式版）
powercontext server run --host 127.0.0.1 --port 17429 --no-env-file
GET /health/ready → {"status":"ready","checks":{"runtime":"ready","database":"ready",…}}
包名是 powercontext；powermem 已归档在 origin/archive/powermem，未使用
```

### 2.2 契约实测（影响设计的事实）

- `create_scope(idempotency_key=…)` 幂等：同 key 二次调用返回同一 `scope_id`（T4/T7 校验）。
- `remember_memory` **不幂等**：同文本再写会新建 artifact（实测 `changed=True`、新 `art_…`）。
  → ResearchFlow 在应用层对 `(kind, text)` 去重，重复保存 `written=0`、`skipped_duplicates=N`。
- `list_memory_entries` **不保证插入顺序**（实测乱序）→ 每条记忆自带 `seq` 与 ISO `updated_at`。
- `AtomicMemoryRecord` 无时间戳字段；`CreateArtifactRequest` 是固定 family 判别联合，
  **不支持自定义 family** → 进度快照以 `kind=rf_progress_snapshot` 的 Atomic Memory 存储，
  内含 `seq` / `updated_at` / `fingerprint`。
- SQLite 后端 `fts5 tokenize='unicode61'`：纯中文查询 0 命中，含 ASCII token 的查询正常命中
  （实测 `'已确认决策'→0`、`'seekdb'→4`、`'决策 D1 SHA-256'→4`）。
  → 恢复主路径走全量 `list_memory_entries`，不依赖搜索；并用真实存在的 ASCII 锚点扩展 recall query，
  UI 与 API 均展示该限制说明（`prepared_context.note`）。

### 2.3 写入证据（T4）

- 创建项目 → `scope_id=scp_…`（真实 PowerContext scope）。
- 保存 7 条 bullet（1 goal + 2 decision + 2 next_step + 1 completed_work + 1 open_question）+ 1 快照。
- 通过 PowerContext 自己的 `list_memory_entries` 回读：`rf_decision` / `rf_next_step` /
  `rf_progress_snapshot` 均在；每条决策与 next_step 文本逐字命中。
- 每条记录 `artifact.family="atomic-memory"`、`artifact_id` 以 `art_` 开头、`revision>=1`。
- 重复保存：`written=0`、`snapshot_unchanged=true`、`snapshot_artifact_id` 不变。
- 修改内容后保存：`written=1`（只写新增 bullet）、`snapshot_unchanged=false`、新 artifact。

### 2.4 跨会话恢复证据（T5）

- 新 HTTP 会话 + **全新客户端进程**（独立 Python 子进程）仅凭 `project_id` 恢复：
  `decisions` / `next_steps` / `objective` / `key_evidence[0].page_no` 与保存值逐字段相等。
- 续研简报包含「上次做到了哪里」「接下来该做什么」两节，并带
  「以上全部来自 PowerContext 历史记忆，不是文献原文证据」声明。
- 所有记忆条目 `source="memory"`；文献证据 `source="document"`，两者在 API 与 UI 中分通道标记。

### 2.5 重启持久化证据（T6）

- **kill -9 式杀掉** PowerContext 进程再重启：同一 `project_id` 恢复出完全相同的 decisions。
  （SQLite WAL 在异常终止后自动恢复，实测成立。）
- 杀掉并重启 ResearchFlow API：seekdb 计数 `documents/pages/chunks` 与重启前一致，检索照常。
- **seekdb 容器未自动重启**：`contest-seekdb` 与同机其他赛题共用，自动重启会影响他人。
  其数据在命名卷 `contest-seekdb-data-20261027` 中持久化；
  `run_acceptance.py --restart-seekdb` 可显式执行该验证（本轮未执行，已在报告备注中说明）。

### 2.6 断连对比证据（T7）

杀掉 PowerContext 后：

| 能力 | 表现 |
| --- | --- |
| `GET /api/memory/status` | `available=false` + 真实错误文本 |
| `GET …/memory/restore` | `memory_available=false`、`snapshot=null`、`entries=[]`，简报写明「PowerContext 当前不可用…文献检索与问答不受影响」 |
| `GET …/memory/history` | **503** + 真实错误，非 canned 响应 |
| `POST /api/retrieval/search` | **照常返回 citation**（只依赖 seekdb） |
| `POST /api/qa/ask` | 照常 grounded 回答，且 `memory.memory_available=false`、`memory.source="memory"` 显式上报断连 |

重启后：同一 decisions 立即恢复。→ PowerContext 的作用是**真实且独立**的：它只承载任务记忆，
断开它不影响证据链路；而任务恢复能力完全依赖它。

---

## 3. 测试与验收汇总

### 3.1 pytest（149 个，全部通过）

```
cd backend && .venv/Scripts/python -m pytest tests/ -q
→ 149 passed（V2 末轮 45.36s）
```

| 文件 | 覆盖 |
| --- | --- |
| `tests/test_parsing.py` | 哈希/路径安全/分块偏移/解析/相关性门控/记忆模型（单元） |
| `tests/test_seekdb_integration.py` | T1/T2/T3/T8（对真实 seekdb） |
| `tests/test_memory_integration.py` | T4/T5/T7（对真实 PowerContext） |
| `tests/test_memory_zh.py` | B1 中文记忆召回回归（独立数据集驱动） |
| `tests/test_qa.py` | citation 服务端校验、降级、仅检索模式、记忆分通道 |
| `tests/test_security.py` | C3 上传/解析 DoS/提示注入/SQL 注入/隔离/CORS/密钥 |
| `tests/test_heldout.py` | C2 保留集：多空白页 PDF、跨文档定位、并发、断连重连、LLM 重试 |
| `tests/test_api.py` | HTTP 契约、错误码、OpenAPI、上传校验、过滤校验 |

### 3.2 验收运行（T1–T8 + T9，全部 PASS）

报告与逐用例日志已随仓库提交，位于 `verification/acceptance-run/`
（`acceptance-report.md` 人读、`acceptance-report.json` 机读、`T1.log … T9-LLM.log` 逐用例日志、
`powercontext*.log` / `api*.log` 服务日志）。重新运行会另写一份到 `logs/acceptance-<时间戳>/`。

| 编号 | 场景 | 结果 | 校验数 | 耗时 |
| --- | --- | --- | --- | --- |
| T1 | 上传 PDF，全部物理页有稳定记录，seekdb 保存正确 | **PASS** | 20 | 5.9s |
| T2 | 明确问题 → 正确资料与真实页码 | **PASS** | 28 | 2.3s |
| T3 | 无答案问题 → 不伪造 citation | **PASS** | 20 | 2.1s |
| T4 | 新建项目保存决策与 next_steps，PowerContext 实际写入 | **PASS** | 17 | 0.6s |
| T5 | 结束并重建会话恢复决策与 next_steps | **PASS** | 14 | 2.3s |
| T6 | 重启服务后数据库与记忆仍可查询 | **PASS** | 11 | 15.1s |
| T7 | 断开 PowerContext 对比任务恢复能力 | **PASS** | 19 | 19.5s |
| T8 | 断开 seekdb 报真实错误而非预置答案 | **PASS** | 14 | 15.8s |
| T9-LLM | 真实 LLM 证据问答 + citation 校验（附加用例） | **PASS** | 7 | 2.4s |

合计 **150 项校验，0 失败**。

T9-LLM 实测输出（DeepSeek `deepseek-chat`）：

```
answer: 根据文档，一条记录如果在两条腿里都排第一，RRF 融合分数是 1/61 + 1/61 = 0.0328 [c1]。
claims: 2 × supported，均引用 c1（seekdb_hybrid_retrieval_notes.pdf 第 5 页）
invalid_citations: []
```

### 3.3 浏览器实测（人工可复现）

用真实浏览器访问 `http://127.0.0.1:8787/`（后端同源提供前端构建产物）逐页验证：

- 对话首页 `/`：三段式外壳（左项目 / 本机会话侧栏、中首页与提问框、右 Evidence / Context 面板）；
  侧栏底部实时展示 seekdb / PowerContext / LLM 状态点。
- 知识库 `/knowledge`：文档卡片展开页导航显示 5 个物理页且第 4 页标记「空白页（保留页级身份）」；
  检索结果卡片含 score+score_kind、coverage、relevance、chunk_id、门控徽章，并同步到右侧「本轮检索命中」；
  「查看原文」弹窗显示 seekdb 存储原文与 `page_id`/`char_count`。
- 证据问答 `/workbench`：grounded 回答带 `[c1]` 可点引用；论断核验「资料直接支持：2」；
  记忆面板紫色通道并带「不是文献原文证据」声明。
- 研究进度 `/memory`：PowerContext 状态横幅、保存表单（含从检索结果选择证据）、
  自动恢复的续研简报、按类型分组的研究卡片与历史时间线（seq / artifact_id / revision / state）。
- 验证 `/verification`：seekdb 真实版本/计数、PowerContext 1.4.1、LLM、embedding 的实时健康，
  以及 T1–T9 验收与 pytest 真实日志。

响应式（automated，`scripts/capture_screenshots.cjs` 于 390×844 无头 Chromium 逐路由断言）：
侧栏与证据面板在 ≤900px 折叠为抽屉，六个路由 `documentElement.scrollWidth == clientWidth`
且主区内无横向滚动容器溢出，全部通过；同时截图 2 张移动端页面（`s8`/`s9`）。
真实手机上的手感（human）未做逐页人工复核。

---

## 4. 已知限制（如实记录）

1. **嵌入式 seekdb 在 Windows 不可用**（官方 wheel 仅 manylinux）。Linux/macOS 可设 `RF_SEEKDB_MODE=embedded`。
2. **PowerContext 纯中文记忆检索弱**（fts5 unicode61）。恢复不依赖搜索；限制在 UI/API 中展示。
3. **默认 embedding 为英文词表**：中文查询命中纯英文原文时语义相似度低。
   缓解：双语 demo 语料、hybrid 默认、门控含语义逃逸（`vector_confidence=0.62`）、
   `RF_EMBEDDING_PROVIDER=openai` 可换任意中文 embedding 服务。
4. **RRF 平分时顺序不稳定**：demo 语料中 PDF 与 experiment_log.txt 对同一问题都是合法来源，
   故 T2 对 fulltext/hybrid 断言「前 2 位」而非「第 1 位」。
5. **HNSW 写入后需 refresh**：不刷新时新写入向量可能不被 ANN 立即召回
   （实测 13 chunk 只返回 3）。已在入库后调用 `collection.refresh_index()`。
6. **seekdb 容器重启未自动验证**（共享资源），提供 `--restart-seekdb` 显式开关。

---

## 5. Qoder Sites 公开部署可行性（本轮不发布）

结论依据：Qoder Sites 官方 skill 文档（`sites-building/`、`sites-hosting/` 全部 md 逐条核对）。

### 5.1 平台能力边界（文档原文结论）

| 能力 | 结论 |
| --- | --- |
| 静态 SPA（Vite 构建产物） | **支持**，是首要模型；`prepare_site.webDirectory` 指向含 `index.html` 的专用目录；SPA 深链接有 `spa` 开关 |
| 服务端运行时 | **仅一个** `app` Edge Function，TypeScript / Deno；`Deno.serve` HTTP handler |
| Python / FastAPI | **不支持**。文档明确「不要假设 Node 服务器、框架 SSR 进程或部署期包安装可用」；Python 只作为本地静态预览的可选回退 |
| 持久进程 / 常驻服务 | **不支持**。「实现 HTTP handler，而不是 Express 启动命令或持久后台进程」；冷启动、多实例、无共享进程内存；无 cron/调度器 |
| 数据库 | 托管 **PostgreSQL**，DDL 为受限子集（无触发器/自定义函数/表达式索引/数组/varchar(n)）；**无向量与全文检索能力**（全树 grep 零命中）；仅 Function 可访问 |
| 对象存储 | 支持，Function 中介 |
| Secrets | 支持（≤100 个/次，名称正则受限，保留前缀 `QODER_`/`SUPABASE_`/`POSTGRES_`/`DATABASE_URL`） |
| Function 出站网络 | **未文档化是否允许任意出站**；文档化模式是「固定、可信、HTTPS、配置在 Secret 中的目的地」；localhost/LAN 不可达 |
| 发布可见性 | 新站点默认 **private**；公开需额外授权 + `confirmPublic: true`；平台子域名寻址，无自定义域名文档 |
| 保留路由命名空间 | `/api`、`/functions`、`/storage`、`/rest/v1`、`/supabase` 等被平台保留 |

### 5.2 对本项目的直接结论

**ResearchFlow 的当前三进程架构（FastAPI + seekdb + PowerContext）无法整体部署到 Qoder Sites。**
原因不是配置问题而是平台模型问题：没有 Python 运行时、没有持久进程、没有 MySQL 协议数据库、
托管 PostgreSQL 没有向量/全文检索。

### 5.3 可行的三种接入方案（按推荐度）

**方案 A（推荐）：静态前端上 Sites + 后端留在可公网访问的自托管位置**
- `frontend/dist` 作为 `webDirectory` 发布；前端改为通过 Secret 配置的固定 HTTPS 基址调用后端。
- 需要一个公网可达的后端宿主（云 VM / 容器服务），其上跑 FastAPI + seekdb + PowerContext。
- 注意：前端现在调用 `/api/...`，而 `/api` 是 Sites 保留命名空间 → 需把前端 API 基址改为绝对 URL
  （`VITE_API_BASE_URL` 已支持），或经 Edge Function 反向代理到固定 HTTPS 目的地。
- 风险：Function 出站是否允许未文档化，需实测一次最小代理后再承诺。

**方案 B：演示站点 = 静态前端 + 只读快照数据**
- 把一次真实运行的检索/问答/记忆结果导出为 JSON 快照，前端在 Sites 上以「演示模式」展示，
  明确标注「快照数据，非实时后端」。适合作为比赛展示页，但不能冒充在线产品。

**方案 C：在 Edge Function 内重实现一个降级版后端**
- 用托管 PostgreSQL 存文档/页/chunk 元数据与记忆；**但无向量与全文索引**，
  只能做客户端过滤式「检索」，不满足「真实向量+全文混合检索」的赛题要求。不推荐。

### 5.4 发布前必须满足的条件（清单）

1. 选定方案并实测 Function → 自托管后端的 HTTPS 出站（方案 A 的前提）。
2. 前端 API 基址改为绝对 URL 或 Function 代理路径，避开 `/api` 保留命名空间。
3. `prepare_site` → `get_publish_status`（读 `artifactReady`/`dependenciesReady`/`blockers`）→ `publish_site`。
4. 公开可见需单独授权与 `confirmPublic: true`；默认保持 private 直到人工确认。
5. 密钥（LLM key 等）只进 Sites Secrets，不进前端包、不进仓库。
6. 发布内容需通过平台内容政策审查。

**本轮未执行任何发布操作**，符合赛题「第一阶段只完成部署可行性分析及站点方案」的要求。

---

## 6. 工程风险与修复优先级

| 优先级 | 风险 | 现状 / 对策 |
| --- | --- | --- |
| P0 | seekdb 容器非自启，机器重启后服务不可用 | `RUN.md` 已写明 `docker start contest-seekdb`；健康检查会明确报 degraded |
| P0 | 共享 seekdb 被误操作 | 全部对象带前缀；`reset_store.py` 拒绝清理不带前缀的对象；测试用 `rft_`/`rfacc_` |
| P1 | 中文记忆检索弱（PowerContext unicode61） | 已用全量读取兜底 + UI 说明；根治需把 PowerContext 指向 seekdb/OceanBase 后端（`POWERCONTEXT_SERVER_DATABASE_KIND=oceanbase`），未实测，列为后续工作 |
| P1 | 跨语言向量检索弱 | 双语语料 + 语义逃逸门控 + 可换 embedding provider；多语模型未接入 |
| P2 | RRF 平分顺序不稳定 | 断言与 UI 均已按「前 2 位」表述；如需稳定可在应用层加 tie-break（coverage 优先） |
| P2 | LLM 供应商瞬时故障 | 已加 3 次指数退避重试，仅对传输/服务端错误重试 |
| P3 | 前端窄屏未逐页截图验证 | CSS 媒体查询已实现；建议人工补一轮移动端走查 |
| P3 | Qoder Sites 出站未文档化 | 方案 A 前需一次最小实测 |

---

## 7. V2 增量验证（2026-10-29 第二轮）

### 7.1 全新环境复现（C1）

`scripts/fresh_env_e2e.py` 在**不依赖开发机任何缓存/数据库/预启动服务**的条件下跑通评审旅程：
新建两个 venv（从 pyproject 固定版本安装）、新建 seekdb 容器（端口 2890、独立匿名卷）、
新建 PowerContext 数据目录（端口 17431）、新建 API（端口 8790、前缀 `rffresh_`），
然后上传样例 → 查询并回查第 5 页 → 建项目绑 Scope → 保存进度 → **独立进程恢复** → 清理容器与卷。

结果：**23/23 步 PASS**（68.4 s），原始记录 `logs/fresh-env-20261029-222030.json`（封版当晚 22:20 重跑）。
23 步 = 评审旅程本体 21 步 + 端口前置检查 + 容器与卷清理；报告里的 `full reviewer journey completed`
一行写的是 `21/21 steps passed`（清理步骤在其之后才追加）。
同日 09:44 的一次为 22/22（`logs/fresh-env-20261029-094431.json`）；22:12 的一次失败也已保留
（`logs/fresh-env-20261029-221217.json`，10/11）——本机另一进程恰好占用了 8790 端口，而旧版就绪判据
把「任何 <500 的响应」当作服务已就绪，于是错误被推迟成 `KeyError: 'components'`。
已修：端口占用前置检查（新增一步，故总数从 22 变 23）、就绪判据要求响应体含 `components`、
三个端口与容器名可用 `RF_FRESH_SEEKDB_PORT` / `RF_FRESH_PC_PORT` / `RF_FRESH_API_PORT` / `RF_FRESH_CONTAINER` 覆盖。
关键行：

```
[PASS] fresh seekdb accepts connections — 5.7.25-OceanBase seekdb-v1.4.0.0
[PASS] fresh seekdb holds the imported corpus — {"documents": 3, "pages": 7, "projects": 0, "chunks": 13}
[PASS] query returns the expected page — top=seekdb_hybrid_retrieval_notes.pdf p5
[PASS] save progress writes to fresh PowerContext — written=3, snapshot_artifact_id=art_a1…
[PASS] a separate process restores the saved progress — decisions/next_steps 与保存值逐字相等
[PASS] fresh seekdb container and volume removed — rf-fresh-seekdb
```

### 7.2 中文记忆检索修复前后（B1）

同一数据集、同一 PowerContext 实例：

| 路径 | 修复前 | 修复后 |
| --- | --- | --- |
| PowerContext `search_memory` | 6/10，负例误报 1/1 | 不变（平台行为，如实保留） |
| ResearchFlow CJK 匹配 + kind 定向读取 | —（不存在） | hit@3 **10/10**，hit@1 8/10，负例 0/1 |

定位结论：存储层无损（全量读取 100%），瓶颈在召回层。原始数据 `logs/bench-memory-zh-*.json`。

### 7.3 中英混合检索（B2）

- 跨语言相似度实测：multilingual 0.792 / 0.813（翻译句对），minilm 0.174 / 0.442；负例两者均 ≤0.093。
- 默认阈值 0.62：三 provider R@1 0.78、负例误报 0/2。
- multilingual + 0.28：R@5 1.00、MRR 0.87，但负例误报 1/2（PostgreSQL/MVCC 查询）。
- 仍未覆盖：2 条「英文改写问中文原文」在 0.62 下被门控拦下——记录为能力边界，不修饰。
  原始数据 `logs/bench-retrieval-20261029-091422.json`。

### 7.4 安全审计新增发现（C3）

**SDK 层过滤绕过（已修复）**：实测 seekdb v1.4.0.0 + pyseekdb 1.4.0.post1 的
`hybrid_search` 全文腿对含 SQL 元字符的 metadata 过滤值会**静默丢弃整个 where 子句**
（恶意值与无过滤结果完全一致：5 hits / 2 docs；向量腿参数化正常：0 hits）。
修复：`build_where` 对 `doc_id`（64 位 hex）与 `content_type`（白名单）做 fail-closed 校验，非法返回 422。
回归：`test_metadata_filters_fail_closed_on_hostile_values`、`test_search_rejects_malformed_filter_values`。
其余 14 项审计结论见 `SECURITY.md` §2。

### 7.5 工作流提效（D）

见 `BENCHMARK.md` §3 与 `logs/bench-workflow-20261029-095416.json`。要点：
W1 基线 6/6 定位但**不产出任何引用对象**且耗时不含人工阅读；ResearchFlow top1 5/6、top5 5/6、
可点引用 5/6，1 条需人工修正（正确块排第 6）。W2 基线从手工笔记恢复 5/7（漏记 2 条）、
无结构无来源指针不可跨会话；ResearchFlow 7/7 逐字段精确、独立进程恢复、0 修正。

### 7.6 展示站验证与正式发布

**本地验证**：`scripts/verify_site.cjs`（Playwright 无头）：证据数据渲染（9/9 PASS、149 passed、9 行验收表）、
10 张截图全部加载、锚点跳转与整页刷新正常、390px 横向溢出 0px、无 console/pageerror。
（2026-10-29 前端 UI 重构后重跑：`screenshots: 10 broken: 0`、`mobile h-overflow px: 0`、`failed requests (>=400): 0`。）
预览图 `site/preview/site-desktop.png`、`site/preview/site-mobile.png`。

**云端已正式发布并公开访问**（V3，2026-10-29）：<https://researchflow-5esfsogn38f.qoder.zone>
`published=true`、`readiness=publication_completed`、`operation.committed=true`、`access_mode=public`
（公开切换经用户明确授权）。未登录验证：无凭据 curl 根路径与全部静态资源 200、深链 200、
不存在路径 404；无头浏览器全新上下文（无 cookie）`failed requests (>=400): 0`、9 张截图 `broken=0`、
390px 横向溢出 0px、无 console/pageerror。线上整页截图与逐项清单：
`verification/site-public/`（`PUBLISH_VERIFICATION.md`、`site-desktop.png`、`site-mobile.png`）。
发布过程与能力边界见 `SITE_DEPLOYMENT.md` §5。V2 期间的 `sites_unavailable` 阻塞已解除，
其原始实测记录保留在 `SITE_DEPLOYMENT.md` §1 作为过程证据。

## 8. 前端 UI 重构后的真实浏览器交互验收（2026-10-29 第三轮）

执行方式：`scripts/verify_interactions.cjs`（Playwright 驱动真实 Chromium，对着真实后端
`127.0.0.1:8787` + seekdb + PowerContext + DeepSeek 跑真实手势）。**不检查 mock、不只看 DOM**：
每条断言都拿页面渲染出来的文本与脚本拦截到的接口 JSON 逐字比对，因此"界面有东西"不等于通过。

结果：**30 组全部通过 / 0 失败**（`verification/browser-acceptance/interactions.json`，
运行日志 `interactions-run.log`，记录于 2026-10-29 18:59 +08:00，标注 **automated**）。
本轮界面做了减法（首页只留问题入口、输入区次要控件收进「选项」、侧栏去掉重复说明），
能力一项未删，因此新增一组用例专门验证渐进披露本身。

| 组别 | 断言的真实行为 |
| --- | --- |
| 外壳 | 侧栏 264→68→264px 折叠且主区变宽 >180px；证据面板第三列压到 0px 再恢复 |
| 输入区 | Shift+Enter 只插换行不发请求；`isComposing` 的 Enter 不发送；输入框长高到 240px 上限后内部滚动 |
| 完整问答 | Enter 触发真实 `/api/qa/ask` → 加载态与「生成中」禁用态 → 论断区块渲染文本与接口 `claims[]` 逐条一致（本轮 2/2 命中，mode=grounded） |
| 引用链路 | 按接口 `citation_id` 选 chip → 点击后面板条目进入高亮 → 打开原文页并核对 `page_id` 与 seekdb 返回正文一致 → Esc 关弹窗且不连带关掉面板 |
| 滚动 | 向上翻看时不被拉回底部，「回到最新消息」出现且点击后真正回到底部 |
| 仅检索 | 走 `/api/retrieval/search`，命中数与门控结果与接口一致，且**没有**打 LLM |
| 渐进披露 | 折叠「选项」后 `#qa-project` 与回答方式确实从 DOM 收起，但非默认设置仍写在按钮文案上；重新展开后勾选与分段选择保持原值，切回问答后按钮同步 |
| 上传 | 真实上传新文档：`doc_id`/页数/chunk 数与接口一致、列表可见、随后删除；重复上传命中去重 |
| 记忆 | 显式保存写入 PowerContext 且条数与接口一致；跨会话凭 `project_id` 取回同一条；相同内容重复保存命中 `snapshot_unchanged` 并给出「内容未变化」文案 |
| 错误反馈 | 拦截 `/api/qa/ask` 制造失败 → 页面给出可读错误 + 重试按钮 → 点重试真的重新发请求并渲染成功、错误消失 |
| 深色模式 | 切换生效、刷新保持，正文对比度实测 **5.27:1**（≥ WCAG AA 4.5:1） |
| 移动端 | 390px 侧栏/证据面板为抽屉，遮罩点击与 Esc 都能关；视口收缩（键盘弹起）时输入框仍完整可见；输入字号 16px 不触发 iOS 聚焦缩放 |
| 响应式 | 390 / 768 / 1280 / 1920 四宽度 × 6 路由整页无横向溢出（容器内滚动单独统计，不误判为溢出）；1920px 消息列与输入框同宽居中 |
| 路由 | 6 个路由深链直达与刷新都落在同一页；顶栏来回切换不残留抽屉 |
| 运行时健康 | 全程 0 未捕获 JS 错误、0 非预期 console error、0 非预期 4xx/5xx；刷新后本机会话仍在且标注「最近会话 · 本机」 |

同批产出：`verification/browser-acceptance/responsive/` 48 张真实截图（6 路由 × 4 宽度 × 明暗两套，
`manifest.json` 记录每张的 `scrollWidth/clientWidth`，溢出 0 张）；
`verification/browser-acceptance/compare/` 重构前后对比图与线上站点当前快照。

过程事实（不修饰）：本轮此前的一次运行中，上游 LLM 对 `/api/qa/ask` 返回过 503（后端重试到上限后
如实透传）。当时问答轮次未提交，导致后续 3 组依赖该轮结果的用例连带失败。脚本据此改为按同一手势
重发（最多 3 次）并把这类上游 5xx 从「前端交互失败」里单独摘出来计数——应用侧的错误卡+重试路径本身
由「错误反馈」用例单独断言，第三方抖动不计入前端缺陷。上表为修复后完整重跑的结果。
