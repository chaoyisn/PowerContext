# 提交说明 — 规有所依：面向软件持续演进的 SDD 上下文管理系统（MiniMax × OceanBase 2026）

本文件是本次赛题的提交说明，包含复现步骤、验收结果、技术参与证据与已知限制。
文中不含任何真实凭据；所有路径均为**仓库相对路径**。

---

## 1. 项目简介

### 1.1 要解决的问题

规格驱动开发（SDD）里，"这次改动要动哪些代码、要满足哪些条款、上一轮做到哪了"
这三类信息通常散落在规格文档、代码库、测试文件和聊天记录里。模型拿到的上下文要么靠人手工拼，
要么靠检索猜，结果是"看起来合理但对不上规格"的补丁。

本模块把这三类信息收敛成一条**可重复执行**的流水线：

```
规格 .md ──┐
代码 .py ──┼─▶ MaterialImporter (AST) ─▶ seekdb ─▶ ContextBuilder ─▶ MiniMax ─▶ git apply
测试 .py ──┘                                  ▲                                    │
                                   规格↔代码↔测试绑定                      工作树改动
                                              ▲
                        任务进展/待办/验证 ──┴─▶ PowerContext Server
```

### 1.2 三项技术的分工

| 技术 | 承担的角色 | 代码位置 | 真实参与的可核验方式 |
| --- | --- | --- | --- |
| **seekdb (OceanBase)** | **规格/代码/测试的结构化存储与检索**。四张表 `sdd_specification` / `sdd_code_symbol` / `sdd_test` / `sdd_relation` 承载全部物料，绑定关系随规格版本继承 | `minimax/sdd_context/seekdb_store.py`、`importer.py` | 验收 TEST-04 回磁盘核对每个符号与测试函数；上下文只返回数据库真实查出的行，不读本地文件 |
| **PowerContext** | **任务状态与开发进展的持久化**。通过官方 HTTP 接口写入/读取 work contract、memory、outcome | `minimax/sdd_context/powercontext_store.py` | 验收 TEST-05：写入进程退出后由**另一个进程**读回，并合入新构建的上下文（记录两个 OS PID） |
| **MiniMax** | **按规格生成补丁**。以结构化上下文为输入，返回 unified diff，用 `git apply` 落地 | `minimax/sdd_context/minimax_agent.py` | 归档 `evidence/minimax_calls/*.json` 含模型身份、token 用量与原始响应；审计脚本把每轮补丁**重放到改动前的代码**上再跑该轮自己的目标测试 |

三者都不是"装上了"或"文档里提到"：

- MiniMax 的补丁被 `git apply` 真正写入工作树，且可在审计中重放复现；
- seekdb 的行数与磁盘文件内容逐项比对一致，写入后立即可读回；
- PowerContext 的记录在进程退出后由另一进程读回，并出现在新构建的上下文里。

---

## 2. Git 信息

| 项目 | 值 |
| --- | --- |
| 参赛仓库 | `https://github.com/chaoyisn/PowerContext` |
| 官方上游仓库 | `https://github.com/oceanbase/powercontext`（**不推送**） |
| 官方基线分支 | `2026-competition-ecosystem` |
| 官方基线 Commit（冻结点） | `d647275c308e09b7b623f322a26f5c4e85734fb0` |
| 提交分支 | `competition/minimax-sdd-context` |
| 提交目录 | `minimax/` |
| 相对基线的改动范围 | **仅 `minimax/`**（71 个文件） |

> **分支说明**：官方赛题文档 `competition/challenges/setup-00-repository-fork/instruction.md` 明确
> "仓库名称和分支名称不限，无需创建判题专用分支"。本分支的历史包含冻结基线
> `d647275c`，因此满足基线历史要求。基线分支 `2026-competition-ecosystem` 上
> `minimax/` 只有一个 `.gitkeep`，本实现即填入该目录。

**被测试的代码提交（完整 40 位 SHA）**：

```
aa56990683e778badbc6d11f3e7972e4c9181358
```

