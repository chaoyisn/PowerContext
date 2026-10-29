# 验证说明（Verification Note）

本文说明**评审者如何独立复核**本模块的六项官方验收，以及每一项的证据在哪里。
所有路径均为仓库相对路径。

## 0. 前置条件

| 依赖 | 是否为验收必需 | 说明 |
| --- | --- | --- |
| Python 3.12 | 是 | `python -m minimax.sdd_context.cli --help` 需可运行 |
| seekdb / OceanBase（MySQL 协议，2881） | 是 | TEST-03 / TEST-04 需要真实数据库 |
| PowerContext Server（HTTP，8790） | 是 | TEST-05 需要真实服务端 |
| MiniMax 端点（15721） | **否** | 六项验收只审计已归档的真实调用，不发起新调用 |

若依赖不可用，对应项判 `BLOCKED`——**不会**判成 `PASS`。

```bash
python minimax/scripts/diagnose.py
```

该命令会明确区分四种情况：`SERVICE_NOT_STARTED`（服务没起）、
`WRONG_CREDENTIALS`（凭据不对）、`DATABASE_MISSING`（库不存在）、
`BUSINESS_TEST_FAILED`（依赖正常但业务测试失败）。

## 1. 一条命令跑完六项

```bash
python minimax/scripts/verify.py --all
echo $?     # 0 = 六项全过
```

报告：`minimax/evidence/acceptance_report.json`（机器可读）、
`minimax/evidence/acceptance_report.md`（人可读，由
`python minimax/scripts/render_acceptance_report.py` 生成）。

每项都记录：**实际执行的命令、真实退出码、结果对应的 Git 版本、证据路径**。

## 2. 逐项复核路径

### TEST-01 流程可在干净环境运行

- 命令：`python -m pytest minimax/tests/test_list_tasks_status_filter.py minimax/tests/test_list_tasks_status_wildcard.py minimax/tests/test_taskmanager_regression.py -q`
- 样例代码零第三方依赖，探针脚本直接 import 并调用 `list_tasks(status='active')`。
- 证据：`minimax/evidence/acceptance_report.json` 的 `TEST-01` 段。

### TEST-02 MiniMax 真实参与代码修改

这是**离线历史证据审计**，不发起模型调用。

```bash
python minimax/scripts/audit_minimax_evidence.py
```

审计做的是四件事：

1. 归档文件 `minimax/evidence/minimax_calls/*.json` 逐条读取（只追加，不覆盖）；
2. 取出该轮**改动前**的样例代码（`git show <commit>~1:...`）；
3. 把归档补丁 `git apply` 到改动前的代码上，跑**该轮自己的目标测试**；
4. 把打补丁后的文件与该轮提交中的文件逐字节比对。

r1 与 r2 各自独立审计，互不混用。证据：
`minimax/evidence/minimax_evidence_audit.json`。

需要一次**真实在线调用**时使用单独的入口：

```bash
python minimax/scripts/live_minimax_check.py
```

它发起一次真实请求并把补丁应用到临时拷贝，不改动工作树，结果单独存到
`minimax/evidence/minimax_live_check.json`，标记 `mode: LIVE`。
**历史审计不会被标记为在线调用，在线调用也不计入历史开发轮次。**

### TEST-03 上下文内容正确且来源真实

```bash
python -m minimax.sdd_context.cli context --task-id TASK-SPEC-REQ-001 \
  --spec-id SPEC-REQ-001 --output minimax/evidence/context_snapshot.json
```

每一项来源都回磁盘核对：文件是否存在、符号是否真在文件里定义、
测试函数是否真在测试文件里。同时确认上下文解析到的是**当前生效版本**
（v1.1.0 / r2）而不是留档的旧版本。

### TEST-04 数据库真实参与

```bash
python minimax/scripts/seekdb_evidence.py
```

记录服务器版本、四张表的行数、规格的全部版本、绑定关系、代码符号与测试行，
并做一次写入后立即读回。证据：`minimax/evidence/seekdb_queries.json`。

### TEST-05 任务状态可复用

```bash
python -m minimax.scripts.phase4_checks
```

跨进程恢复的证明方式：

