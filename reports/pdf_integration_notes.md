# 跨题整合

实现只新增独立 Source Definition，不修改共享注册、投影、Runtime 或 Source ID 逻辑；与 CSV、Pi 的 Definition 可通过不同 input/source class 和名称共同注册，仍须整合测试。HTTP rerank、embedding 缓存和 seekdb 单 SQL 应检查 FTS 多路调用预算及排序影响；本实现强制离线 FTS。来源撤回需验证旧页引用及停用语义；query-aware evidence 和增量传输需保留完整 MemoryCitation 的 artifact revision、entry 和 version。以上均为风险审计，未合并或跨题测试。
