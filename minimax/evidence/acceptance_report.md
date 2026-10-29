# 验收报告 — MiniMax SDD 上下文管理模块

- 总体结果：**PASS**
- 通过 / 失败 / 阻塞：6 / 0 / 0（共 6 项）
- Git 分支：`competition/minimax-sdd-context`
- Git 版本：`28828fe0f81e8fe7eb5e25bb4626cfd6b892a0e9`
- Python：`3.12.13`
- 生成命令：`python minimax/scripts/verify.py --all`
- 模块路径：`minimax`

## 六项官方验收

| 编号 | 名称 | 结果 | Git 版本 | 证据路径 |
| --- | --- | --- | --- | --- |
| TEST-01 | 流程可在干净环境运行 | **PASS** | `28828fe0` | `minimax/sample/taskmanager.py` |
| TEST-02 | MiniMax 真实参与代码修改 | **PASS** | `28828fe0` | `minimax/evidence/minimax_calls`<br>`minimax/evidence/minimax_evidence_audit.json`<br>`minimax/evidence/phase3_git_diff.patch` |
| TEST-03 | 上下文内容正确且来源真实 | **PASS** | `28828fe0` | `minimax/evidence/context_snapshot.json` |
| TEST-04 | 数据库真实参与 | **PASS** | `28828fe0` | `minimax/evidence/seekdb_queries.json` |
| TEST-05 | 任务状态可复用 | **PASS** | `28828fe0` | `minimax/evidence/phase4_cross_process.json` |
| TEST-06 | 代码改动生效 | **PASS** | `28828fe0` | `minimax/evidence/phase1_before.log`<br>`minimax/evidence/phase3_after.log`<br>`minimax/evidence/phase4_r2_before.log`<br>`minimax/evidence/phase4_r2_after.log`<br>`minimax/evidence/phase3_git_diff.patch`<br>`minimax/evidence/red_green_audit.json` |

### TEST-01 — 流程可在干净环境运行

- 结果：**PASS**
- 说明：样例、目标测试、回归测试与 CLI 均可在无第三方依赖的干净环境运行
- Git 版本：`28828fe0f81e8fe7eb5e25bb4626cfd6b892a0e9`
- 实际执行的命令：
- `python -m pytest minimax/tests/test_list_tasks_status_filter.py minimax/tests/test_list_tasks_status_wildcard.py minimax/tests/test_taskmanager_regression.py -q` → 退出码 `0`
- `python -m minimax.sdd_context.cli --help` → 退出码 `0`
- 证据路径：
  - `minimax/sample/taskmanager.py`

### TEST-02 — MiniMax 真实参与代码修改

- 结果：**PASS**
- 说明：归档中 2 条真实开发调用记录（轮次 ['r1', 'r2']）均含模型身份、任务输入与已应用的补丁，补丁逐条重放到改动前的代码后仍通过该轮目标测试，且与 Git 历史中的真实改动逐行对应
- Git 版本：`28828fe0f81e8fe7eb5e25bb4626cfd6b892a0e9`
- 实际执行的命令：
- r1 — `python -m pytest minimax/tests/test_list_tasks_status_filter.py -q  # 在该轮改动前的代码上重放归档补丁后运行` → 退出码 `0`
- r2 — `python -m pytest minimax/tests/test_list_tasks_status_wildcard.py -q  # 在该轮改动前的代码上重放归档补丁后运行` → 退出码 `0`
- 证据路径：
  - `minimax/evidence/minimax_calls`
  - `minimax/evidence/minimax_evidence_audit.json`
  - `minimax/evidence/phase3_git_diff.patch`

### TEST-03 — 上下文内容正确且来源真实

- 结果：**PASS**
- 说明：上下文包含规格 1.1.0 (r2)、9 个代码符号、20 个测试，全部来源文件真实存在
- Git 版本：`28828fe0f81e8fe7eb5e25bb4626cfd6b892a0e9`
- 实际执行的命令：
- `python -m minimax.sdd_context.cli context --task-id TASK-SPEC-REQ-001 --spec-id SPEC-REQ-001` → 退出码 `0`
- 证据路径：
  - `minimax/evidence/context_snapshot.json`

### TEST-04 — 数据库真实参与

- 结果：**PASS**
- 说明：seekdb 5.7.25-OceanBase seekdb-v1.4.0.0 上四张表共 39 行，写入后立即可读回，内容与磁盘文件一致
- Git 版本：`28828fe0f81e8fe7eb5e25bb4626cfd6b892a0e9`
- 实际执行的命令：
- `python minimax/scripts/seekdb_evidence.py` → 退出码 `0`
- 证据路径：
  - `minimax/evidence/seekdb_queries.json`

### TEST-05 — 任务状态可复用

- 结果：**PASS**
- 说明：进程退出后由全新进程读回 24 条完成项、24 条待办、24 条验证结果，并合并进新构建的上下文
- Git 版本：`28828fe0f81e8fe7eb5e25bb4626cfd6b892a0e9`
- 实际执行的命令：
- write process — `python -c "...record_completed/record_todo/record_verification..."` → 退出码 `0`
- read process — `python -c "...ContextBuilder.build..."` → 退出码 `0`
- 证据路径：
  - `minimax/evidence/phase4_cross_process.json`

### TEST-06 — 代码改动生效

- 结果：**PASS**
- 说明：同一目标测试在改动前以 AssertionError 失败、改动后通过，回归测试保持通过，且目标测试文件哈希前后一致
- Git 版本：`28828fe0f81e8fe7eb5e25bb4626cfd6b892a0e9`
- 实际执行的命令：
- r1 before — `pytest minimax/tests/test_list_tasks_status_filter.py minimax/tests/test_taskmanager_regression.py -q  # r1 Red` → 退出码 `1` (日志 `minimax/evidence/phase1_before.log`)
- r1 after — `pytest minimax/tests/test_list_tasks_status_filter.py minimax/tests/test_taskmanager_regression.py -q  # r1 Green` → 退出码 `0` (日志 `minimax/evidence/phase3_after.log`)
- r2 before — `pytest minimax/tests/test_list_tasks_status_wildcard.py -q  # r2 Red` → 退出码 `1` (日志 `minimax/evidence/phase4_r2_before.log`)
- r2 after — `pytest minimax/tests/test_list_tasks_status_filter.py minimax/tests/test_list_tasks_status_wildcard.py minimax/tests/test_taskmanager_regression.py -q  # r2 Green` → 退出码 `0` (日志 `minimax/evidence/phase4_r2_after.log`)
- current suite — `python -m pytest minimax/tests/test_list_tasks_status_filter.py minimax/tests/test_list_tasks_status_wildcard.py minimax/tests/test_taskmanager_regression.py -q` → 退出码 `0`
- 证据路径：
  - `minimax/evidence/phase1_before.log`
  - `minimax/evidence/phase3_after.log`
  - `minimax/evidence/phase4_r2_before.log`
  - `minimax/evidence/phase4_r2_after.log`
  - `minimax/evidence/phase3_git_diff.patch`
  - `minimax/evidence/red_green_audit.json`

## 判定口径

- `PASS`：该项的检查全部为真，且其证据来自本报告记录的 git 版本对应的真实执行。
- `FAIL`：检查执行了但未通过，例如补丁重放后目标测试未通过，或哈希与提交不一致。
- `BLOCKED`：依赖不可用或证据缺失，该项**没有**被执行，因此不计入通过。

TEST-02 是**离线历史证据审计**，它不发起新的模型调用；需要一次真实在线调用时使用 `minimax/scripts/live_minimax_check.py`，其结果单独记录在 `minimax/evidence/minimax_live_check.json`。
