# 基线记录

- 基线分支：`competition/context-delta-rebuild`，从 `origin/2026-competition` 建立。
- 基线工作区：干净；上游分支头为 `dab240063bfcfa7917898dc44da4baadb3747bd0`（首次验收前记录）。
- 题目冻结基线 `9db1753434162c0aa7c9f1189a1722e617880a52` 已确认是该提交的祖先。
- 官方竞赛公开验收：`competition/challenges/context-02-incremental-pack/acceptance/test_incremental_pack.py`，共 14 个测试项。
- 环境：Windows 11；隔离 Python 3.12.13 venv；公开验收依赖缺少的 `pytest-asyncio` 单独安装为 1.4.0。Python 3.11.7 的系统环境也存在，但缺少多项 runtime 依赖。
- 官方 `make -C competition test-incremental` 面向 Linux 容器。此会话的 WSL 返回 `Wsl/ERROR_ACCESS_DENIED`，Docker Desktop daemon 未连接，因此基线改用公开 pytest 配置在 Windows Python 3.12 上执行。

## 首次基线结果

运行公开验收得到 **14 failed / 0 passed**。所有失败的根因均为缺少 `powercontext.builtin.runtime.context_pack`；原始版本没有本题接口。最初直接使用系统 pytest 时还遇到 `pytest-asyncio` 未安装，随后使用独立 venv 重跑并完成了有效测试收集。

本结果是预期的功能缺口基线，不代表已有 prepare 回归。修改后会以同一 Windows venv、相同公开验收文件和配置复测，并单独运行相关 Runtime 回归。