- 写入在一个子进程里完成，**该进程退出后**才启动读取进程；
- 记录两个进程的操作系统 PID，断言二者不同，且读取进程不是父进程；
- 任务 ID 每次运行唯一，并先断言**起始状态为空**，避免把历史记录误当恢复；
- 读回的完成项 / 待办 / 验证结果必须**出现在新构建的上下文里**。

证据：`minimax/evidence/phase4_cross_process.json`。

### 规格变更是否真的进入上下文

```bash
python minimax/scripts/check_spec_change_propagates.py
```

`phase4_checks.py` 重放的是仓库里已提交的 r1 / r2。这个脚本回答的是**机制本身**：
临时插入一条已提交版本里不存在的要求并提升版本号，重新导入并重建上下文，
断言新要求出现在上下文里、改动前不存在、内容哈希变化、绑定未丢失、旧版本仍留档。
在隔离库名与隔离 scope 下运行，运行结束后还原规格文件。
证据：`minimax/evidence/spec_change_propagation.json`。

### TEST-06 代码改动生效
```bash
python minimax/scripts/audit_red_green.py
python minimax/scripts/regenerate_round_logs.py
```

两轮**各自独立**审计：

| | r1 | r2 |
| --- | --- | --- |
| 目标测试 | `test_list_tasks_status_filter.py` | `test_list_tasks_status_wildcard.py` |
| 改动提交 | `e66ae7f7` | `14959429` |
| Red 日志 | `phase1_before.log` | `phase4_r2_before.log` |
| Green 日志 | `phase3_after.log` | `phase4_r2_after.log` |
| Red 结果 | 6 failed / 12 passed | 3 failed / 1 passed |
| Green 结果 | 18 passed | 22 passed |

`regenerate_round_logs.py` 用 `git archive` 导出真实提交，在那里跑真实 pytest，
重新生成四份日志——因此日志不是手写的。测试文件逐字取自提交，断言未被修改。

每份日志带 `COMMAND=` / `EXITCODE=` / `COMMIT=` / `TARGET_TEST=` /
`TARGET_TEST_SHA256=` / `SPEC_VERSION=` / `SPEC_REVISION=`。

> 目标测试的哈希取自**行尾归一化后**的内容，并与 git 中的 blob 哈希交叉比对，
> 因此在任何平台、任何 `core.autocrlf` 设置下结果一致。

## 3. 干净环境复现

```bash
python minimax/scripts/reproduce_clean.py --fresh-checkout
```

它会用**独立的库名**（`sdd_context_repro`）与**独立的 PowerContext scope**
跑完整条流水线，并先证明这两个命名空间在运行前是空的；
`--fresh-checkout` 还会把仓库 clone 到临时目录，用它自己的库名与 scope 再跑一遍。

结果：`minimax/evidence/clean_reproduction.json`。

### 3.1 全新的 Python 环境

```bash
python minimax/scripts/verify_fresh_env.py
```

新建一个**看不到系统包**的虚拟环境（`include-system-site-packages = false`），
从零安装 `minimax/requirements.txt`，用该环境里的 `powercontext` CLI 在独立端口、
独立 `POWERCONTEXT_HOME` 上启动官方服务端，再在新环境里跑六项验收、三个审计脚本、
pytest 与 phase4 检查。

结果：`minimax/evidence/fresh_env_report.json`——含每条命令、真实退出码、
Python 版本、隔离性检查与解析到的全部依赖版本。

## 4. 怎么判断"没有作弊"

| 检查 | 做法 |
| --- | --- |
| 没有硬编码答案 | TEST-03/04 的每个来源都回磁盘核对；TEST-02 把补丁重放后跑真实测试 |
| 没有用 mock 冒充真实调用 | 归档里的每条记录都含模型返回的原始响应；离线审计只重放不生成 |
| 不依赖开发机历史状态 | `reproduce_clean.py` 用空库空 scope 跑通全流程 |
| 证据与代码版本一致 | 每份证据记录产生它的 commit；哈希与 git blob 交叉比对 |
| 不只是检查文件存在 | 符号与测试函数都核对到文件内容；数据库行数与磁盘内容比对 |
| 未执行的测试不标 PASS | 依赖不可用判 `BLOCKED`；报告的 `commands` 段记录真实退出码 |
| 没有改断言换通过 | 目标测试文件哈希在 Red 与 Green 之间逐字节一致 |
| 没有伪造日志 | 四份 Red/Green 日志可从真实提交重新生成 |
