# 赛题七要求与评分项

赛题：Processing 01「按新增来源条目数触发记忆处理」，满分 20 分。评分为全有或全无：公开测试和平台必测组全部通过得 20 分，任一必测项失败得 0 分。

## 要求来源

- 冻结题目说明：[instruction.md](../competition/challenges/processing-01-count-trigger/instruction.md)
- 公开验收：[test_count.py](../competition/challenges/processing-01-count-trigger/acceptance/test_count.py) 与 [checks.py](../competition/challenges/processing-01-count-trigger/acceptance/checks.py)
- 官方提交及自测说明：[competition README](../competition/README.md)
- 原始赛题链接：[OceanBase Yuque](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/kv2g0mm2fdfdda7x)

原始 Yuque 页面在本次开发环境中无法打开；要求以仓库冻结赛题说明及随附的公开验收文件为准。验收数据来自 Trace Commons 固定 revision `147684b2fdacbbdcd473e92962f565902b2739d5`，测试使用本地确定性 OpenAI 兼容服务，不要求在线模型。

## 按评分行为整理

| 必测组 | 通过要求 |
| --- | --- |
| 配置与计数 | `RuntimeConfig` 提供 `memory_source_count_threshold` 和 `topic_memory_source_count_threshold`；默认 `None`；非空必须是严格正整数，拒绝 `bool`、字符串、浮点数、零和负数。按 scope 与 family 分别统计成功 cursor 之后的持久化 Source journal 身份。重复 capture 和 receipt 信任升级不新增身份；lineage-only Source 计数，但不成为生成证据。 |
| 启动与消费边界 | 达到数量门槛即可自动接受处理，不需要 flush；时间条件与数量条件为 OR。`None` 保持原时间行为。显式 Memory/Topic Memory flush 不受数量门槛阻挡。Memory 每次仍受 `source_window_limit` 限制，成功后按新 cursor 重算剩余数；Topic Memory 一旦接受 wave，须按原逻辑完成其后续窗口。 |
| 隔离与恢复 | scope、Memory、Topic Memory 的游标和门槛互不替代。不足门槛的输入在重启后保留；已接受请求失败后按原机制重试，失败不推进成功 cursor；重启时恢复已接受工作，不重复计算已消费历史。 |
| 原生结果 | 使用项目既有 worker 生成可检索的 Memory/Topic Memory；保留精确 Source 引用，且输出能通过公开读取 API 在重启后继续读取。 |

官方等待上限为自动处理 45 秒、不足门槛静默观察 5 秒、故障后的原生生成尝试 30 秒。题目允许任意等价调度实现，不要求新增指定的 checkpoint、队列或 helper。
