# 赛题九要求摘要

依据：仓库随赛题发布的 [`instruction.md`](../competition/challenges/memory-01-source-lifecycle/instruction.md)、配套公开验收测试，以及冻结版 PowerContext v1.2.0。赛题总分 20 分。

## 核心契约

- 每个 scope 独立维护一个只由单写者修改的 DAG；注册后绑定固定。验收图含 4 个 Source、8–12 条 Memory 和 4 个 Topic Memory。
- Source、Memory、Topic Memory 分别绑定可精确读取的原始引用。派生节点至少有一个已注册父节点，并声明 `all` 或 `any` 策略；注册时立即计算状态。
- `SourceLifecycleEvent` 严格校验字段；Source 生命周期 revision 精确匹配，sequence 单调递增。完全相同的事件重放幂等，过期序号或同序号不同内容报错。
- 撤回/恢复按 DAG 传播。不可用 Memory 从活跃列表、搜索和 Context 移除；Topic 搜索与 Context 也须排除无依据的精确 Topic revision。恢复时复用原记录和引用。
- `generation` 不能解析不可用节点；`audit` 始终能取得绑定时的原始引用，以便读取历史内容。
- 节点绑定、事件状态和派生可用性必须持久化且按 scope 隔离。Runtime 重启后状态一致。
- 原生 Memory 写入中断后，同一事件重试须完成传播；成功重放不得新增 Memory revision。

## 公开验收范围

公开测试覆盖多层 `all`/`any`、撤回后注册派生节点、共享与独立依据、Memory/Topic 搜索、PreparedContext、历史引用、重启、事件校验及幂等重放。本次未修改官方测试或预期。

赛题要求由调用方显式给出依赖关系和事件；本实现不推断 Source 关系，也不把 Source 物理删除。
