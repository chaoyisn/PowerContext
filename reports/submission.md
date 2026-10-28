# 提交信息

## 建议提测分支

- Repository: [chaoyisn/PowerContext](https://github.com/chaoyisn/PowerContext)
- Branch: `competition/powercontext-integrated`
- 最终分支 HEAD：由终端交付信息提供（本文件与报告一并提交，避免自引用 commit id）。
- 五题源码合并 commit：`b6c70e92d027d10c1bfda620fc15a229be4c8dc3`
- 赛题八独立分支：`competition/embedding-singleflight-cache`
- 赛题八独立分支最终提交：`386339c289dce77159a99ff0ef6a387eb379b346`

## 测试与提交状态

五个功能题的官方公开验收在统一集成源码上通过：CSV 17、Pi 15、HTTP Rerank 10、Source Count Trigger 17、Embedding 8。新增 Embedding 本地单测为 14 passed；并发、取消和失败重试用例 8 项连续三轮通过。Fork 状态通过 GitHub API 确认：公开 Fork，parent 为 `oceanbase/powercontext`。

完整 PowerContext 回归未通过：首次全量 39 failed、3717 passed、141 skipped、6 warnings；纠正快照和 asyncio 配置后，Pi/release/scan 定向组为 34 passed、5 failed（5 项 scan 因 WSL 缺少 jq），Topic Memory 组为 14 passed、4 failed（后台 Worker 超时；E0 同一失败也在 Embedding 合并前提交复现）。其他全量失败组及测试环境限制见 `reports/integration_results.md`。实际官方得分未知；理论目标 110 分仅代表目标分值。本次没有调用 OceanBase 提交或提测接口，由用户手动提交。

赛题八独立分支已推送至用户 Fork，并核对远端 HEAD。集成分支将在报告提交后推送并核对远端 HEAD。
