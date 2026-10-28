# 测试结果

## 最终验收

最终版本：**17 passed in 337.56s**（17/17，退出码 0）。

比赛固定依赖离线容器 `powercontext-competition-selftest:2026` 使用 Python 3.12、pytest 9.0.2 和 pytest-asyncio 1.4.0，`network_mode: none`。Windows checkout 的官方 shell 入口脚本因 CRLF 无法解析，测试在同一容器内手动执行入口脚本中的 dummy interface 初始化和 `setpriv`，然后运行官方 pytest 参数；没有修改公开测试、测试数据或测试预期。

```sh
cd /selftest
setpriv --reuid 10001 --regid 10001 --clear-groups \
  python -m pytest -q -c pytest.ini --confcutdir=. \
  challenges/processing-01-count-trigger/acceptance
```

实际运行的容器命令在上述 pytest 前执行 `ip link add pcselftest0 type dummy`、配置 `198.18.0.1/32` 并启用接口，以匹配官方入口脚本要求；容器网络仍为关闭状态。

## 重复运行

配置校验、Memory 单窗重判、Topic Memory wave、失败后重启恢复四项关键场景连续运行三轮，均通过：

| 轮次 | 结果 |
| --- | --- |
| 第 1 轮（另含 scope/family 隔离及 lineage 顺序） | 10 passed, 7 deselected in 263.25s |
| 第 2 轮 | 5 passed, 12 deselected in 145.63s |
| 第 3 轮 | 5 passed, 12 deselected in 151.74s |

## 回归测试与静态检查

Runtime/Supervisor、composition、Topic scope 和持久化恢复相关的 7 个项目测试文件：`100 passed`。对应文件为：

- `tests/builtin/runtime/test_artifact_processing_config.py`
- `tests/builtin/runtime/test_artifact_processing.py`
- `tests/builtin/runtime/test_processing_scheduler.py`
- `tests/builtin/runtime/test_processing_composition.py`
- `tests/builtin/runtime/test_topic_memory_scope.py`
- `tests/e2e/test_artifact_processing_persistence.py`
- `tests/e2e/test_topic_memory_processing.py`

本题四个源码文件的 Ruff lint、Ruff format 检查和 Ty 检查通过。全仓 Ty 检查仍报告 246 项诊断，分布于竞赛 acceptance、既有模块的 unresolved import/API 类型、Windows 下 Unix-only API 等；本题修改的四个文件无诊断。全仓类型检查未作为通过项报告。

## 环境限制与基线

- 改动前官方严格配置用例真实失败：缺少两个阈值字段（`1 failed`）。
- Windows 首次读官方 UTF-8 样例时采用系统 GBK 编码，出现 `UnicodeDecodeError`；未更改样例，改用官方 Linux 容器后公开组通过。
- 早期开发验收曾发现计数扫描的 SQLAlchemy 结果映射类型错误，已修复；随后公开组及重复回归通过。