六项官方验收、全新检出复现、全新虚拟环境验证均在该提交上运行。

**最终交付提交**：本分支 `competition/minimax-sdd-context` 的 tip。
它相对上面那个提交只增加了本文件与刷新后的证据文件，**代码内容完全一致**。

由于一个提交无法在自身的文件内容里写下自己的哈希（会自我引用），最终提交的
完整 40 位 SHA 记录在仓库的**附注标签** `submission-v3` 上，
该标签在提交之后创建，不属于提交内容，因此没有循环引用：

```bash
git tag -n submission-v3          # 查看标签注释，其中写明最终提交的完整 SHA
git rev-parse submission-v3       # 直接取出最终提交的完整 SHA
```

分支链接：<https://github.com/chaoyisn/PowerContext/tree/competition/minimax-sdd-context>

> 报告中的 `commit` / `git_version` 字段记录的是**本次运行所测试的代码提交**。
> 把报告本身提交进仓库的那次提交会更新报告文件，但不改变被测试的代码——
> 这两者的区别在 `acceptance_report.json` 的 `git_version_note` 字段里已写明。

---

## 3. 快速复现

### 3.1 前置条件（服务需自行启动）

| 依赖 | 必需 | 说明 |
| --- | --- | --- |
| Python 3.12 | 是 | |
| seekdb / OceanBase（MySQL 协议，2881 端口） | 是 | TEST-03 / TEST-04 需要真实数据库 |
| PowerContext Server（HTTP，8790 端口） | 是 | TEST-05 需要真实服务端 |
| MiniMax 端点（15721 端口） | **否** | 六项验收只审计已归档的真实调用，不发起新调用 |

启动 seekdb：

```bash
docker run -d --name contest-seekdb -p 2881:2881 oceanbase/seekdb:1.4.0.0
```

启动 PowerContext Server（**必须用官方 CLI**；`python -m powercontext.server` 不可用，
该包没有 `__main__.py`）：

```bash
pip install "powercontext[cli,server]==1.4.1"
export POWERCONTEXT_HOME="$PWD/.pc-home"     # 隔离数据目录，避免污染既有状态
powercontext server run --host 127.0.0.1 --port 8790 --no-env-file
```

### 3.2 从 clone 到完整验收

```bash
git clone https://github.com/chaoyisn/PowerContext.git
cd PowerContext
git checkout competition/minimax-sdd-context

python3.12 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r minimax/requirements.txt
pip install "powercontext[cli,server]==1.4.1"

# 0) 体检：区分"服务没起 / 密码错 / 库不存在 / 业务测试失败"
python minimax/scripts/diagnose.py

# 1) 空库初始化 + 导入物料
python minimax/scripts/run_cli.py init

# 2) 六项官方验收（退出码 0 = 六项全过）
python minimax/scripts/verify.py --all
echo "EXIT=$?"

# 3) 专项证据（可选，全部离线，不消耗模型额度）
python minimax/scripts/audit_minimax_evidence.py     # 历史调用证据审计
python minimax/scripts/audit_red_green.py             # r1 / r2 逐轮 Red→Green 审计
python -m minimax.scripts.phase4_checks               # 规格更新 + 跨进程恢复
python minimax/scripts/check_spec_change_propagates.py  # 证明规格变更真的进入上下文
```

> `python -m minimax.sdd_context.cli` 需要当前目录是仓库根；
> `python minimax/scripts/run_cli.py` 是等价入口，**可从任意工作目录运行**。

### 3.3 一键端到端（隔离环境，不碰正式数据）

```bash
python minimax/scripts/reproduce_clean.py --fresh-checkout  # 独立库名 + 独立 scope + 全新 git clone
python minimax/scripts/verify_fresh_env.py                  # 全新 Python venv + 从零装依赖 + 独立端口服务端
```

---

## 4. 六项验收结果

验收命令：`python minimax/scripts/verify.py --all`
**本次运行退出码：`0`（六项全过）**
证据文件：`minimax/evidence/acceptance_report.json`（机器可读）、`minimax/evidence/acceptance_report.md`（人可读）

