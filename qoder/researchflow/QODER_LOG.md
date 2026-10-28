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
