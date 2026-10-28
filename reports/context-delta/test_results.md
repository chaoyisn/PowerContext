# 测试与静态检查结果

## 赛题与新增代码

环境为 Windows 11、Python 3.12.13 隔离 venv；`PYTHONPATH=src`，`PYTHONHASHSEED=0`。

```text
pytest -q competition/challenges/context-02-incremental-pack/acceptance/test_incremental_pack.py tests/builtin/runtime/test_context_pack.py
22 passed in 1.96s
```

覆盖公开竞赛验收和新增 Runtime 测试。公开验收本身 14 项，全部通过；新增测试覆盖 wire oracle、UTF-8 分块、序列化后独立重建、增删改排、空正文和篡改拒绝。

- Ruff 对 3 个变更文件检查通过。
- Ruff 格式检查对 3 个变更文件通过；全仓格式检查也通过（995 个文件）。
- `ty check` 对 3 个变更文件通过，目标 Python 3.12/Linux，使用隔离 venv。
- `scripts/release_version.py --check`、`scripts/generate_api.py --check`、`scripts/generate_js_operations.py --check`、`scripts/check_workflow_actions.py .github/workflows .github/actions`、`uv lock --project . --locked` 及设置 `PYTHONPATH=src` 后的 Integration Manifest 文档检查均通过。

## 全仓 pytest

命令：`python -m pytest --doctest-modules -q --tb=short`，使用 `PYTHONPATH=src`。

```text
3421 passed, 137 failed, 240 skipped, 30 warnings in 1522.90s
```

本次隔离环境由 `uv sync --locked --extra builtin --group dev --no-install-workspace` 准备：源码通过 `PYTHONPATH` 可导入，但项目未安装到 venv。失败记录包括子进程无法导入已安装的 `powercontext`、缺少 distribution metadata、Windows 上运行的 systemd/launchd 相关断言，以及独立 Memory 进程集成场景失败。Pytest 的 137 个失败标识中没有 `context_pack`、新增 challenge acceptance 或变更 Runtime application 测试。全仓结果因此不能作为本题回归门禁；本题验收以其上方全部通过的公开 acceptance + 新增测试结果为准。

全仓 Ruff 检查也发现三个原有 challenge acceptance 文件的 `I001` 导入排序问题；这些文件不属于本次修改，检查时恢复了由 Ruff 自动格式化造成的本地改动。变更文件的 Ruff 检查通过。全仓 `ty` 在当前 Windows 环境报告 233 项诊断；变更文件的 Linux 目标检查通过。
