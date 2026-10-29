# ResearchFlow 验收报告 20261029-100634

生成时间：2026-10-29T10:08:33+08:00

## 运行环境

| 项目 | 值 |
| --- | --- |
| seekdb_endpoint | `127.0.0.1:2881` |
| seekdb_version | `5.7.25-OceanBase seekdb-v1.4.0.0` |
| seekdb_database | `test` |
| seekdb_prefix | `rfacc_` |
| fts_analyzer | `ik` |
| embedding_provider | `minilm` |
| embedding_dimension | `384` |
| powercontext_version | `1.4.1` |
| powercontext_url | `http://127.0.0.1:17430` |
| llm_enabled | `True` |
| llm_model | `deepseek-chat` |
| api_url | `http://127.0.0.1:8788` |
| run_tag | `c83a126f` |
| documents_ingested | `['4d5da56c0b76197ba4b679b9804a3b0cb66fdbeba1e8c67d734dcbf86ee1b74e', '60aa394c2a53076681d95ea42589fc6111112a26277395b306dd82efa0e49bcc', '5bfa03744934e583d25b84784eb3915962167d6f958434f384fce5401c3b3ad3']` |

## 汇总

- 用例总数：9
- PASS：9
- FAIL：0
- SKIP：0

| 编号 | 场景 | 结果 | 耗时(ms) | 日志 |
| --- | --- | --- | --- | --- |
| T1 | 上传 PDF：全部物理页有稳定记录，seekdb 保存正确 | **PASS** | 9365.6 | `logs\acceptance-20261029-100634\T1.log` |
| T2 | 明确问题：检索返回正确资料与真实页码 | **PASS** | 4211.5 | `logs\acceptance-20261029-100634\T2.log` |
| T3 | 不存在答案的问题：不伪造 citation | **PASS** | 4647.5 | `logs\acceptance-20261029-100634\T3.log` |
| T4 | 新建项目并保存已确认决策与 next_steps，PowerContext 实际写入 | **PASS** | 1016.4 | `logs\acceptance-20261029-100634\T4.log` |
| T5 | 结束并重建会话后恢复之前的决策与 next_steps | **PASS** | 2083.6 | `logs\acceptance-20261029-100634\T5.log` |
| T9-LLM | 配置 LLM 后的真实证据问答与 citation 服务端校验 | **PASS** | 3546.4 | `logs\acceptance-20261029-100634\T9-LLM.log` |
| T6 | 重启服务后数据库与记忆仍可查询 | **PASS** | 16942.1 | `logs\acceptance-20261029-100634\T6.log` |
| T7 | 断开 PowerContext，对比任务恢复能力，证明其真实作用 | **PASS** | 41559.8 | `logs\acceptance-20261029-100634\T7.log` |
| T8 | 断开 seekdb，检索接口报真实错误而非返回预置答案 | **PASS** | 17487.4 | `logs\acceptance-20261029-100634\T8.log` |

## T1 — 上传 PDF：全部物理页有稳定记录，seekdb 保存正确

**结果：PASS**

**输入**

```json
{
  "file": "seekdb_hybrid_retrieval_notes.pdf",
  "endpoint": "POST /api/documents/upload"
}
```

**预期**

PDF 报告 5 个物理页；seekdb 的 rf_pages 表恰好 5 行，page_no 为 1..5；第 4 页 is_empty=true 且 char_count=0；page_id 可由 doc_id 复算；空白页不产生 chunk；重复上传去重且不改变行数

**实际**

