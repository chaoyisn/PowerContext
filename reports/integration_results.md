# PowerContext 比赛集成结果

## 分支组成

集成基线为 `2026-competition`（`dab240063bfcfa7917898dc44da4baadb3747bd0`）。远端原 `competition/powercontext-integrated` 已包含四道先前功能题及 Context Delta；本次保留该远端历史，并加入 Embedding。原集成 HEAD 为 `d0d90e333cfe1d5f5bb0dd241d40bb86eaf16891`。

| 功能 | 分支头 commit | 验收结果 |
| --- | --- | --- |
| CSV 行级采集 | `3d19ba60811a32cd31dc6c89c2b31d5ece350896` | PASS：17 passed |
| Pi 会话采集与恢复 | `3ed1e77a013307764e904adaf26aa8e5e985025d` | PASS：15 passed |
| HTTP 跨批 Rerank | `17e676f9a2d83a33c5599d44017bbb66014cb36b` | PASS：10 passed |
| Source 数量触发 | `222989aac17dfc91638a8c468483921d2330872d` | PASS：最终合并树 17 passed，隔离容器中 349.35s |
| Embedding 合并与缓存 | 独立分支最终提交 `386339c289dce77159a99ff0ef6a387eb379b346` | PASS：官方 8 passed；新增单测 14 passed |
| Context Delta（远端既有功能） | `04576845858dc56cff2f7ab4552bf66721453c65` | 公开验收 14 项通过；下方记录本次 WSL 共存复跑结果 |

本次要求的五组公开 acceptance（CSV、Pi、HTTP、Source Count、Embedding）均已通过；Context Delta 是原远端集成分支中已有且有独立通过记录的额外功能。Pi 公开样例校验其原始 SHA-256；Windows checkout 的 `core.autocrlf=true` 曾将 JSONL 样例检出为 CRLF。本地验收时将该文件临时还原为官方 LF 字节（SHA-256 `381ed5d1e98494ae33bae23c6d8dade8487182a2734c60aa325b9cbbd1f629a5`），测试通过后恢复了 Git 工作树版本；此过程没有产生测试数据提交。

Source Count 测试依赖 Linux 非回环 dummy 网卡。Windows CRLF 使容器 entrypoint 无法解析；本次在同一固定离线镜像中执行 entrypoint 明确的 `ip link` 初始化与 `setpriv` 步骤，随后运行官方 pytest 目录，17 项全部通过。容器网络隔离保持开启，产品源码和公开测试均只读挂载。

## 合并与冲突处理

- 本地分支从冻结的 `2026-competition` 基线整合了 CSV、Pi、HTTP、Source Count 和 Embedding。推送发现远端已有较新的集成 HEAD `d0d90e333cfe1d5f5bb0dd241d40bb86eaf16891`，该 HEAD 已包含 Context Delta；为避免覆盖，已将远端集成历史合入并保留 Context Delta 源码、测试和报告。
- 保留远端历史后的集成 merge commit：`1e2503f5d36e7a391f86c554061c98268cb9dd0e`，其第二父提交为原远端 HEAD `d0d90e333cfe1d5f5bb0dd241d40bb86eaf16891`。
- CSV 与 Pi 都修改 `src/powercontext/sources/__init__.py`；该文件已按语义合并两项 Source 实现与导出。
- 先前赛题共用的 `reports/architecture.md` 等文件产生 add/add 冲突。每个分支的原始报告已保存在 `reports/previous_competition/<task>/`，避免覆盖；集成报告使用单独文件名。
- Embedding 合并没有源码冲突。`git ls-files -u` 无未解决冲突，`git diff --check` 通过。
- Embedding 后续加入 Provider 异常恢复测试与最终测试报告，以 merge commit `65b5b6b0e9f63e7e2522d5118d8ba741ab3b3f85` 合回集成分支；生产源码与既有四题没有冲突。
- 远端旧 `reports/submission.md` 是 CSV 分题报告，与本次总提测报告冲突；其原文已由 `reports/previous_competition/csv-row-ingestion/submission.md` 保存且字节校验相同，当前总提测文档保留在 `reports/submission.md`。远端 Context Delta、HTTP、Pi 与 Source Count 专题报告均保留在各自目录。
- Context Delta 不是本次从未确认分支新引入；它已在远端总分支，并有 14 项公开 acceptance 与修复测试的本地记录。没有合并其他未确认分支；`master` 未修改。

## 联合验收