| 验收项 | 名称 | 结果 | 复现命令 | 退出码 | 证据路径 |
| --- | --- | --- | --- | --- | --- |
| TEST-01 | 流程可在干净环境运行 | **PASS** | `python -m pytest minimax/tests/test_list_tasks_status_filter.py minimax/tests/test_list_tasks_status_wildcard.py minimax/tests/test_taskmanager_regression.py -q`<br>`python -m minimax.sdd_context.cli --help` | `0`<br>`0` | `minimax/sample/taskmanager.py` |
| TEST-02 | MiniMax 真实参与代码修改 | **PASS** | `python minimax/scripts/audit_minimax_evidence.py` | `0` | `minimax/evidence/minimax_calls/`、`minimax/evidence/minimax_evidence_audit.json`、`minimax/evidence/phase3_git_diff.patch` |
| TEST-03 | 上下文内容正确且来源真实 | **PASS** | `python minimax/scripts/run_cli.py context --task-id TASK-SPEC-REQ-001 --spec-id SPEC-REQ-001` | `0` | `minimax/evidence/context_snapshot.json` |
| TEST-04 | 数据库真实参与 | **PASS** | `python minimax/scripts/seekdb_evidence.py` | `0` | `minimax/evidence/seekdb_queries.json` |
| TEST-05 | 任务状态可复用 | **PASS** | `python -m minimax.scripts.phase4_checks` | `0` | `minimax/evidence/phase4_cross_process.json` |
| TEST-06 | 代码改动生效 | **PASS** | `python minimax/scripts/audit_red_green.py` | `0` | `minimax/evidence/phase1_before.log`、`phase3_after.log`、`phase4_r2_before.log`、`phase4_r2_after.log`、`phase3_git_diff.patch`、`red_green_audit.json` |

各项实测细节：

- **TEST-01**：22 项测试全部通过（`22 passed`），样例代码零第三方依赖，CLI 可独立运行。
- **TEST-02**：归档中 **2 条**真实开发调用记录（轮次 `r1`、`r2`），每条都含模型身份
  `MiniMax-M3.1-Flash`、任务输入与已应用的补丁。审计把每轮补丁 `git apply` 到**改动前**的代码上，
  再跑**该轮自己的目标测试**，全部通过——因此不需要每次复核都消耗模型额度。
- **TEST-03**：上下文解析到规格 **1.1.0 (r2)**、**9** 个代码符号、**20** 个测试；
  每一项都回磁盘核对文件存在、符号真在文件里定义、测试函数真在测试文件里。
- **TEST-04**：`5.7.25-OceanBase seekdb-v1.4.0.0` 上四张表共 **34 行**
  （规格 1 / 代码符号 9 / 测试 20 / 关系 4），写入后立即可读回，内容与磁盘文件一致。
- **TEST-05**：写入进程退出后，由**全新进程**读回 1 条完成项、1 条待办、1 条验证结果，
  并合入新构建的上下文；两个进程 PID 不同，读取进程不是父进程。
- **TEST-06**：r1 与 r2 **各自独立**审计——Red 阶段失败均为 `AssertionError`（功能性失败，
  不是 `TypeError`），Green 阶段通过；目标测试文件在 Red 与 Green 之间 SHA256 逐字节一致，
  并与 git blob 交叉比对；回归测试保持通过。

### 4.1 Red→Green 实测数据

| 轮次 | 目标测试 | Red | Green | 改动提交 |
| --- | --- | --- | --- | --- |
| r1 | `test_list_tasks_status_filter.py` | `6 failed, 12 passed`，EXITCODE=1 | `18 passed`，EXITCODE=0 | `e66ae7f7` |
| r2 | `test_list_tasks_status_wildcard.py` | `3 failed, 1 passed`，EXITCODE=1 | `22 passed`，EXITCODE=0 | `14959429` |