3 documents ingested into seekdb; PDF has 5 physical page rows including the blank page 4; re-upload and forced re-ingest both leave row counts at {'documents': 3, 'pages': 7, 'projects': 0, 'chunks': 13}

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| upload seekdb_hybrid_retrieval_notes.pdf returns 200 | `True` | `True` | OK |
| upload research_plan.md returns 200 | `True` | `True` | OK |
| upload experiment_log.txt returns 200 | `True` | `True` | OK |
| pdf page_count | `5` | `5` | OK |
| pdf empty_pages | `[4]` | `[4]` | OK |
| page rows returned | `[1, 2, 3, 4, 5]` | `[1, 2, 3, 4, 5]` | OK |
| page ids are recomputable | `["4d5da56c0b76197b:p0001", "4d5da56c0b76197b:p0002", "4d5da56c0b76197b:p0003", "4d5da56c0b76197b:p0004", "4d5da56c0b76197b:p0005"]` | `["4d5da56c0b76197b:p0001", "4d5da56c0b76197b:p0002", "4d5da56c0b76197b:p0003", "4d5da56c0b76197b:p0004", "4d5da56c0b76197b:p0005"]` | OK |
| page 4 is_empty | `True` | `True` | OK |
| page 4 char_count | `0` | `0` | OK |
| the PDF produced chunks | `True` | `True` | OK |
| blank page 4 has no chunks in seekdb | `[]` | `[]` | OK |
| seekdb documents count | `3` | `3` | OK |
| seekdb pages count (5+1+1) | `7` | `7` | OK |
| seekdb chunk count matches the uploads | `True` | `True` | OK |
| seekdb server version contains seekdb | `True` | `True` | OK |
| re-upload flagged as deduplicated | `True` | `True` | OK |
| re-upload keeps the same doc_id | `4d5da56c0b76197ba4b679b9804a3b0cb66fdbeba1e8c67d734dcbf86ee1b74e` | `4d5da56c0b76197ba4b679b9804a3b0cb66fdbeba1e8c67d734dcbf86ee1b74e` | OK |
| row counts unchanged after re-upload | `{"documents": 3, "pages": 7, "projects": 0, "chunks": 13}` | `{"documents": 3, "pages": 7, "projects": 0, "chunks": 13}` | OK |
| forced re-ingest keeps doc_id | `4d5da56c0b76197ba4b679b9804a3b0cb66fdbeba1e8c67d734dcbf86ee1b74e` | `4d5da56c0b76197ba4b679b9804a3b0cb66fdbeba1e8c67d734dcbf86ee1b74e` | OK |
| forced re-ingest does not append rows | `{"documents": 3, "pages": 7, "projects": 0, "chunks": 13}` | `{"documents": 3, "pages": 7, "projects": 0, "chunks": 13}` | OK |

日志：`logs\acceptance-20261029-100634\T1.log`

## T2 — 明确问题：检索返回正确资料与真实页码

**结果：PASS**

**输入**

```json
{
  "questions": [
    "which full text analyzer segments Chinese correctly",
    "RRF rank constant 60 fusion score for a row first in both legs",
    "HNSW cosine distance measured for the hybrid retrieval query"
  ],
  "modes": [
    "vector",
    "fulltext",
    "hybrid"
  ]
}
```

**预期**

fulltext 与 hybrid 模式把正确的页排进前 2 位（demo 语料中 PDF 与 experiment_log.txt 对同一问题都是合法来源，RRF 平分顺序不稳定）；vector 模式在前 3 位内命中；每条 citation 的页码都能在 seekdb 中回查到原文

**实际**

all three modes locate the correct page for every answerable question; every citation resolves to a real stored page

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| vector: seekdb_hybrid_retrieval_notes.pdf p3 surfaced | `True` | `True` | OK |
| vector: p3 within top 3 | `True` | `True` | OK |
| citation c1 page 3 exists in seekdb | `True` | `True` | OK |
| fulltext: seekdb_hybrid_retrieval_notes.pdf p3 surfaced | `True` | `True` | OK |
| fulltext: p3 within top 2 | `True` | `True` | OK |
| citation c1 page 1 exists in seekdb | `True` | `True` | OK |
| hybrid: seekdb_hybrid_retrieval_notes.pdf p3 surfaced | `True` | `True` | OK |
| hybrid: p3 within top 2 | `True` | `True` | OK |
| citation c1 page 1 exists in seekdb | `True` | `True` | OK |
| vector: seekdb_hybrid_retrieval_notes.pdf p5 surfaced | `True` | `True` | OK |
| vector: p5 within top 3 | `True` | `True` | OK |
| citation c1 page 5 exists in seekdb | `True` | `True` | OK |
| fulltext: seekdb_hybrid_retrieval_notes.pdf p5 surfaced | `True` | `True` | OK |
| fulltext: p5 within top 2 | `True` | `True` | OK |
| citation c1 page 5 exists in seekdb | `True` | `True` | OK |
| hybrid: seekdb_hybrid_retrieval_notes.pdf p5 surfaced | `True` | `True` | OK |
| hybrid: p5 within top 2 | `True` | `True` | OK |
| citation c1 page 5 exists in seekdb | `True` | `True` | OK |
| vector: seekdb_hybrid_retrieval_notes.pdf p2 surfaced | `True` | `True` | OK |
| vector: p2 within top 3 | `True` | `True` | OK |
| citation c1 page 2 exists in seekdb | `True` | `True` | OK |
| fulltext: seekdb_hybrid_retrieval_notes.pdf p2 surfaced | `True` | `True` | OK |
| fulltext: p2 within top 2 | `True` | `True` | OK |
| citation c1 page 2 exists in seekdb | `True` | `True` | OK |
| hybrid: seekdb_hybrid_retrieval_notes.pdf p2 surfaced | `True` | `True` | OK |
| hybrid: p2 within top 2 | `True` | `True` | OK |
| citation c1 page 2 exists in seekdb | `True` | `True` | OK |
| compare returns all three modes | `["fulltext", "hybrid", "vector"]` | `["fulltext", "hybrid", "vector"]` | OK |

