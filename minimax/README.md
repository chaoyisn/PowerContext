# MiniMax × OceanBase 2026 赛题 — MiniMax SDD 上下文管理模块

本目录是《规有所依——面向软件持续演进的 SDD 上下文管理系统》赛题的完整可运行实现。
模块把 **规格（spec）**、**代码符号**、**测试** 三类工程物料存入 seekdb，把**任务进展、
待办与验证结果**存入 PowerContext，再由 `ContextBuilder` 组装成结构化开发上下文交给
**MiniMax** 生成并落地补丁。

## 0. 三分钟复现（干净环境）

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r minimax/requirements.txt
pip install "powercontext[cli,server]==1.4.1"   # 官方 PowerContext Server（见 3.3）

# 1) 启动依赖服务（见第 3 节）
# 2) 体检：区分"服务没起/密码错/库不存在/业务测试失败"
python minimax/scripts/diagnose.py

# 3) 空库初始化 + 导入物料
python -m minimax.sdd_context.cli init

# 4) 六项官方验收
python minimax/scripts/verify.py --all        # 退出码 0 = 六项全过
```

以上全部命令都不需要 MiniMax API Key，也不需要任何历史数据。
只有"重新发起一次新的模型调用"才需要模型端点，见第 5 节。

## 1. 三项技术的真实参与

| 技术 | 参与位置 | 可核验证据 |
| --- | --- | --- |
| MiniMax | `sdd_context/minimax_agent.py` 发起真实 HTTP 调用，返回 unified diff 并用 `git apply` 落地 | `evidence/minimax_calls/*.json`（归档，含 model / request_id / token / patch）+ `evidence/minimax_evidence_audit.json` |
| seekdb (OceanBase) | `sdd_context/seekdb_store.py` 建四张表并承载全部检索 SQL | `evidence/acceptance_report.json` 的 TEST-04 段（含 `counts` 与 `server_version`） |
| PowerContext | `sdd_context/powercontext_store.py` 通过官方 HTTP 接口写入/读取任务状态 | `evidence/phase4_cross_process.json`（写入进程 PID → 退出 → 全新进程 PID 读回并合入新上下文） |

三者都不是"装上了"或"文档里提到"：MiniMax 的补丁被 `git apply` 真正写入工作树，
seekdb 的行数与磁盘文件内容一致，PowerContext 的记录在进程退出后由**另一个进程**
读回并合入新上下文。

## 2. 目录结构

```
minimax/
├── sample/taskmanager.py            业务样例（零第三方依赖）
├── specs/SPEC-REQ-001.md            真实 SDD 规格（含 r1 / r2 两个版本）
├── specs/history/                   r1 基线快照，用于重放"规格更新"流程
├── tests/
│   ├── test_list_tasks_status_filter.py    r1 目标功能测试
│   ├── test_list_tasks_status_wildcard.py  r2 目标功能测试
│   └── test_taskmanager_regression.py      回归测试
├── sdd_context/
│   ├── config.py            环境变量驱动的配置
│   ├── seekdb_store.py      seekdb 四张表与检索 SQL
│   ├── powercontext_store.py PowerContext 状态读写
│   ├── importer.py          AST 解析导入规格/代码/测试
│   ├── context_builder.py   结构化开发上下文组装
│   ├── minimax_agent.py     MiniMax 调用与补丁落地
│   ├── call_archive.py      只追加的真实调用归档
│   └── cli.py               命令行入口
├── scripts/
│   ├── verify.py                 六项官方验收（入口）
│   ├── render_acceptance_report.py 把验收 JSON 渲染成 Markdown 报告
│   ├── diagnose.py               环境与服务诊断
│   ├── audit_minimax_evidence.py 历史调用证据审计（离线，不调用模型）
│   ├── live_minimax_check.py     在线真实调用验证（单独入口）
│   ├── audit_red_green.py        r1 / r2 逐轮 Red→Green 证据审计
│   ├── regenerate_round_logs.py  从真实 Git 提交重生成 Red/Green 日志
│   ├── reproduce_clean.py        隔离环境端到端复现
│   ├── seed_call_archive.py      从 Git 历史播种调用归档
│   ├── seekdb_evidence.py        seekdb 检索证据
│   └── phase4_checks.py          规格更新 + 跨进程恢复的专项证据
├── evidence/                全部证据文件（日志、补丁、快照、报告、调用归档）
├── docs/VERIFICATION_NOTE.md  验证说明：评审者如何逐项独立复核
├── requirements.txt         固定版本依赖
├── .env.example             配置模板（不含任何真实密钥）
├── .gitattributes           固定行尾，保证哈希断言跨平台一致
├── README.md                本文件
└── TECHNICAL_NOTE.md        一页技术说明
```

## 3. 依赖与准备

### 3.1 Python

官方仓库要求 Python 3.12。请准备一个 3.12 虚拟环境：

```bash
python3.12 -m venv .venv
# Windows
py -3.12 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```

安装依赖（版本已固定在 `requirements.txt`）：

```bash
pip install -r minimax/requirements.txt
```

PowerContext Server 从 **PyPI** 安装到同一环境：

```bash
pip install "powercontext[cli,server]==1.4.1"
```

> **为什么不是 `pip install -e .`？** 本赛题分支 `2026-competition-ecosystem` 的仓库里
> **只有各赛题的子目录，没有 PowerContext 的 Python 源码**（官方源码在 `master` 分支）。
> 因此 `pip install -e .` 会报
> `does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found`。
> 从 PyPI 安装官方发布的同名发行版是本分支上唯一可用的方式，
> 其 API 与官方仓库一致（`/v1/scopes`、`/v1/work/contracts/create`、
> `/v1/memory/remember`、`/v1/memory/entries/list`、`/v1/work/outcomes/record`）。

### 3.2 seekdb / OceanBase

本模块通过 MySQL 协议访问 seekdb，默认 `127.0.0.1:2881`、库名 `sdd_context`。

用容器快速拉起（**可选**，Docker 不是本模块的必需依赖）：

```bash
docker run -d --name contest-seekdb -p 2881:2881 \
  -e OB_ROOT_PASSWORD= oceanbase/oceanbase-seekdb:v1.4.0.0
```

若使用已有的 OceanBase 集群，改 `SDD_SEEKDB_HOST` / `PORT` / `USER` / `PASSWORD` 即可。
诊断脚本会明确区分"服务没起"与"密码错误"，不必手工猜测。

### 3.3 PowerContext Server

用 3.1 安装好的官方 CLI 启动服务（**实测可用**的命令）：

```bash
# Linux / macOS
POWERCONTEXT_HOME="$PWD/.pc-data" powercontext server run --host 127.0.0.1 --port 8790 --no-env-file

# Windows（PowerShell）
$env:POWERCONTEXT_HOME = "$PWD\.pc-data"
powercontext server run --host 127.0.0.1 --port 8790 --no-env-file
```

`POWERCONTEXT_HOME` 决定 SQLite 数据库文件的位置，因此可以用它把不同实验隔离开
（默认落在 `~/.powercontext`）。启动后自检：

```bash
curl http://127.0.0.1:8790/health/ready
# {"status":"ready","checks":{"runtime":"ready","database":"ready", ...}}
```

> `python -m powercontext.server` **不可用**：PyPI 发行包里 `powercontext.server` 是包，
> 没有 `__main__.py`，直接执行会报
> `No module named powercontext.server.__main__`。请使用上面的 `powercontext` CLI。

### 3.4 MiniMax 接入

模块使用 Anthropic 兼容的 `/v1/messages` 接口，默认 `http://127.0.0.1:15721`，
模型 `MiniMax-M3.1-Flash`。**不要把真实 API Key 写进仓库**；用环境变量注入：

```bash
export SDD_MINIMAX_BASE_URL="http://127.0.0.1:15721"
export SDD_MINIMAX_API_KEY="<你的密钥或 PROXY_MANAGED>"
export SDD_MINIMAX_MODEL="MiniMax-M3.1-Flash"
```

所有配置项见 `.env.example`（`.env` 已在 `.gitignore` 中，不会被提交）。

> **模型端点不是验收前提。** 六项官方验收只审计仓库中已保存的真实调用证据，
> 不发起新的模型调用；只有第 5 节的"在线验证"入口需要模型端点。

## 4. 完整运行流程

### 4.1 环境诊断

```bash
python minimax/scripts/diagnose.py
```

逐项区分四种失败：

| 结论 | 含义 | 处理 |
| --- | --- | --- |
| `SERVICE_NOT_STARTED` | 端口无人监听 | 启动服务，或改 `SDD_*_HOST/PORT/URL` |
| `WRONG_CREDENTIALS` | 服务在，但拒绝登录 | 核对 `SDD_SEEKDB_PASSWORD` / `SDD_POWERCONTEXT_TOKEN` |
| `DATABASE_MISSING` | 凭据正确，但 SDD 库不存在 | 执行 `cli init` |
| `BUSINESS_TEST_FAILED` | 依赖全好，问题在模块本身 | 看 `evidence/acceptance_report.json` |

同时报告数据库里是否已有历史物料、PowerContext 里是否已有历史任务状态，
以便判断"空状态复现"的前提是否成立。

### 4.2 初始化（建表 + 导入物料）

```bash
python -m minimax.sdd_context.cli init
```

输出包含数据库版本、PowerContext 健康状态、导入的规格/代码符号/测试与绑定关系。

### 4.3 查看某个开发任务的上下文

```bash
python -m minimax.sdd_context.cli context \
  --task-id TASK-SPEC-REQ-001 \
  --task "为工单查询函数增加按 status 筛选工单的功能 list_tasks(status='active')" \
  --spec-id SPEC-REQ-001 \
  --output minimax/evidence/context_snapshot.json
```

JSON 包含 `task_id`、`task`、`specifications`、`code`、`tests`、`state`、`sources`，
其中每一项都带真实存在的 `source_path` / `file_path`。

### 4.4 持久化任务状态

```bash
python -m minimax.sdd_context.cli task --task-id TASK-SPEC-REQ-001 --create \
  --completed "完成 Red 阶段" \
  --todo "等待 MiniMax 实现" \
  --verification "Red 阶段 6 failed / 12 passed"

python -m minimax.sdd_context.cli state --task-id TASK-SPEC-REQ-001
```

### 4.5 规格更新（重新导入 → 再次查询）

```bash
python -m minimax.sdd_context.cli import \
  --spec minimax/specs/SPEC-REQ-001.md --spec-id SPEC-REQ-001 \
  --code minimax/sample/taskmanager.py \
  --test minimax/tests/test_list_tasks_status_filter.py \
  --test minimax/tests/test_list_tasks_status_wildcard.py \
  --test minimax/tests/test_taskmanager_regression.py
```

新版本继承上一版本的代码/测试绑定，因此上下文仍能解析到同一批物料。
`evidence/phase4_spec_update.json` 记录了更新前后的版本号、`content_hash`、绑定继承数，
以及"旧版本仍留档但不是当前生效版本"的核验。

### 4.6 一键验收

```bash
python minimax/scripts/verify.py --all
python minimax/scripts/render_acceptance_report.py
```

退出码 0 表示六项全部通过；报告写入 `evidence/acceptance_report.json`，
并由第二条命令渲染成可读的 `evidence/acceptance_report.md`——每项都带
**实际执行的命令、退出码、Git 版本和证据路径**。
单项执行：`python minimax/scripts/verify.py --only TEST-04`。

### 4.7 规格更新与跨进程恢复的专项证据

```bash
python -m minimax.scripts.phase4_checks
```

写出 `evidence/phase4_spec_update.json` 与 `evidence/phase4_cross_process.json`。
跨进程验证使用**每次运行唯一的任务 ID**，从空状态开始，并记录写入进程与读取进程的
操作系统 PID——两者必须不同，且读取进程必须能证明恢复内容参与了新的上下文输出。

### 4.8 重置验证样本

```bash
python -m minimax.sdd_context.cli reset
```

清空 seekdb 中的四张 SDD 表并删除数据库。

## 5. MiniMax 证据：历史审计 与 在线验证 分离

这两件事**必须分开看**，本实现提供两个互不替代的入口：

| | 历史证据审计 | 在线集成验证 |
| --- | --- | --- |
| 入口 | `python minimax/scripts/audit_minimax_evidence.py` | `python minimax/scripts/live_minimax_check.py` |
| 是否调用模型 | **否**，不消耗任何额度 | **是**，发起一次真实调用 |
| 模式标记 | `mode: HISTORICAL` | `mode: LIVE` |
| 证明什么 | 仓库里保存的两轮真实开发记录确实产生了仓库里的代码改动 | 此刻的模型接入与"上下文→补丁→落地"链路仍然可用 |
| 需要的条件 | 只要有 git 历史 | 需要模型端点可达 |

历史审计的做法（`audit_minimax_evidence.py`）比"读一个 JSON 看看字段齐不齐"更强：
它把每轮归档的补丁**重放到该轮改动之前的代码**上（从 git 里取出），
然后跑该轮自己的目标测试，最后把打补丁后的文件与该轮提交中的文件逐字节比对。
r1 与 r2 各自独立核验，互不混用。

在线验证（`live_minimax_check.py`）用真实的 seekdb 上下文发起一次调用，
并把返回的补丁应用到**一份临时拷贝**上，因此验证过程不会改动仓库工作树。

## 6. Red → Green 证据链（r1 与 r2 各自独立）

| 阶段 | 证据文件 | 命令 | 结果 |
| --- | --- | --- | --- |
| Red (r1) | `evidence/phase1_before.log` | 目标测试 + 回归测试 | 6 failed / 12 passed，`AssertionError`，`EXITCODE=1` |
| Green (r1) | `evidence/phase3_after.log` | 目标测试 + 回归测试 | 18 passed，`EXITCODE=0` |
| Red (r2) | `evidence/phase4_r2_before.log` | 目标测试 | 3 failed / 1 passed，`AssertionError`，`EXITCODE=1` |
| Green (r2) | `evidence/phase4_r2_after.log` | 全量套件 | 22 passed，`EXITCODE=0` |
| 改动 | `evidence/phase3_git_diff.patch` | — | MiniMax 补丁的真实 unified diff |
| 快照 | `evidence/snapshots/taskmanager_before.py` / `taskmanager_after.py` | — | 基线提交与最终提交的样例全文 |

每份日志都带 `COMMAND=` / `EXITCODE=` / `COMMIT=` / `TARGET_TEST=` / `TARGET_TEST_SHA256=` /
`SPEC_VERSION=` / `SPEC_REVISION=`，因此可以核对"这条结果对应哪个代码版本"。

两轮的目标测试、用例数、规格版本各自独立，不混用：

| | r1 | r2 |
| --- | --- | --- |
| 目标测试 | `test_list_tasks_status_filter.py` | `test_list_tasks_status_wildcard.py` |
| 改动提交 | `e66ae7f7` | `14959429` |
| 规格版本 | 1.0.0 (r1) | 1.1.0 (r2) |
| 目标测试 SHA256 | `8be75f1a…`（前后一致） | `ac7ab515…`（前后一致） |

日志可从真实 Git 提交**重新生成**，用来证明它不是手写的：

```bash
python minimax/scripts/regenerate_round_logs.py
python minimax/scripts/audit_red_green.py
```

> 目标测试文件的哈希对行尾不敏感：校验时先把 CRLF 归一为 LF，并与 git 中的 blob
> 哈希交叉比对，因此在任何平台、任何 `core.autocrlf` 设置下结果一致。

## 7. 干净环境复现

```bash
python minimax/scripts/reproduce_clean.py                  # 隔离库名 + 隔离 scope
python minimax/scripts/reproduce_clean.py --fresh-checkout # 另加全新 git clone
```

该脚本会：

1. 新建一个独立库名（`sdd_context_repro`）并**先确认该库不存在**；
2. 新建一个独立的 PowerContext scope，并确认其中没有任何任务记录；
3. 用一个每次运行唯一的任务 ID；
4. 依次执行 `init` → `diagnose` → `context` → `task` → `verify --all` → `phase4_checks`；
5. 结束后删除隔离库，不影响既有数据库。

`--fresh-checkout` 还会把仓库 clone 到临时目录，用它自己的库名与 scope 重跑一遍，
证明"从全新检出开始按 README 执行"同样成立。

### 7.1 全新的 Python 环境验证

上一条证明的是"数据是空的"，这一条证明的是**环境也是新的**——在一个从未装过本项目
依赖的虚拟环境里，从零安装依赖、启动官方 PowerContext Server，再跑完整套验收：

```bash
python minimax/scripts/verify_fresh_env.py
```

该脚本会新建一个 `include-system-site-packages = false` 的虚拟环境、
执行 `pip install -r minimax/requirements.txt`、用该环境里的 `powercontext` CLI
在独立端口与独立 `POWERCONTEXT_HOME` 上启动服务端，然后在新环境里跑
六项验收、三个审计脚本、pytest 与 phase4 检查。

结果写入 `minimax/evidence/fresh_env_report.json`，其中记录了每一条命令、
真实退出码、Python 版本、隔离性检查结果与解析到的全部依赖版本。

## 8. 已知限制

- 模型端点不可用时，`live_minimax_check.py` 无法运行；这**不影响**六项官方验收，
  因为验收走的是离线历史证据审计。
- seekdb 与 PowerContext Server 需由使用者自行启动；两者不可用时，对应项判为
  `BLOCKED`，绝不判为 `PASS`。
- 规格 r2 的通配符实现由 MiniMax 生成，形态与 r1 略有差异（`None if status == "*" else status`），
  但满足 r2 的全部验收条款。
