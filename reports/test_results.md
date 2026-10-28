# 赛题三：Pi 会话分支采集与断点恢复 - 测试执行与验证报告

## 一、测试环境配置

- **操作系统**：Windows 11 / WSL2
- **Python 版本**：CPython 3.12.13 (x86_64)
- **Pytest 版本**：9.1.1
- **工作目录**：`E:\OceanBaseContest\powercontext-pi-session`
- **代码分支**：`competition/pi-session-branch-resume`
- **环境变量**：
  ```powershell
  $env:POWERCONTEXT_CANDIDATE = "E:\OceanBaseContest\powercontext-pi-session"
  $env:POWERCONTEXT_PUBLIC = "E:\OceanBaseContest\powercontext-pi-session\competition"
  $env:PYTHONPATH = "E:\OceanBaseContest\powercontext-pi-session\src;E:\OceanBaseContest\powercontext-pi-session\competition"
  $env:PYTHONDONTWRITEBYTECODE = "1"
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
  $env:PYTHONHASHSEED = "0"
  $env:TZ = "UTC"
  ```

---

## 二、测试套件总览与执行结果

本赛题共执行 **34 个测试用例**，全部通过（**100% PASS**），无一失败或跳过：

| 测试套件 | 测试文件 | 用例数 | 通过数 | 失败数 | 通过率 |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **官方必测验收集** | `competition/challenges/source-02-pi-history/acceptance/test_pi.py` | 14 | 14 | 0 | **100%** |
| **官方增量与恢复集** | `competition/challenges/source-02-pi-history/acceptance/test_pi_incremental.py` | 1 | 1 | 0 | **100%** |
| **综合扩展与边界回归集** | `tests/test_pi_session_comprehensive.py` | 19 | 19 | 0 | **100%** |
| **总计** | | **34** | **34** | **0** | **100%** |

---

## 三、官方必测项逐项验证清单

1. `test_public_sessions`：**PASSED**
   - 验证公开 Trace Commons 转换样例（`converted-pi.jsonl`, SHA-256 校验）。
   - 逐事件 Source 解析、`TextEvidence` 投影、SQLite 持久化以及通过 Memory FTS 检索和精确 Citation 回查。
2. `test_explicit_branch_preserves_tool_and_summary_events`：**PASSED**
   - 验证分支路径准确回溯，仅保留祖先链节点 `["a", "c", "d", "e", "f"]`。
   - 验证 `compaction` 与 `branch_summary` 正文原样保留且不截断历史证据。
   - 验证 `assistant` 中包含 `thinking` 过程被过滤，而 `toolCall` 格式化为 `[tool_call read call-1] {"path":"a.txt"}`。
   - 验证 `toolResult` 正确提取并格式化为 `[tool_result read call-1] file contents`。
3. `test_reimport_rejects_changed_event_payload`：**PASSED**
   - 验证相同 session 与 event ID 产生相同的 Source identity。
   - 验证同事件内容改写时触发 `SourceConflictError`，确保不可变性。
4. `test_invalid_graphs_fail_atomically`（4 组边界）：**PASSED**
   - 缺失 parent、自指向循环、重复节点 ID、不存在的 leaf_id 均原子抛出 `ValueError`。
5. `test_invalid_archives_fail`（6 组边界）：**PASSED**
   - 空文件、空 JSON、非字典 JSON、非法 UTF-8 编码、非法版本号（version != 3）均直接抛出 `ValueError`。
6. `test_bom_bash_custom_and_control_parent_are_preserved`：**PASSED**
   - 验证 UTF-8 BOM 自动剥离。
   - 验证 `bashExecution` 正确格式化为 `$ command\noutput`。
   - 验证 `custom_message` 角色为 `custom`。
   - 验证控制节点不生成文本事件但其父子关系被后续事件完整继承。
7. `test_branch_switch_restart_full_evidence_and_mutation_rejection`：**PASSED**
   - 验证分支从 `left` 切换至 `right` 时，共享的 `root` 节点被复用去重，仅导入 1 个新节点。
   - 验证 `replay` 重复执行时 0 节点重复导入，checkpoint 保持一致。
   - 验证追加 `tail` 节点时仅增量导入新增事件。
   - 验证历史记录被篡改时原子触发 `ValueError` 且 checkpoint 不被污染。
   - 验证篡改恢复后无缝从原断点继续。

---

## 四、三次连续执行稳定性验证

按照赛题要求，对包含增量与断点恢复的全部 34 个测试执行 3 次连续回归验证：

```
=== TEST RUN 1 ===
..................................                                       [100%]
34 passed in 25.49s

=== TEST RUN 2 ===
..................................                                       [100%]
34 passed in 22.55s

=== TEST RUN 3 ===
..................................                                       [100%]
34 passed in 22.78s
```

三次执行结果完全一致，无偶发失败（Flaky Tests），系统具备高鲁棒性与确定性。

---

## 五、代码规范与基线一致性检查

- **静态代码检查 (`ruff check`)**：
  ```powershell
  ruff check --config competition/ruff.toml src/powercontext/sources/pi_session.py tests/test_pi_session_comprehensive.py src/powercontext/sources/__init__.py
  ```
  **输出**：`All checks passed!`
- **代码格式化检查 (`ruff format --check`)**：
  ```powershell
  ruff format --check --config competition/ruff.toml src/powercontext/sources/pi_session.py tests/test_pi_session_comprehensive.py src/powercontext/sources/__init__.py
  ```
  **输出**：`3 files already formatted`
- **基线祖先链检查 (`selftest_support.check_baseline`)**：
  ```powershell
  python -m selftest_support.check_baseline
  ```
  **输出**：`Frozen baseline is reachable from HEAD or a fetched branch.`