四份日志可由 `python minimax/scripts/regenerate_round_logs.py` 从真实提交重新生成
（用 `git archive` 导出提交树后在导出目录里跑真实 pytest），因此日志不是手写的。

### 4.2 全新环境与全新检出验证

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 全新 Python venv（`include-system-site-packages = false`）从零装依赖并跑完整验收 | PASS，15 步全部退出码 0 | `minimax/evidence/fresh_env_report.json` |
| 全新 git clone 后按 README 执行完整流程 | PASS，8 步全部退出码 0 | `minimax/evidence/clean_reproduction.json` |
| 规格变更真的进入上下文（临时插入一条已提交版本不存在的要求） | PASS | `minimax/evidence/spec_change_propagation.json` |
| 规格更新重放 + 跨进程恢复（独立库名与独立 scope） | PASS | `minimax/evidence/phase4_spec_update.json`、`phase4_cross_process.json` |

---

## 5. 技术使用记录

### 5.1 MiniMax

| 项 | 实测值 |
| --- | --- |
| 模型 | `MiniMax-M3.1-Flash` |
| 接入方式 | Anthropic 兼容的 `POST {base_url}/v1/messages`（默认 `http://127.0.0.1:15721`） |
| 归档目录 | `minimax/evidence/minimax_calls/`（只追加，不覆盖） |
| 开发轮次记录 | 2 条（`r1`、`r2`），含 `model` / `input_tokens` / `output_tokens` / `raw_response` / `patch` / `applied_files` / `repository_commit` |
| 在线验证记录 | 4 条（`round = live-verification`），含真实 `request_id`（形如 `2113154684427440325_17932855705nyy5k`）与 `usage` |
| 历史审计 | `minimax/evidence/minimax_evidence_audit.json`（`status = PASS`） |
| 在线验证 | `minimax/evidence/minimax_live_check.json` |

**历史证据审计与在线调用严格分离**：TEST-02 只读归档、把补丁重放到改动前的代码上跑该轮自己的
目标测试，全程离线；需要一次真实在线调用时用 `python minimax/scripts/live_minimax_check.py`，
结果单独存档并标记 `mode: LIVE`，不与历史开发轮次混算。

### 5.2 seekdb (OceanBase)

| 项 | 实测值 |
| --- | --- |
| 版本 | `5.7.25-OceanBase seekdb-v1.4.0.0` |
| 接入方式 | MySQL 协议（`pymysql`），默认 `127.0.0.1:2881` |
| 表 | `sdd_specification` / `sdd_code_symbol` / `sdd_test` / `sdd_relation` |
| 查询日志 | `minimax/evidence/seekdb_queries.json`（含每条 SQL、参数、行数与真实返回行） |
| 数据库内实测量 | 34 行（规格 1 / 符号 9 / 测试 20 / 关系 4） |

**规格版本的留档机制**：`sdd_specification` 以 `(spec_id, version)` 为主键，v1.0.0 与 v1.1.0 并存；
`import_specification()` 检测到版本变化时会把上一版的绑定关系复制到新版本上——这正是
"规格更新后上下文仍能解析到同一批物料"的关键。

### 5.3 PowerContext

| 项 | 实测值 |
| --- | --- |
| 安装方式 | PyPI `powercontext[cli,server]==1.4.1`（官方赛题分支不含 PowerContext 源码，无法 `pip install -e .`） |
| 服务端启动 | `powercontext server run --host 127.0.0.1 --port 8790 --no-env-file` |
| 使用的官方接口 | `POST /v1/scopes`、`GET /v1/scopes/default`、`POST /v1/work/contracts/create`、`POST /v1/memory/remember`、`GET /v1/memory/entries/list`、`POST /v1/work/outcomes/record`、`GET /health/ready` |
| 数据隔离 | `POWERCONTEXT_HOME` 环境变量控制 SQLite 数据目录；每次验证使用独立 scope 与唯一任务 ID |
| 证据 | `minimax/evidence/phase4_cross_process.json`（写入 PID → 进程退出 → 全新进程 PID 读回并合入上下文） |

