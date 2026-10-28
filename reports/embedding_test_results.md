# Embedding 赛题测试结果

执行日期：2026-10-28。竞赛测试在 WSL2 Ubuntu 24.04、Python 3.12 下执行。

## 官方公开验收

| 检查 | 结果 |
| --- | --- |
| 冻结基线 `9db1753434162c0aa7c9f1189a1722e617880a52` | 未实现题目 API，公开验收收集时因缺少 `powercontext.builtin.inference.coalescing` 模块失败 |
| `make -C competition test-embedding` | **8 passed in 16.04s** |
| 官方原生请求预算 | 随公开验收通过：24 条文本、6 个 scope、批次上限 6，Provider 恰好 4 次调用；6 次向量搜索后仍为 4 次 |

官方命令使用仓库固定的 `competition/.venv` 与 `competition/pytest.ini`。第一次误选开发虚拟环境时缺少 pytest-asyncio 插件，未计作正式验收运行；随后使用固定竞赛环境运行官方 Make 目标并通过。

## 新增单元与稳定性检查

| 检查 | 结果 |
| --- | --- |
| `tests/builtin/inference/test_coalescing.py` | **10 passed in 4.08s** |
| 并发去重、取消隔离、失败重试关键用例，第 1 轮 | **4 passed in 5.21s** |
| 同上，第 2 轮 | **4 passed in 5.36s** |
| 同上，第 3 轮 | **4 passed in 5.42s** |
| Ruff lint | **All checks passed**（2 个修改文件） |
| Ruff format | **2 files already formatted** |
| Ty 定向类型检查 | **All checks passed** |

## 全仓回归

正在运行项目 `make test` 全套回归。pytest 收集 **3,798 items / 2 skipped**；运行至约 30% 时已经出现多个 Runtime 既有测试失败。完整运行尚未结束，失败堆栈和是否与本次改动相关待完整日志确认；此项暂不记为通过。最终结论将在集成分支联合回归后补记。

## 覆盖边界

公开测试和本地单测使用离线计数 Provider；没有访问在线模型或评分服务器。公开套件覆盖跨调用并发、缓存、LRU、失败恢复、取消隔离、usage 和原生 Memory 搜索。本地单测额外检查非法数量、非有限数值、容量为零、非对称 query/document 向量和配置边界。
