# RUN.md — 启动、演示与验证

所有路径相对于 `qoder/researchflow/`。本机环境：Windows 11、Python 3.11.7、Node v24、Docker 29。

---

## 0. 前置条件

| 依赖 | 状态 | 说明 |
| --- | --- | --- |
| seekdb 服务 | 需要运行中的容器 | `docker ps` 应能看到 `contest-seekdb`（`127.0.0.1:2881`）。若机器重启过：`docker start contest-seekdb` |
| 后端 Python venv | `backend/.venv` | 已随仓库工作副本存在；重建命令见 §1 |
| PowerContext venv | `services/.venv-powercontext` | 已存在；重建命令见 §1 |
| 前端依赖 | `frontend/node_modules` | 已存在；重建：`cd frontend && npm install` |
| LLM 密钥 | 可选 | 不配置则问答进入「仅检索模式」，其余功能不受影响 |

检查 seekdb 是否可用：

```bash
docker exec contest-seekdb mysql --no-defaults --protocol=TCP -h 127.0.0.1 -P 2881 -u root --batch -e "SELECT VERSION();"
# 期望输出包含：5.7.25-OceanBase seekdb-v1.4.0.0
```

---

## 1. 从零重建环境（可选，通常不需要）

```bash
# 后端
cd backend
uv venv --python 3.11 .venv
uv pip install --python .venv -e ".[dev]"        # 或 pip install -e ".[dev]"

# PowerContext 服务（独立 venv，避免与后端依赖冲突）
cd ..
uv venv --python 3.11 services/.venv-powercontext
uv pip install --python services/.venv-powercontext "powercontext[cli,server]==1.4.1"

# 前端
cd frontend && npm install && cd ..

# demo 语料（可复现；PDF 第 4 页为刻意留空）
backend/.venv/Scripts/python scripts/build_demo_assets.py
```

---

## 2. 启动三个进程

### 2.1 PowerContext 记忆服务（端口 17429）

```bash
POWERCONTEXT_HOME="$PWD/services/powercontext-data" \
  services/.venv-powercontext/Scripts/powercontext.exe server run \
  --host 127.0.0.1 --port 17429 --no-env-file
```

验证：`curl http://127.0.0.1:17429/health/ready` → `{"status":"ready",...}`

### 2.2 ResearchFlow 后端（端口 8787，同源提供前端）

```bash
cd backend
RF_LLM_API_KEY="$DEEPSEEK_API_KEY" .venv/Scripts/python -m app.api.main
```

- 不配置 `RF_LLM_API_KEY` 也能启动；问答会进入「仅检索模式」。
- 其他 OpenAI 兼容服务：`RF_LLM_BASE_URL=... RF_LLM_MODEL=...`。
- 前端构建产物 `frontend/dist` 存在时会被同源挂载，`/knowledge` 等深链接有 SPA 回退。

验证：`curl http://127.0.0.1:8787/api/health`

### 2.3 前端开发服务器（可选，端口 5173）

```bash
cd frontend && npm run dev
```

开发模式走 Vite 的 `/api` 代理到 8787；生产演示直接用 2.2 的同源地址即可。

### 2.4 灌入演示数据

```bash
backend/.venv/Scripts/python scripts/seed_demo.py
```

它会上传 `demo/` 三份文档、创建项目 `demo-seekdb-hybrid`、保存一条带真实证据指针的进度快照，
并跑一次带证据问答，把每一步真实返回值打印出来。

---

## 3. 演示流程（约 5 分钟）

1. **项目总览** `http://127.0.0.1:8787/`
   健康条显示 seekdb 真实版本与计数、PowerContext 1.4.1、LLM 与 embedding provider。
   点击项目卡片 → 看到「历史记忆 · PowerContext」标记的续研简报与待办。
2. **知识库** `/knowledge`
   - 展开 `seekdb_hybrid_retrieval_notes.pdf` 的页导航：5 个物理页，第 4 页标记「空白页（保留页级身份）」。
   - 点第 5 页 → 弹窗显示 seekdb 中存储的原文与 `page_id`。
   - 搜索「一条记录如果在两条腿里都排第一，RRF 融合分数是多少」，勾选「启用证据门控」→
     命中第 5 页，卡片显示 score（RRF 融合分）、coverage、relevance、chunk_id。
   - 点「对比三种检索方式」→ 三列并排 + 重叠分析。
   - 再拖一份 `demo/research_plan.md` 上传 → 显示「重复上传已去重」。
