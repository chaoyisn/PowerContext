# 03 · seekdb 真实读写与检索证据

seekdb 在本项目里承担**唯一的证据存储**角色：文档原文、物理页、分块与向量都存在 seekdb，
检索与引用回查也都走 seekdb。没有本地 JSON 假库，没有预置答案。

| 项目 | 值 |
| --- | --- |
| 实例 | Docker 容器 `contest-seekdb` @ `127.0.0.1:2881`（MySQL 协议） |
| 版本 | `5.7.25-OceanBase seekdb-v1.4.0.0` |
| 库 / 租户 | `test` / `sys`，表前缀 `RF_SEEKDB_PREFIX`（验收跑用 `rfacc_`，互不污染） |
| 客户端 | 官方 `pyseekdb==1.4.0.post1`，**remote server 模式**（嵌入式 `pylibseekdb` 不支持 Windows） |
| 向量索引 | HNSW，384 维，cosine |
| 全文索引 | `ik` 分析器（中文分词实测可用） |
| 混合检索 | `rank={"rrf":{}}`，upsert 后需 `refresh_index()` 才可见 |

## 1. 写入证据（真实落库）

| 证据 | 位置 |
| --- | --- |
| 建表与建集合过程 | `QODER_LOG.md` §P1 01:45；`logs/acceptance-20261029-100634/T1.log` |
| 三份演示文档的 `doc_id`（内容 SHA-256） | `verification/acceptance-run/acceptance-report.md` 运行环境表 `documents_ingested` |
| 页级行数与空白页 | T1：PDF 5 个物理页全部成行，`page_no` 1..5，第 4 页 `is_empty=true`、`char_count=0`；空白页不产生 chunk |
| 去重 | T1：重复上传与强制重灌后行数保持 `{documents:3, pages:7, chunks:13}` |
| 能力实测（分页/索引/RRF 行为） | `scripts/probe_seekdb_capability.py`；结论写入 `ARCHITECTURE.md` §2.1 |

## 2. 读取与检索证据

| 证据 | 位置 | 实际结果 |
| --- | --- | --- |
| 三模检索正确性 | `logs/acceptance-20261029-100634/T2.log`（4211.5 ms） | 3 个问题 × `vector/fulltext/hybrid`，全部定位到正确页码，每条 citation 都能回 seekdb 取到原文 |
| RRF 融合分数 | T9-LLM 用例 | 答案含 `0.0328`，与文档内手写的双第一融合分一致 |
| 无答案不编造 | `T3.log`（4647.5 ms） | 语料外问题不产生 citation |
| 断连真实报错 | `T8.log`（17487.4 ms）+ `api-broken-seekdb.log` | 断开 seekdb 后检索接口返回真实错误，**不返回预置答案** |
| 重启后可查 | `T6.log`（16942.1 ms） | 服务重启后文档、页、chunk、记忆均可查询 |

## 3. 数据模型与门控参数

- 关系表：`rf_documents` / `rf_pages` / `rf_projects`（pymysql 直连同一 `test` 库）。
- 集合：`rf_chunks`（pyseekdb Collection，向量 + 全文 + metadata）。
- ID 稳定性：`doc_id = SHA-256(文件内容)`，`page_id` 由 `doc_id` 复算 → 引用可跨进程复现。
- 证据门控：词面（CJK bigram）覆盖率 ≥ `RF_RETRIEVAL_MIN_COVERAGE=0.30`
  **或** 语义余弦 ≥ `RF_RETRIEVAL_VECTOR_CONFIDENCE=0.62` 才允许标为「资料直接支持」。
  标定过程见 `ARCHITECTURE.md` §5.3–§5.4。

## 4. 已知边界（如实记录）

- 全文检索的中文能力依赖 `ik` 分析器；换 `space` 会显著退化（`ARCHITECTURE.md` §2.1 实测对比）。
- 跨语言提问（英文问、中文原文答）在默认阈值下有 2 条被门控拦下，见 `BENCHMARK.md` B2，未隐藏。
- seekdb 容器与同机其他赛题共享；本项目只写 `rf_` / `rfacc_` 前缀对象，不触碰他人表。
