# 四题集成验证

## 集成来源

| 功能 | 已拉取的远程分支 | 纳入的完整 SHA |
| --- | --- | --- |
| CSV 行级采集 | `competition/csv-row-ingestion` | `3d19ba60811a32cd31dc6c89c2b31d5ece350896` |
| HTTP 重排 | `competition/http-rerank-cross-batch` | `17e676f9a2d83a33c5599d44017bbb66014cb36b` |
| Pi 会话采集 | `competition/pi-session-branch-resume` | `3ed1e77a013307764e904adaf26aa8e5e985025d` |
| Source 数量触发 | `competition/source-count-trigger` | `222989aac17dfc91638a8c468483921d2330872d` |

四个提交均为集成分支历史的祖先；CSV 之外三个分支与 CSV 的共同祖先为 `dab240063bfcfa7917898dc44da4baadb3747bd0`。上下文增量分支没有纳入。

## 冲突处理

`src/powercontext/sources/__init__.py` 的冲突合并保留了 CSV 与 Pi 两套导入、常量、模型和解析函数的公开导出。其余冲突是各分支新增的同名报告：CSV 报告保留在 `reports/`，HTTP、Pi 和数量触发报告分别保存于 `reports/http-rerank/`、`reports/pi-session/` 和 `reports/source-count/`。其他源码无冲突。未改变依赖、迁移或 API 合同。

## 实际测试

比赛固定依赖 Docker 镜像使用 Python 3.12、pytest 9.0.2、pytest-asyncio 1.4.0，容器网络关闭。Windows checkout 的 shell 入口脚本使用 CRLF，测试通过 `/bin/sh` 执行相同的 dummy interface 初始化和降权步骤，然后运行官方 pytest/Makefile 目标。

| 阶段 | 结果 |
| --- | --- |
| CSV 基点公开验收 | 17 passed |
| 合入 HTTP 后 CSV + HTTP | 27 passed |
| 合入 Pi 后 CSV + HTTP + Pi | 42 passed |
| 合入数量触发后四题公开验收 | 59 passed in 495.77s |
| CSV/Pi 同 scope、数量触发、HTTP 重排、citation 与重启共存测试 | 1 passed in 38.32s |
| 仓库补充测试：CSV、Pi、HTTP、调度器、Topic scope 和共存测试 | 144 passed in 99.08s |

新增共存测试位于 `tests/e2e/test_integrated_competition.py`：分别注册并持久化 CSV 与 Pi observation，不足阈值时保持静默，达到阈值后由原生 worker 生成 Memory，通过 Mock HTTP 服务按批次重排，验证真实请求数、条目 identity/citation 和重启后的 Source 引用。

完整官方 `make -C /selftest test PYTHON=python PRODUCT=/candidate` 已实际执行，整体退出失败。目标四题分别为 CSV 17 passed、Pi 15 passed、HTTP 10 passed、Source 数量触发 17 passed。未纳入的六题结果：PDF 1 收集错误（模块缺失）；上下文增量 14 failed（模块缺失）；embedding 批处理 2 收集错误（模块缺失）；Source lifecycle 1 收集错误（模块缺失）；evidence selection 3 failed（配置能力缺失）；hybrid search 1 failed（缺少指定 native hybrid 查询）。这些结果不计为目标四题通过。

集成文件的 Ty 检查通过；Ruff format 检查 10 个文件通过。Ruff lint 在合入的 Pi 源文件中报告 45 项既有规则诊断，其他九个集成文件通过；未为消除 lint 改写该已通过的分支行为。

目标 90 分是四题各 20 分与 Fork 10 分的理论和。Fork 的平台通过状态来自用户提供的信息；正式平台隐藏测试及累计分数尚未由本地验证。未自动向平台提交任务。