| 检查 | 结果 |
| --- | --- |
| Fork / 公开状态 | PASS：GitHub API 返回 `private=false`、`fork=true`、parent=`oceanbase/powercontext` |
| CSV 行级采集 | PASS：17 passed in 16.34s |
| Pi 会话采集 | PASS：15 passed in 20.74s |
| HTTP Rerank | PASS：10 passed in 16.54s |
| Source 数量触发 | PASS：最终合并树 17 passed in 349.35s，固定断网容器 |
| Embedding 缓存 | PASS：保留 Context Delta 后的最终集成源码状态 8 passed in 16.92s |
| 新增 Embedding 单测 | PASS：最终集成源码状态 14 passed in 7.23s；并发去重、取消隔离和 Provider 故障/重试 8 项连续 3 轮通过（6.34s、6.25s、5.92s） |
| Context Delta acceptance 与共存回归 | 37 passed、1 failed in 152.46s；14 项公开 acceptance 与包/修复单测通过，共存 e2e 因 Worker 未消费 Source 超时 |
| CSV、Pi、HTTP、Context Delta、Embedding 联合公开验收 | PASS：64 passed in 27.92s |
| 六项代码题最终合并树公开验收 | PASS：上述 64 项加 Source Count 17 项，共 81 passed；Source Count 在同一工作树的固定断网容器中单独运行 |
| Ruff / format | PASS：竞赛配置下 8 个功能模块/测试文件 lint 通过且格式正确 |
| Ty | PASS：Embedding 模块与对应单测通过定向类型检查 |
| Pi、release、evidence 定向回归 | 34 passed、5 failed；Pi 与 release 通过，5 个 scan 用例受 WSL 缺少 `jq` 影响 |
| Topic Memory 定向回归 | 14 passed、4 failed；4 项均为后台 Worker 未及时发布结果，详见下文 |
| 完整 PowerContext 回归 | 未通过：首次全量 39 failed、3717 passed、141 skipped、6 warnings；未将其记为 PASS |

单独对更大的合并文件组执行竞赛 Ruff 配置时发现 12 条既有兼容/格式诊断，集中于运行时文件已有的 Python 3.11 `override`/泛型写法与长消息，以及 CSV 综合测试的长行；没有因此修改无关基线代码。对新增 Embedding 源码和测试的定向 Ruff、format、Ty 均通过。

## 全量回归与失败归因

直接 pytest 全量回归收集 3895 items，最终 **3717 passed、141 skipped、39 failed、6 warnings（46:19）**。该轮在 Context Delta 远端历史合入前执行，使用的 `git archive` 工作区快照漏掉了 Git 已跟踪的根目录 `scripts/`，导致证据扫描脚本和 release helper 无法按真实工作树运行；当时开发 venv 也未启用 pytest-asyncio，4 个 async 用例因此报告不支持 async 函数。随后切换到真实整合工作树并启用 `asyncio_mode=auto` 复跑：Pi comprehensive、release version、evidence scan 合计 **34 passed、5 failed**。Pi 和 release 均通过；换行敏感的脚本及中文文档在复跑期间临时规范为 LF，测试后恢复原始字节。evidence scan 有 5 项因 WSL 没有 `jq`，摘要明确记录 `finding_diagnostics=jq_unavailable`，故不计通过。

另外复跑 `tests/e2e/test_topic_memory_product_chain.py` 和 `tests/e2e/test_topic_memory_qwen_settings.py`：**14 passed、4 failed in 326.00s**。失败为 E0 hermetic chain、configured provider hybrid/fallback 和 Qwen 的 inferred/declared 两种 family 配置；均表现为 Worker 没有在测试期限内发布 Topic Memory。E0 脱敏 worker 诊断为 `TimeoutError`，fake provider 仅记录一次 embedding 调用。为检查赛题八是否引入该问题，在四题集成提交 `a6dde1e20508a62b8b06d711ea82a6f587ae1901`（Embedding 合并前）重跑同一个 E0 用例，得到相同 `TimeoutError` 与一次 embedding 调用；因此 E0 超时可确认先于赛题八存在。其余三个 Worker 失败没有逐一做基线对照，保留为未解决回归风险。

Context Delta 共存回归的 `tests/e2e/test_integrated_competition.py` 在当前保留远端分支的工作树中为 **1 failed in 152.46s**，失败为 Native automatic processing 超时；其余 37 个一起运行的 Context Delta acceptance、单元与修复用例通过。为了排除赛题八影响，在原远端 HEAD `d0d90e333cfe1d5f5bb0dd241d40bb86eaf16891` 的临时 worktree 上用相同 WSL 环境复跑该 e2e，仍以同一 `Native automatic processing timed out` 失败（1 failed in 139.03s）。因此该共存测试失败也可确认在本次 Embedding 合入前已存在于当前 WSL 环境；旧远端分支此前记录的 Windows 本地共存测试通过结果仍保留在 `reports/integration-validation.md`。

全量首轮其余失败组包括 worker prompt usage 超时（3）、observability（5）、OpenCode plugin host（1）、scheduled experience incubation（1）、CLI zcode（2）和 LoCoMo plus runner（9）；这些组尚未在修正环境后全部重跑，不能据首轮失败直接判断为本次提交引入。完整回归总体结论仍是未通过/未完全确认。`make test` 本身因 `uv` 下载 `hatch-vcs` 超时未进入 pytest，完整 pytest 是直接运行的。

## 得分说明

公开的 Fork 关系和五个代码题公开验收均通过，理论目标为 110 分。全仓回归尚有上述 WSL 环境问题及未复核失败组，平台必测组也未运行。实际官方得分尚待用户手动提测；没有向 OceanBase 平台发起提交。

集成分支通过普通 fast-forward 推送，赛题八独立分支与集成分支的远端 HEAD 均已核对与本地一致。未 force push、未修改 `master`，也未执行官方提测。
