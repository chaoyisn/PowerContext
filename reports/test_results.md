# 测试与静态检查结果

## 赛题公开验收

- 官方公开验收目录：`competition/challenges/memory-01-source-lifecycle/acceptance`。
- 连续执行 3 轮，每轮 `4 passed`；总计 12 个测试执行均通过。覆盖撤回、恢复、DAG 多层传播、原生搜索/Context、事件校验、重启、历史引用和重放。
- Windows 执行环境通过 `D:\OceanBase\PowerContext-embedding\.venv\Scripts\python.exe` 提供 Python 3.12 及 `pytest-asyncio`。设置 `PYTHONPATH` 指向本工作树 `src`，并关闭自动插件发现，避免赛题 `pytest.ini` 显式插件与 entry point 重复注册。

## 聚焦回归

在功能分支运行以下聚焦测试，结果为 **158 passed in 30.94s**：

```powershell
uv run --locked --group dev python -m pytest -c pyproject.toml -q -p no:cacheprovider `
  tests/builtin/runtime/test_source_lifecycle.py `
  tests/builtin/runtime/test_prepared_context.py `
  tests/builtin/runtime/test_topic_memory_application.py `
  tests/builtin/persistence/test_sources.py `
  tests/builtin/persistence/test_memory.py `
  tests/builtin/persistence/test_topic_memory.py `
  tests/builtin/artifacts/memory/test_service.py
```

## 静态检查

- Ruff lint：变更的 6 个源码/测试文件 `All checks passed!`
- Ruff format：同 6 个文件 `6 files already formatted`
- ty：4 个变更实现文件 `All checks passed!`

## 范围与限制

全仓测试套件未在本次功能分支执行。最初的基线全仓收集尝试使用不完整的既有虚拟环境，报 234 个 collection errors、10 个 skips，包含缺少可选/开发依赖的问题；该结果不是功能分支测试结论。已运行的官方公开验收及聚焦回归均在功能工作树中针对当前实现执行。