3. **AI 工作台** `/workbench`
   - 关联项目后提问上面的问题 → 回答带 `[c1]`，论断核验显示「资料直接支持：2」，
     引用面板可点开第 5 页原文；记忆面板显示紫色「历史记忆 · PowerContext」通道。
   - 提问「这篇文档里有没有关于量子纠缠实验的测量结果」→
     回答「尚无证据」，`citations` 为空，**不会编造引用**。
4. **任务记忆** `/memory`
   - 选项目 → 看到恢复的续研简报、按类型分组的 16 条记忆（含 seq / artifact_id / revision）。
   - 在保存表单加一条 next_steps → 保存 → 显示 `written=1`、`seq` 递增、snapshot artifact id。
   - 再点一次保存同样内容 → 显示「内容未变化，未产生重复记忆」。

---

## 4. 验证命令

```bash
# 单元 + 集成测试（88 个；对真实 seekdb 与真实 PowerContext）
cd backend && .venv/Scripts/python -m pytest tests/ -q

# T1-T8 端到端验收（自带独立 PowerContext:17430 与 API:8788，真实重启/断连）
cd .. && backend/.venv/Scripts/python scripts/run_acceptance.py

# 需要连共享 seekdb 容器一起重启验证时（会影响同机其他赛题，谨慎）：
backend/.venv/Scripts/python scripts/run_acceptance.py --restart-seekdb

# 能力实测（P0 证据）
backend/.venv/Scripts/python scripts/probe_seekdb_capability.py
backend/.venv/Scripts/python scripts/smoke_ingest_retrieve.py
backend/.venv/Scripts/python scripts/smoke_memory.py

# 只清理本项目对象（rf_ 前缀），不碰其他赛题
backend/.venv/Scripts/python scripts/reset_store.py --yes
```

验收报告输出在 `logs/acceptance-<时间戳>/`：`acceptance-report.md` / `.json` + 每个用例的独立 `.log`。
后端结构化日志：`logs/researchflow.log`（JSON 行，含 request_id）。

---

## 5. 配置

全部配置项见 [.env.example](./.env.example)。常用：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RF_SEEKDB_HOST/PORT` | `127.0.0.1:2881` | seekdb 服务器 |
| `RF_SEEKDB_MODE` | `server` | Windows 必须 `server`；Linux/macOS 可 `embedded` |
| `RF_SEEKDB_PREFIX` | `rf_` | 所有表/集合前缀，隔离同库其他项目 |
| `RF_SEEKDB_FTS_ANALYZER` | `ik` | 全文分析器：ik / ngram / ngram2 / space / beng |
| `RF_EMBEDDING_PROVIDER` | `minilm` | minilm / hashing / openai |
| `RF_POWERCONTEXT_URL` | `http://127.0.0.1:17429` | 记忆服务 |
| `RF_LLM_API_KEY` | 空 | 空 = 仅检索模式 |
| `RF_RETRIEVAL_MIN_COVERAGE` | `0.30` | 证据门控阈值（实测标定，见 VERIFICATION.md） |

---

## 6. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `Embedded Client is not available...` | Windows 无 `pylibseekdb` wheel。把 `RF_SEEKDB_MODE` 设为 `server`（默认即如此） |
| 健康检查 seekdb `available=false` | 容器没起：`docker start contest-seekdb`；或端口被改 |
| 记忆接口 503 | PowerContext 没起；按 §2.1 启动。检索与问答不受影响 |
| 中文记忆检索召回弱 | PowerContext 默认 SQLite 用 `fts5 unicode61`，不分中文。恢复走全量读取，不受影响；UI 会展示该说明 |
| 向量检索结果与预期不符 | 检查 `/api/health` 的 `stored_embedding.provider` 是否与当前 provider 一致；换 provider 后需重新入库（`force=true`） |
| 上传 415 | 扩展名不在白名单（.pdf/.md/.markdown/.txt） |
| 上传 413 | 超过 `RF_UPLOAD_MAX_BYTES`（默认 20MB） |