日志：`logs\acceptance-20261029-100634\T2.log`

## T3 — 不存在答案的问题：不伪造 citation

**结果：PASS**

**输入**

```json
{
  "questions": [
    "这篇文档里有没有关于量子纠缠实验的测量结果",
    "how many calories are in a chocolate brownie recipe"
  ],
  "modes": [
    "vector",
    "fulltext",
    "hybrid"
  ]
}
```

**预期**

启用证据门控后 citations 为空；问答接口 answerable=false、无 citation、结论标记为 no_evidence

**实际**

no citation was produced for any unanswerable question in any mode; QA reports answerable=false with a no_evidence claim

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| vector: gated citations for 这篇文档里有没有关于量子纠缠实验的测量结 | `[]` | `[]` | OK |
| vector: coverage below the gate | `True` | `True` | OK |
| fulltext: gated citations for 这篇文档里有没有关于量子纠缠实验的测量结 | `[]` | `[]` | OK |
| fulltext: coverage below the gate | `True` | `True` | OK |
| hybrid: gated citations for 这篇文档里有没有关于量子纠缠实验的测量结 | `[]` | `[]` | OK |
| hybrid: coverage below the gate | `True` | `True` | OK |
| qa answerable for 这篇文档里有没有关于量子纠缠实验的测量结 | `False` | `False` | OK |
| qa citations for 这篇文档里有没有关于量子纠缠实验的测量结 | `[]` | `[]` | OK |
| qa used_citations for 这篇文档里有没有关于量子纠缠实验的测量结 | `[]` | `[]` | OK |
| qa labels no_evidence for 这篇文档里有没有关于量子纠缠实验的测量结 | `True` | `True` | OK |
| vector: gated citations for how many calories ar | `[]` | `[]` | OK |
| vector: coverage below the gate | `True` | `True` | OK |
| fulltext: gated citations for how many calories ar | `[]` | `[]` | OK |
| fulltext: coverage below the gate | `True` | `True` | OK |
| hybrid: gated citations for how many calories ar | `[]` | `[]` | OK |
| hybrid: coverage below the gate | `True` | `True` | OK |
| qa answerable for how many calories ar | `False` | `False` | OK |
| qa citations for how many calories ar | `[]` | `[]` | OK |
| qa used_citations for how many calories ar | `[]` | `[]` | OK |
| qa labels no_evidence for how many calories ar | `True` | `True` | OK |

日志：`logs\acceptance-20261029-100634\T3.log`

## T4 — 新建项目并保存已确认决策与 next_steps，PowerContext 实际写入

**结果：PASS**

**输入**

```json
{}
```

**预期**



**实际**

project acc-c83a126f bound to scope scp_1pdehwady4r7zmyvxhhka53vak; 6 bullets plus 1 snapshot written to PowerContext and read back through its own API

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| project created | `True` | `True` | OK |
| PowerContext scope_id returned | `True` | `True` | OK |
| scope id looks like a PowerContext scope | `True` | `True` | OK |
| save returns 200 | `True` | `True` | OK |
| saved scope matches | `scp_1pdehwady4r7zmyvxhhka53vak` | `scp_1pdehwady4r7zmyvxhhka53vak` | OK |
| bullets written | `7` | `7` | OK |
| snapshot artifact id returned | `True` | `True` | OK |
| snapshot revision >= 1 | `True` | `True` | OK |
| snapshot unchanged flag | `False` | `False` | OK |
| persisted in PowerContext: D-c83a126f: 默认检索模式为 hybrid（RRF 融合） | `True` | `True` | OK |
| persisted in PowerContext: D-c83a126f: 文档主键使用内容 SHA-256 | `True` | `True` | OK |
| persisted in PowerContext: N-c83a126f: 跑通 T1-T8 | `True` | `True` | OK |
| persisted in PowerContext: N-c83a126f: 输出 Qoder Sites 部署可行性分析 | `True` | `True` | OK |
| history source label | `memory` | `memory` | OK |
| history has rf_decision entries | `True` | `True` | OK |
| PowerContext available | `True` | `True` | OK |
| PowerContext package version | `1.4.1` | `1.4.1` | OK |

