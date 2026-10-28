# 撤回、恢复及故障恢复测试记录

## 官方恢复与重启路径

官方 `test_dag_propagates_withdrawal_and_restore_to_runtime_and_context` 在持久化 SQLite 数据库上执行多个 Source 的撤回及部分恢复，检查 Memory 和 Topic 状态、搜索及 Context；关闭并重新打开 Runtime 后再次检查状态，重放相同事件并比较 Memory revision，随后完成恢复并核验所有 generation 引用。

官方 `test_new_derivatives_of_withdrawn_evidence_stay_out_of_generation` 验证撤回后才注册的 Memory/Topic 仍继承不可用状态，随后 Source 恢复令其重新可用。

上述完整公开验收套件连续运行三轮，每轮 4/4 通过。

## 故障注入与隔离

新增 `test_failed_memory_transition_completes_on_same_event_retry`：第一次原生 `MemoryService.forget` 抛出模拟写入异常，随后以完全相同事件重试，确认条目最终进入 inactive。

新增 `test_manual_memory_deactivation_survives_source_recovery`：Source 撤回后用户显式 retire Memory，再恢复 Source；确认条目仍 inactive 且 generation 解析失败。

新增 `test_scope_isolation`：两个 scope 使用相同节点编号，验证事件只影响对应 scope。

三个新增测试包含在聚焦回归中，均通过。赛题采用每 scope 单写者模型；未实现或声称覆盖多进程并发写同一 scope。
