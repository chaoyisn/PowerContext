# SECURITY.md — 公开部署安全说明与审计结果

审计范围：`qoder/researchflow/` 全部后端、前端与脚本。
审计方式：代码审查 + `backend/tests/test_security.py`（25 项回归）+ 实测探针。
所有结论都标注了证据位置；未修复项在「剩余风险」中如实列出。

---

## 1. 威胁模型与部署边界

ResearchFlow 后端是一个**本地单用户工具**：API 默认绑定 `127.0.0.1`，**没有内置认证**。
因此安全立场是：

- 本地/内网使用：当前控制足够。
- **公网暴露：禁止直接暴露 FastAPI**。若要做在线体验，必须前置网关（TLS、认证、限流），
  或采用方案一（静态展示站，不连后端）。见 `SITE_DEPLOYMENT.md` §3。
- Qoder Sites 展示版是纯静态站点，不携带任何密钥、不连接任何数据库。
- **该展示站已正式发布并公开访问**（<https://researchflow-5esfsogn38f.qoder.zone>，
  `access_mode=public`，经用户明确授权）。公开面仅为比赛展示材料：真实运行截图、
  由真实验收/测试产物导出的 `data/evidence.json`、静态 CSS/JS。上传前已扫描确认
  不含密钥、凭据、完整 Qoder UID 或任何用户上传的私有文档内容；站点无后端、无表单、
  无写入接口，因此不存在匿名用户访问他人记忆或文档的路径。

## 2. 审计结果

| # | 领域 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 上传扩展名白名单 | 仅 `.pdf/.md/.markdown/.txt`，其余 415 | `test_upload_validation_enforces_allowlist_and_size`、`test_upload_rejects_disallowed_extension` |
| 2 | 上传大小上限 | 默认 20MB，超限 413；流式读取前校验长度 | 同上 + `RF_UPLOAD_MAX_BYTES` |
| 3 | 文件名路径穿越 | `safe_filename` 剥离 POSIX/Windows 路径、UNC、空字节、RTL 覆盖符；**上传内容不落盘**，仅内存解析 | `test_filename_sanitisation_strips_every_path_component`（9 个payload） |
| 4 | PDF 解析 DoS | 页数上限 1000、抽取字符上限 8,000,000，超限拒绝入库 | `test_pdf_page_count_cap_rejects_hostile_documents`、`test_pdf_text_volume_cap` |
| 5 | SQL 注入（自有 SQL） | 全部语句参数化；恶意 doc_id 作为标识符查询返回 404 且表完好 | `test_sql_injection_in_identifiers_is_inert`（4 个 payload） |
| 6 | **SDK 层过滤绕过（已修复）** | 实测发现：seekdb 全文腿对含 SQL 元字符的 metadata 过滤值会**静默丢弃整个 where 子句**（恶意值表现与无过滤完全一致；向量腿参数化正常）。修复：`build_where` 对 `doc_id`（必须 64 位 hex）与 `content_type`（白名单）做 fail-closed 校验，非法即 422 | `test_metadata_filters_fail_closed_on_hostile_values`、`test_search_rejects_malformed_filter_values`；实测记录见 `logs/bench-*` 与 QODER_LOG V2 |
| 7 | CORS | 默认仅 `localhost:5173` / `127.0.0.1:5173`，`allow_credentials=False` | `test_cors_posture_is_loopback_only` |
| 8 | 密钥泄露 | 密钥只来自环境变量；`/api/meta`、`/api/health`、`LLMGateway.info()` 均不含密钥；`.env` 在 `.gitignore`。**V3 推送前复查发现历史提交曾纳入 PowerContext 运行期产物（本地 `.powercontext.db.cursor-key`、SQLite `WAL/SHM`、迁移状态）与完整 Qoder UID**：HEAD 已清理（文件转存到已忽略目录、UID 改为截断引用），`.gitignore` 补 `*cursor-key*`/`*.db-wal`/`*.db-shm`/`services/powercontext-acceptance-data/`/`*.qoder.site`，历史清理与推送方案见 `PUSH_PRECHECK.md` | `test_public_payloads_carry_no_secret_material`、`test_llm_gateway_info_exposes_no_key`、`PUSH_PRECHECK.md` §1 |
| 9 | 日志脱敏 | 结构化日志只记录截断后的查询文本（≤60 字符）、计数与错误类型；不记录密钥、不记录完整文档内容 | `app/logging_setup.py`、`agent/service.py` 日志字段 |
| 10 | 提示注入（上传文档） | 证据以「---原文开始/结束---」包裹并声明为数据；系统提示禁止执行文档内指令；服务端 citation 校验会剔除文档诱导出的编造引用；含注入文本的文档无法通过证据门控 | `test_evidence_is_wrapped_as_data_not_instructions`、`test_injected_document_cannot_become_evidence_for_an_unrelated_question`、`test_invented_citation_from_injection_is_stripped` |
| 11 | 记忆隔离 | 一个项目一个 PowerContext Scope；A 项目的记忆在 B 项目的恢复结果中不可见 | `test_memory_is_isolated_between_projects` |
| 12 | seekdb 共享实例隔离 | 所有对象带 `RF_SEEKDB_PREFIX`；`reset_store.py` 拒绝清理不带前缀的对象 | `scripts/reset_store.py` 的前缀校验 + 运行时断言 |
| 13 | 并发安全 | 连接按线程隔离；6 并发重复上传不产生重复文档；16 并发检索无连接损坏；embedding 后端线程安全 | `test_concurrent_uploads_of_the_same_file_stay_deduplicated`、`test_concurrent_searches_do_not_corrupt_connections`、`test_thread_safety_of_embedding_backend` |
| 14 | 依赖供应链 | 后端依赖全部固定版本（pyproject）；仅使用 PyPI 官方 `pyseekdb` / `powercontext`；多语模型来自 HuggingFace 官方仓库且仅在显式配置时下载 | `backend/pyproject.toml` |
| 15 | SSRF | 不接受用户提供的 URL；embedding/LLM 的 base_url 仅来自服务端配置 | 代码审查（`embeddings.py`、`llm.py`） |