日志：`logs\acceptance-20261029-100634\T4.log`

## T5 — 结束并重建会话后恢复之前的决策与 next_steps

**结果：PASS**

**输入**

```json
{
  "project_id": "acc-c83a126f",
  "new_session": "fresh HTTP client + restarted backend process"
}
```

**预期**

仅凭 project_id 就能恢复 decisions 与 next_steps，并生成「上次做到了哪里、接下来该做什么」

**实际**

decisions and next_steps recovered identically over HTTP and from a brand-new client process, using only project_id

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| memory available | `True` | `True` | OK |
| restored decisions | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | OK |
| restored next_steps | `["N-c83a126f: 跑通 T1-T8", "N-c83a126f: 输出 Qoder Sites 部署可行性分析"]` | `["N-c83a126f: 跑通 T1-T8", "N-c83a126f: 输出 Qoder Sites 部署可行性分析"]` | OK |
| restored source label | `memory` | `memory` | OK |
| brief mentions D-c83a126f: 默认检索模式为 hybrid（RRF 融合） | `True` | `True` | OK |
| brief mentions D-c83a126f: 文档主键使用内容 SHA-256 | `True` | `True` | OK |
| brief mentions N-c83a126f: 跑通 T1-T8 | `True` | `True` | OK |
| brief mentions N-c83a126f: 输出 Qoder Sites 部署可行性分析 | `True` | `True` | OK |
| brief has the two required sections | `True` | `True` | OK |
| brief is labelled as memory not evidence | `True` | `True` | OK |
| new process exited cleanly | `True` | `True` | OK |
| new process sees memory | `True` | `True` | OK |
| new process restored decisions | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | OK |
| new process restored next_steps | `["N-c83a126f: 跑通 T1-T8", "N-c83a126f: 输出 Qoder Sites 部署可行性分析"]` | `["N-c83a126f: 跑通 T1-T8", "N-c83a126f: 输出 Qoder Sites 部署可行性分析"]` | OK |

日志：`logs\acceptance-20261029-100634\T5.log`

## T9-LLM — 配置 LLM 后的真实证据问答与 citation 服务端校验

**结果：PASS**

**输入**

```json
{
  "question": "根据文档，一条记录如果在两条腿里都排第一，RRF 分数是多少？",
  "endpoint": "POST /api/qa/ask"
}
```

**预期**

mode=grounded；答案给出 0.0328；至少一条 supported 论断带真实 citation；invalid_citations 为空

**实际**

the live LLM answered from the retrieved evidence, cited a real page and no fabricated citation survived validation

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| mode is grounded | `grounded` | `grounded` | OK |
| LLM produced an answer | `True` | `True` | OK |
| answer contains the documented value 0.0328 | `True` | `True` | OK |
| at least one supported claim | `True` | `True` | OK |
| a real citation was used | `True` | `True` | OK |
| no invalid citations | `[]` | `[]` | OK |
| cited page is the RRF page | `5` | `5` | OK |

日志：`logs\acceptance-20261029-100634\T9-LLM.log`

## T6 — 重启服务后数据库与记忆仍可查询

**结果：PASS**

**输入**

```json
{
  "restart_powercontext": true,
  "restart_researchflow_api": true,
  "restart_seekdb_container": false
}
```

**预期**

PowerContext 进程被杀掉再重启后，记忆仍能按 project_id 恢复；ResearchFlow API 重启后 seekdb 中的文档/页/chunk 仍可查询

**实际**

