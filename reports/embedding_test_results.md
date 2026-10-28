# Embedding 赛题测试结果

执行日期：2026-10-28。竞赛测试在 WSL2 Ubuntu 24.04、Python 3.12 下执行。

## 官方公开验收

| 检查 | 结果 |
| --- | --- |
| 冻结基线 `9db1753434162c0aa7c9f1189a1722e617880a52` | 未实现题目 API，公开验收收集时因缺少 `powercontext.builtin.inference.coalescing` 模块失败 |
| `make -C competition test-embedding` | **8 passed in 16.62s**（新增故障场景用例后复跑） |
| 官方原生请求预算 | 随公开验收通过：24 条文本、6 个 scope、批次上限 6，Provider 恰好 4 次调用；6 次向量搜索后仍为 4 次 |

官方命令使用仓库固定的 `competition/.venv` 与 `competition/pytest.ini`。第一次误选开发虚拟环境时缺少 pytest-asyncio 插件，未计作正式验收运行；随后使用固定竞赛环境运行官方 Make 目标并通过。

## 新增单元与稳定性检查

| 检查 | 结果 |
| --- | --- |
| `tests/builtin/inference/test_coalescing.py` | **14 passed in 6.19s** |
| 并发去重、取消隔离、Provider 故障重试关键用例，第 1 轮 | **8 passed in 6.34s** |
| 同上，第 2 轮 | **8 passed in 6.25s** |
| 同上，第 3 轮 | **8 passed in 5.92s** |
| Ruff lint | **All checks passed**（2 个修改文件） |
| Ruff format | **2 files already formatted** |
| Ty 定向类型检查 | **All checks passed** |

新增 Provider 故障测试分别覆盖 HTTP 500、超时、连接失败和非法 JSON；四种异常均原样传播，失败不进入缓存，下一次相同 Key 请求会重新调用 Provider 并成功。错误向量数量和 NaN 的失败后重试也继续通过。

## 全仓回归

整合分支曾运行完整 pytest：**39 failed、3717 passed、141 skipped、6 warnings**（3895 items，46:19）。该轮使用的 Git 归档快照遗漏了已跟踪的 `scripts/`，且开发 venv 未启用 pytest-asyncio；因此其中发布脚本/证据扫描和 4 个 async 用例失败不构成有效源码回归结论。后续在真实工作树并启用 asyncio 插件，复跑 Pi、release、scan 三组共 **34 passed、5 failed**；Pi 与 release 用例通过，证据扫描剩余 5 项因 WSL 未安装 `jq` 而报告 `jq_unavailable`。换行敏感的脚本与中文文档仅在复跑期间临时转为 LF，均已恢复原始字节。

完整回归仍不记为 PASS。首次全量中 worker/observability、OpenCode/CLI、LoCoMo 等其他失败组尚未全部在修正测试配置后重跑；证据扫描与 Topic Memory 的定向复跑结果如下。

补充的 Topic Memory 定向回归为 **14 passed、4 failed in 326.00s**。失败为 E0 hermetic chain、configured-provider hybrid/fallback 和两种 Qwen family 配置；诊断均是 background worker 未发布结果。E0 的脱敏记录为 `TimeoutError`，fake provider 只收到 1 次 embedding 请求。为排除赛题八影响，在 Embedding 合并前的四题集成提交 `a6dde1e20508a62b8b06d711ea82a6f587ae1901` 上重跑同一 E0 用例，得到相同 `TimeoutError` 和相同 1 次 embedding 记录；该问题在当前 WSL 多进程回归环境中可复现于赛题八之前。

## 覆盖边界

公开测试和本地单测使用离线计数 Provider；没有访问在线模型或评分服务器。公开套件覆盖跨调用并发、缓存、LRU、失败恢复、取消隔离、usage 和原生 Memory 搜索。本地单测额外检查非法数量、非有限数值、容量为零、非对称 query/document 向量和配置边界。
