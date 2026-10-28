# 测试结果

执行日期：2026-10-28（Asia/Shanghai）。

## 环境审计

| 项目 | 实测 |
| --- | --- |
| 工作区 | E:\OceanBaseContest\powercontext-http-rerank，独立 Git worktree |
| 分支 / 起始 HEAD | competition/http-rerank-cross-batch / dab240063bfcfa7917898dc44da4baadb3747bd0 |
| 远程 | origin https://github.com/chaoyisn/PowerContext |
| 系统 Python | 3.11.7 |
| 项目虚拟环境 | Python 3.12.13，httpx 0.28.1 |
| uv | 0.11.28 |
| pytest | 9.1.1 |
| ruff | 0.15.20 |
| ty | 0.0.56 |
| Git | 2.53.0.windows.2 |
| E: 可用空间 | 约 118 GiB |
| WSL / make | wsl.exe 返回 WSL/E_ACCESSDENIED；Windows PATH 中无 make |

项目虚拟环境没有安装 pytest-asyncio，因此无法原样运行 competition/pytest.ini 中强制加载该插件的 Makefile 命令。本机 Windows Python 的 asyncio 默认唤醒 socket 也会被沙箱阻挡；本地 MockTransport 测试通过批准的本地测试进程运行，没有访问外部评分服务或模型 API。实际测试关闭了插件自动加载，直接运行同步包装的 async 测试。

## 结果

| 检查 | 结果 |
| --- | --- |
| 官方 HTTP 重排公开验收文件 | 10 passed |
| 官方公开验收 + 所有 Memory 单测 | 146 passed, 13 skipped |
| 最终关键回归组（官方公开验收、HTTP 适配器、LLM rerank、Memory Search） | 93 passed，连续 3 次：6.38s、5.27s、5.48s |
| Ruff lint | 通过，3 个变更文件 |
| Ruff format check | 通过，3 个变更文件 |
| Ty 类型检查 | 通过，适配器与新增测试 |
| 外部模型 / 真实评分服务器 | 未调用；均用 httpx.MockTransport |

公开验收文件覆盖了批次边界与跨批排序、乱序分数、响应字段与 rank 错误、HTTP 传输错误以及 Runtime Memory 搜索集成。本地回归另覆盖 0、1、N < B、N = B、N = B+1、N > 2B、173 条候选、尾批不满、重复运行、同分、负分和零分、超时、429/500、部分批次失败、原对象与版本引用，以及 LLM 和默认关闭回归。

## 未覆盖的正式质量门槛

赛事材料仅发布 1 条 claim 与 8 篇摘要样例；正式评测使用的 173 篇摘要、20 条 query 的固定向量和 qrels 不在本地公开目录中。虽然本地测试真实覆盖了 173 个候选的批次映射，但这不是 Recall@10/MRR@10 质量测试。正式 Recall@10 >= 0.95、MRR@10 >= 0.80 尚未本地复现，故整体实现状态按 PARTIAL 报告，等待平台固定输入验收。