PowerContext killed and restarted: memory recovered by project_id. ResearchFlow API killed and restarted: seekdb documents/pages/chunks still queryable. seekdb container restart not performed (shared resource, opt-in flag).

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| PowerContext port is down after kill | `True` | `True` | OK |
| memory reported unavailable while down | `False` | `False` | OK |
| PowerContext ready after restart | `True` | `True` | OK |
| memory available after restart | `True` | `True` | OK |
| decisions survived the restart | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | OK |
| resume brief survived the restart | `True` | `True` | OK |
| API ready after restart | `True` | `True` | OK |
| documents survived | `3` | `3` | OK |
| pages survived | `7` | `7` | OK |
| chunks survived | `13` | `13` | OK |
| retrieval works after restart | `True` | `True` | OK |

**备注**

- seekdb 容器未重启：contest-seekdb 与其他赛题共用，自动重启会影响他人。其数据在 Docker volume contest-seekdb-data-20261027 中持久化；用 --restart-seekdb 可显式执行该项验证。

日志：`logs\acceptance-20261029-100634\T6.log`

## T7 — 断开 PowerContext，对比任务恢复能力，证明其真实作用

**结果：PASS**

**输入**

```json
{
  "action": "kill the PowerContext server process",
  "project_id": "acc-c83a126f"
}
```

**预期**

断开后：记忆接口报真实错误、恢复返回 memory_available=false 且无快照；而检索与问答照常工作（因为它们只依赖 seekdb）。恢复服务后记忆立即回来。

**实际**

with PowerContext killed, memory endpoints reported the real outage and returned no snapshot, while retrieval and QA kept working off seekdb; after restart the same decisions were recovered

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| memory available BEFORE disconnect | `True` | `True` | OK |
| decisions BEFORE disconnect | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | OK |
| PowerContext port down | `True` | `True` | OK |
| memory status available=false | `False` | `False` | OK |
| memory status carries a real error | `True` | `True` | OK |
| restore memory_available=false | `False` | `False` | OK |
| restore snapshot is null | `None` | `None` | OK |
| restore entries empty | `[]` | `[]` | OK |
| restore explains the outage | `True` | `True` | OK |
| restore states retrieval still works | `True` | `True` | OK |
| history reports 503 while PowerContext is down | `503` | `503` | OK |
| history error is not a canned answer | `True` | `True` | OK |
| retrieval still returns citations while memory is down | `True` | `True` | OK |
| QA still answers from seekdb while memory is down | `True` | `True` | OK |
| QA reports the memory outage instead of hiding it | `True` | `True` | OK |
| QA still labels the memory channel as memory | `True` | `True` | OK |
| PowerContext ready again | `True` | `True` | OK |
| memory available AFTER reconnect | `True` | `True` | OK |
| decisions recovered AFTER reconnect | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | `["D-c83a126f: 默认检索模式为 hybrid（RRF 融合）", "D-c83a126f: 文档主键使用内容 SHA-256"]` | OK |

日志：`logs\acceptance-20261029-100634\T7.log`

## T8 — 断开 seekdb，检索接口报真实错误而非返回预置答案

**结果：PASS**

**输入**

```json
{
  "action": "start a second API instance pointed at seekdb port 2899 (nothing listening)",
  "port": 8789
}
```

**预期**

健康检查报 degraded 且 available=false 带真实原因；检索/上传/问答返回 503 与真实驱动错误；响应中不含任何检索结果

**实际**

with seekdb unreachable the API reported degraded health and returned 503 with the real driver error on search, upload and QA; no canned results anywhere

**逐项校验**

| 校验项 | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| broken-seekdb API started | `True` | `True` | OK |
| overall status degraded | `degraded` | `degraded` | OK |
| seekdb available | `False` | `False` | OK |
| seekdb error carries the real reason | `True` | `True` | OK |
| capability retrieval disabled | `False` | `False` | OK |
| search returns 503 | `503` | `503` | OK |
| search error code | `seekdb_unavailable` | `seekdb_unavailable` | OK |
| search error names seekdb | `True` | `True` | OK |
| search error preserves the driver reason | `True` | `True` | OK |
| no hits smuggled into the error body | `True` | `True` | OK |
| upload returns 503 | `503` | `503` | OK |
| qa returns 503 | `503` | `503` | OK |
| qa error is not a canned answer | `True` | `True` | OK |
| the healthy instance still retrieves | `True` | `True` | OK |

日志：`logs\acceptance-20261029-100634\T8.log`