## 3. 已知未修复 / 剩余风险

| 风险 | 等级 | 说明与缓解 |
| --- | --- | --- |
| API 无认证、无限流 | 高（若公网暴露） | 默认仅监听回环；公网必须前置网关。展示站不连后端，故不受影响 |
| 上传内容会进入 LLM 上下文 | 中 | 属提示注入面，已用数据包裹 + 引用校验缓解；不能证明模型绝对免疫，故校验在服务端兜底 |
| 日志含截断查询文本 | 低 | 多用户共享部署时应改为仅记录哈希 |
| PowerContext 默认无访问控制（`access_mode=disabled`） | 中（若公网） | 仅回环部署；生产应启用 `POWERCONTEXT_SERVER_ACCESS_MODE=enforced` + token |
| seekdb 容器空密码 | 中（若公网） | 仅回环端口映射；生产应设置租户密码 |
| 多语模型按需下载 | 低 | 仅在 `RF_EMBEDDING_PROVIDER=multilingual` 时从 HuggingFace 拉取；可预置离线目录 |

## 4. 方案二（公网在线体验）的安全前置条件

若后续要提供真实在线体验（Sites 前端 + 独立公网后端），必须先满足：

1. 后端 TLS + 认证（至少是签发式体验 token），API 不再匿名可达；
2. 体验租户与个人数据物理隔离：独立 seekdb database/前缀、独立 PowerContext 实例与 Scope 命名空间；
3. 匿名体验只读：禁用上传与记忆写入，或写入仅限一次性体验 Scope 并定期清理；
4. 网关限流与上传配额（≤5MB/次、≤10 次/分钟/IP）；
5. LLM 密钥与数据库凭据只存网关/平台 Secret，绝不下发到前端；
6. Function → 后端的出站目的地固定为 Secret 中的 HTTPS 地址，禁止用户输入拼接；
7. 发布前重跑 `tests/test_security.py` 与本文第 2 节全部用例。

以上任一条无法满足时，回退方案一（静态展示 + 本地复现），**不开放不安全的公网接口**。
