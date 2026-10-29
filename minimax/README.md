# MiniMax × OceanBase 2026 赛题 — MiniMax SDD 上下文管理模块

本目录是《规有所依——面向软件持续演进的 SDD 上下文管理系统》赛题的完整可运行实现。
模块把 **规格（spec）**、**代码符号**、**测试** 三类工程物料存入 seekdb，把**任务进展、
待办与验证结果**存入 PowerContext，再由 `ContextBuilder` 组装成结构化开发上下文交给
**MiniMax** 生成并落地补丁。

## 1. 三项技术的真实参与

| 技术 | 参与位置 | 可核验证据 |
| --- | --- | --- |
| MiniMax | `sdd_context/minimax_agent.py` 发起真实 HTTP 调用，返回 unified diff 并用 `git apply` 落地 | `evidence/minimax_call.json`（含 model / request_id / token / patch） |
| seekdb (OceanBase) | `sdd_context/seekdb_store.py` 建四张表并承载全部检索 SQL | `evidence/acceptance_report.json` 的 TEST-04 段（含 `counts` 与 `server_version`） |
| PowerContext | `sdd_context/powercontext_store.py` 通过官方 HTTP 接口写入/读取任务状态 | `evidence/phase4_cross_process.json`（跨进程写入 → 退出 → 新进程读回） |

三者都不是"装上了"或"文档里提到"：MiniMax 的补丁被 `git apply` 真正写入工作树，
seekdb 的行数与磁盘文件内容一致，PowerContext 的记录在进程退出后由全新进程读回并合入新上下文。

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
│   └── cli.py               命令行入口
├── scripts/
│   ├── verify.py            六项官方验收（入口）
│   └── phase4_checks.py     规格更新 + 跨进程恢复的专项证据
├── evidence/                全部证据文件（日志、补丁、快照、报告）
├── requirements.txt         固定版本依赖
├── config.example.env       配置模板
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

PowerContext Server 需要从官方仓库安装到同一环境：

```bash
pip install -e . --no-deps
```

### 3.2 seekdb / OceanBase

本模块通过 MySQL 协议访问 seekdb，默认 `127.0.0.1:2881`、库名 `sdd_context`。
可用容器快速拉起：

```bash
docker run -d --name contest-seekdb -p 2881:2881 \
  -e OB_ROOT_PASSWORD= oceanbase/oceanbase-seekdb:v1.4.0.0
```

若使用已有的 OceanBase 集群，改 `SDD_SEEKDB_HOST` / `PORT` / `USER` / `PASSWORD` 即可。

### 3.3 PowerContext Server

从官方仓库启动服务（示例）：

```bash
export POWERCONTEXT_SERVER_DATABASE_URL="sqlite+aiosqlite:///$PWD/pc.db"
python -m powercontext.server --host 127.0.0.1 --port 8790
```

### 3.4 MiniMax 接入

模块使用 Anthropic 兼容的 `/v1/messages` 接口，默认 `http://127.0.0.1:15721`，
模型 `MiniMax-M3.1-Flash`。**不要把真实 API Key 写进仓库**；用环境变量注入：

```bash
export SDD_MINIMAX_BASE_URL="http://127.0.0.1:15721"
export SDD_MINIMAX_API_KEY="<你的密钥或 PROXY_MANAGED>"
export SDD_MINIMAX_MODEL="MiniMax-M3.1-Flash"
```

所有配置项见 `config.example.env`。

## 4. 完整运行流程

### 4.1 初始化（建表 + 导入物料）

```bash
python -m minimax.sdd_context.cli init
```

输出包含数据库版本、PowerContext 健康状态、导入的规格/代码符号/测试与绑定关系。

### 4.2 查看某个开发任务的上下文

```bash
python -m minimax.sdd_context.cli context \
  --task-id TASK-SPEC-REQ-001 \
  --task "为工单查询函数增加按 status 筛选工单的功能 list_tasks(status='active')" \
  --spec-id SPEC-REQ-001 \
  --output minimax/evidence/context_snapshot.json
```

JSON 包含 `task_id`、`task`、`specifications`、`code`、`tests`、`state`、`sources`，
其中每一项都带真实存在的 `source_path` / `file_path`。

### 4.3 让 MiniMax 实现

```bash
python -m minimax.sdd_context.cli apply \
  --task-id TASK-SPEC-REQ-001 \
  --task "为工单查询函数增加按 status 筛选工单的功能 list_tasks(status='active')" \
  --spec-id SPEC-REQ-001
```

模型返回的 unified diff 会被 `git apply` 直接落到工作树，调用记录写入
`evidence/minimax_call.json`。

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
`evidence/phase4_spec_update.json` 记录了更新前后的版本号、`content_hash` 与绑定继承数。

### 4.6 一键验收

```bash
python minimax/scripts/verify.py --all
```

退出码 0 表示六项全部通过；报告同时写入 `evidence/acceptance_report.json`。
单项执行：`python minimax/scripts/verify.py --only TEST-04`。

### 4.7 规格更新与跨进程恢复的专项证据

```bash
python -m minimax.scripts.phase4_checks
```

写出 `evidence/phase4_spec_update.json` 与 `evidence/phase4_cross_process.json`。

### 4.8 重置验证样本

```bash
python -m minimax.sdd_context.cli reset
```

清空 seekdb 中的四张 SDD 表并删除数据库。

## 5. Red → Green 证据链

| 阶段 | 证据文件 | 内容 |
| --- | --- | --- |
| Red (r1) | `evidence/phase1_before.log` | 6 failed / 12 passed，失败原因为 `AssertionError`，`EXITCODE=1` |
| Green (r1) | `evidence/phase3_after.log` | 18 passed，`EXITCODE=0` |
| Red (r2) | `evidence/phase4_r2_before.log` | 3 failed / 1 passed，`AssertionError`，`EXITCODE=1` |
| Green (r2) | `evidence/phase4_r2_after.log` | 22 passed，`EXITCODE=0` |
| 改动 | `evidence/phase3_git_diff.patch` | MiniMax 补丁的真实 unified diff |
| 快照 | `evidence/snapshots/taskmanager_before.py` / `taskmanager_after.py` | 改动前后的业务样例全文 |

目标测试文件在 Red 与 Green 之间**逐字节一致**（SHA256 见日志与验收报告），
断言未被削弱。

## 6. 已知限制

- `verify.py` 的 TEST-02 读取的是最近一次 MiniMax 调用的记录文件。若要复现该调用，
  需先让 `apply` 成功执行一次；模型不可用时该项会判为 `FAIL` 而非 `PASS`。
- seekdb 与 PowerContext Server 需由使用者自行启动；两者不可用时，对应项判为 `BLOCKED`。
- 规格 r2 的通配符实现由 MiniMax 生成，形态与 r1 略有差异（`None if status == "*" else status`），
  但满足 r2 的全部验收条款。
