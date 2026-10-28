# 五题集成验证

## 集成来源

| 功能 | 已拉取的远程分支 | 纳入的完整 SHA |
| --- | --- | --- |
| CSV 行级采集 | `competition/csv-row-ingestion` | `3d19ba60811a32cd31dc6c89c2b31d5ece350896` |
| HTTP 重排 | `competition/http-rerank-cross-batch` | `17e676f9a2d83a33c5599d44017bbb66014cb36b` |
| Pi 会话采集 | `competition/pi-session-branch-resume` | `3ed1e77a013307764e904adaf26aa8e5e985025d` |
| Source 数量触发 | `competition/source-count-trigger` | `222989aac17dfc91638a8c468483921d2330872d` |
| 上下文增量传输 | `competition/context-delta-rebuild` | `04576845858dc56cff2f7ab4552bf66721453c65` |

五个来源提交均纳入集成历史；CSV 之外的分支与 CSV 的共同祖先为 `dab240063bfcfa7917898dc44da4baadb3747bd0`。

## 冲突处理

`src/powercontext/sources/__init__.py` 的冲突合并保留了 CSV 与 Pi 两套导入、常量、模型和解析函数的公开导出。其余冲突是各分支新增的同名报告：CSV 报告保留在 `reports/`，HTTP、Pi、数量触发和上下文增量报告分别保存在各自子目录。其他源码无冲突。未改变依赖、迁移或现有 API 合同。

## 实际测试

比赛固定依赖 Docker 镜像使用 Python 3.12、pytest 9.0.2、pytest-asyncio 1.4.0，容器网络关闭。Windows checkout 的 shell 入口脚本使用 CRLF，测试通过 `/bin/sh` 执行相同的 dummy interface 初始化和降权步骤，然后运行官方 pytest/Makefile 目标。

| 阶段 | 结果 |
| --- | --- |
| CSV 基点公开验收 | 17 passed |
| 合入 HTTP 后 CSV + HTTP | 27 passed |
| 合入 Pi 后 CSV + HTTP + Pi | 42 passed |
| 合入数量触发后四题公开验收 | 59 passed in 495.77s |
| CSV/Pi 同 scope、数量触发、HTTP 重排、citation 与重启共存测试 | 1 passed in 38.32s |
| 四题版本的仓库补充测试：CSV、Pi、HTTP、调度器、Topic scope 和共存测试 | 144 passed in 99.08s |
| 合入上下文增量后五题公开验收 | 73 passed in 423.03s |
| 当前集成版本的增量单元、修复与五题共存测试 | 24 passed in 47.30s |

共存测试位于 `tests/e2e/test_integrated_competition.py`：分别注册并持久化 CSV 与 Pi observation，不足阈值时保持静默，达到阈值后由原生 worker 生成 Memory，通过 Mock HTTP 服务按批次重排，验证真实请求数、条目 identity/citation、增量包序列化与重建，以及重启后的 Source 引用。

四题版本曾实际执行完整官方 `make -C /selftest test PYTHON=python PRODUCT=/candidate`，整体退出失败。目标四题分别为 CSV 17 passed、Pi 15 passed、HTTP 10 passed、Source 数量触发 17 passed。当时未纳入的六题结果：PDF 1 收集错误；上下文增量 14 failed；embedding 批处理 2 收集错误；Source lifecycle 1 收集错误；evidence selection 3 failed；hybrid search 1 failed。上下文增量现已合入，在五题公开验收中 14 项通过；完整十题目标在本次合入后未重跑。

集成文件的 Ty 检查通过；Ruff format 检查 10 个文件通过。Ruff lint 在合入的 Pi 源文件中报告 45 项既有规则诊断，其他九个集成文件通过；未为消除 lint 改写该已通过的分支行为。

五题各 20 分与 Fork 10 分的理论上限为 110 分，前提是平台全部验收通过。Fork 和原四题的平台通过状态来自用户提供的信息；赛题六修复后的隐藏测试、正式累计分数尚未由本地验证。未自动向平台提交任务。

赛题六此前修复报告中注明：官方隐藏测量序列、真实 Server + HTTP Client 端到端和结构化 citation 独立往返尚未验证；本次集成没有消除这些验证缺口。
