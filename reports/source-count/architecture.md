# 按 Source 数量触发的架构

本实现沿用现有 Artifact Processing Supervisor、durable intent、family worker、journal 与成功 cursor，没有新增数据库表或计数器。

## 流程

1. `RuntimeConfig` 中两个可选阈值映射到 Memory 和 Topic Memory 的 `ArtifactProcessingBinding`。
2. 配置了数量门槛的 supervisor 每个本地调度 tick 检查一页 dirty intent；多进程数据库模式沿用 supervisor 已有轮询周期。扫描有界，继续使用现有 scope 队列和 worker 容量。
3. 对每个候选 scope，在当前事务中读取该 scope 的 Source journal head 和对应 binding 的持久化 Source cursor。待处理数为 `head_position - cursor.sequence`；初始 cursor 视作 0。Source journal 的位置只在新身份提交时递增，因此重复 capture 和信任升级不会增加该差值，lineage-only Source 会计入。
4. 达到门槛且没有未处理的 accepted request 时，在事务中递增现有 `ArtifactProcessingIntent` 请求代次，提交后入队。候选正文不参与门槛计算。
5. Worker 与恢复语义不变：Memory 每次运行一个原有 Source window；Topic Memory 在目标 head 冻结后继续完成整个 accepted wave。处理完成后，后续扫描按更新的 cursor 重新计算待处理数。

## 与既有触发器的关系

- 数量检查与既有时间扫描互相独立，任一接受工作即可启动，保持 OR 行为。
- 阈值为 `None` 时不启动数量扫描；现有默认行为和显式 flush 路径保持不变。
- `ArtifactProcessingIntentRepository` 保存已接受请求，失败和 Runtime 重启仍按既有 requested/handled generation 规则恢复。
- 每个 binding 使用自己的 cursor；同一 scope 的 Memory 与 Topic Memory 分别计数。

关键实现位于 [artifact_processing.py](../src/powercontext/builtin/runtime/artifact_processing.py)、[composition.py](../src/powercontext/builtin/runtime/composition.py)、[config.py](../src/powercontext/builtin/runtime/config.py) 和 [processing_registry.py](../src/powercontext/builtin/runtime/processing_registry.py)。

## 调度成本

仅在设置数量阈值时增加周期性 metadata 查询；每次扫描受现有队列容量和 `_DISCOVERY_PAGE_SIZE` 限制，只读取 journal head、cursor 与 intent 元数据，不读取 Source 正文。Local Runtime 的触发轮询周期为 1 秒，新增来源可在下一轮被发现；既有数据库轮询模式继续使用其 supervisor tick。
