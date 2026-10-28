# 实现说明

## 代码改动

- `src/powercontext/builtin/runtime/config.py`：增加 Memory、Topic Memory 两个可空严格正整数阈值，默认关闭。
- `src/powercontext/builtin/runtime/composition.py`：按 family 将阈值注入自动处理 binding，并在缺少对应处理能力时沿用现有配置错误。
- `src/powercontext/builtin/runtime/artifact_processing.py`：新增有界数量触发扫描，基于 journal head 与 family cursor 计算待处理身份数；达到门槛后持久化现有 intent 请求、入现有队列，并在配置阈值时安排周期发现。分页位置随 supervisor leadership 丢失时重置，数据库中的请求和 cursor 保持权威。
- `src/powercontext/builtin/runtime/processing_registry.py`：将 Memory 数量触发登记为自动处理能力，纳入既有 processing manifest。

## 行为保障

- 数量触发仅生成既有 accepted intent，不直接调用模型、不改写 Source、Artifact 或 Citation。
- Memory 单窗消费和 Topic accepted wave 由原 worker 保持；门槛在各次 Memory 成功后自然按新 cursor 重判。
- 已接受请求沿用持久化 generation、现有重试和重启恢复；没有增加自动重试次数或修改失败语义。
- `None` 默认关闭计数路径；时间触发和显式 flush 的既有实现未改变。
- 配置 manifest 与数据表结构兼容性保持现有格式，不增加迁移步骤。

## 范围

只修改 Runtime 配置、binding 组合、Supervisor 计数触发和 processing manifest；未修改 CSV 采集、数据库持久化格式、Memory/Topic Memory 生成器、其他赛题测试预期或模型输出。