---

## 6. 已知限制

1. **外部服务依赖**：seekdb 与 PowerContext Server 需自行启动；MiniMax 端点仅在需要
   发起**新的**在线调用时必需。六项官方验收走离线历史证据审计，不需要模型端点。
2. **平台兼容性**：开发与验证在 **Windows 11 + Python 3.12.13** 上完成，
   PowerContext 服务端以官方 CLI 启动。Linux/macOS 下的命令差异仅在虚拟环境激活
   （`source .venv/bin/activate` vs `.venv\Scripts\activate`）；仓库内所有路径均为仓库相对路径，
   `.gitattributes` 已把行尾固定为 LF，因此跨平台不会出现行尾导致的哈希不一致。
3. **需配置的环境变量**：见 `minimax/.env.example`（全部为占位值，不含真实密钥）。
   常用项：`SDD_SEEKDB_*`、`SDD_POWERCONTEXT_URL` / `SDD_POWERCONTEXT_TOKEN`、
   `SDD_CONTEXT_ROOT`、`SDD_EVIDENCE_DIR`、`SDD_MINIMAX_BASE_URL` / `SDD_MINIMAX_API_KEY`。
   `SDD_MINIMAX_API_KEY` 默认为占位符 `PROXY_MANAGED`，**请注入自己的密钥，不要提交进仓库**。
4. **模型输出的形态差异**：r2 的通配符实现由 MiniMax 生成，形态与 r1 略有差异
   （`None if status == "*" else status`），但满足 r2 的全部验收条款。
5. **当前只覆盖 Python 单一语言**：`ast` 解析路径换成 tree-sitter 即可扩展到多语言。
6. **上下文检索策略**：目前以规格 ID 为主、任务词为辅；数据量变大后可加向量检索，
   但**不得**退化成"读本地文件"——那会让数据库失去意义。

---

## 7. 交付材料清单

| # | 材料 | 位置 |
| --- | --- | --- |
| 1 | SDD 上下文模块 | `minimax/sdd_context/` |
| 2 | MiniMax 集成与真实开发记录 | `minimax/sdd_context/minimax_agent.py`、`minimax/evidence/minimax_calls/` |
| 3 | seekdb 初始化与真实查询实现 | `minimax/sdd_context/seekdb_store.py` |
| 4 | PowerContext 保存/恢复实现 | `minimax/sdd_context/powercontext_store.py` |
| 5 | 可运行业务项目 | `minimax/sample/taskmanager.py` |
| 6 | SDD 规格 | `minimax/specs/SPEC-REQ-001.md`、`minimax/specs/history/` |
| 7 | 种子数据与验证样本 | `minimax/sample/`、`minimax/tests/`、`minimax/evidence/snapshots/` |
| 8 | 新功能测试与原回归测试 | `minimax/tests/test_list_tasks_status_filter.py`、`test_list_tasks_status_wildcard.py`、`test_taskmanager_regression.py` |
| 9 | 改动前后代码快照 | `minimax/evidence/snapshots/` |
| 10 | 实际 Git Diff | `minimax/evidence/phase3_git_diff.patch` |
| 11 | Red→Green 日志 | `minimax/evidence/phase1_before.log`、`phase3_after.log`、`phase4_r2_before.log`、`phase4_r2_after.log` |
| 12 | 数据库查询日志 | `minimax/evidence/seekdb_queries.json` |
| 13 | 跨进程恢复证据 | `minimax/evidence/phase4_cross_process.json` |
| 14 | README | `minimax/README.md` |
| 15 | 一页技术说明 | `minimax/TECHNICAL_NOTE.md` |
| 16 | 配置模板 + 依赖锁定 + 重置方法 | `minimax/.env.example`、`minimax/requirements.txt`、`minimax/README.md` §4.9 |

补充：`minimax/docs/VERIFICATION_NOTE.md` 说明评审者如何**独立复核**每一项；
`minimax/SUBMISSION.md` 即本文件。
