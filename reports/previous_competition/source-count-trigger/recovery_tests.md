# 恢复与边界测试

公开验收对持久化恢复使用真实 SQLite 数据库、原生 Memory/Topic Memory worker、本地确定性 HTTP provider 和数据库触发器注入的写入失败；不依赖收费模型 API。

| 场景 | 验证结果 |
| --- | --- |
| Memory 数量门槛 3、单窗上限 1 | 先 capture 2 条及重复身份不处理；第 3 条触发并只消费一窗；剩余 2 条静默；新增第 4 条重新达到门槛后消费下一窗。通过。 |
| Topic Memory 数量门槛、单窗上限 1 | 重启后保留不足门槛输入；达到门槛后自动启动；已接受 wave 跨多个窗口完成，结果及 Source 引用可精确读取。通过。 |
| 作用域与 family 隔离 | 两个 scope 与两个 family 独立达到各自阈值。通过。 |
| lineage-only Source | 在 lineage Artifact 前后写入 Source，身份均计入启动阈值；生成证据仍不包含 lineage-only Source。Memory 与 Topic Memory 均通过。 |
| 重复 capture / receipt trust upgrade | 重放同一来源保持 journal sequence；receipt 的信任标记升级不制造新 identity，后续新增身份才达到阈值。通过。 |
| 持久化故障后恢复 | Memory 与 Topic Memory 分别通过 SQLite trigger 阻断 Artifact 写入；确认 native generation 已尝试且 cursor/ref 未提前提交；关闭 Runtime、移除 trigger、重启后不增加新输入即完成处理，Source 引用可读。通过。 |
| 时间条件、显式 flush 与关闭阈值 | 两个 family 的定时触发与数量阈值为 OR；阈值为 `None` 时原显式 flush 仍可处理。通过。 |

最终公开 acceptance 为 17/17 通过；配置、Memory 单窗、Topic wave 与两种 family 的失败后重启恢复关键用例重复三轮，结果均通过。详情见 [test_results.md](test_results.md)。
