# ResearchFlow 研究计划：带证据的科研知识助手

## 1. 研究目标

验证一个科研工作台能否同时满足三件事：检索有证据、结论可追溯、换会话后能继续工作。
具体到工程指标：

- 目标 A：所有回答中的引用必须能回查到 seekdb 中真实存在的文档页，伪造率为 0。
- 目标 B：任务记忆在新会话中的字段级恢复准确率为 100%（决策与 next_steps 逐条比对）。
- 目标 C：断开 PowerContext 后，检索与问答仍可用，且系统明确报告记忆不可用而非静默降级。

## 2. 已完成工作

- 已确认 seekdb v1.4.0.0 在 127.0.0.1:2881 可用，pyseekdb 1.4.0.post1 远程服务器模式连通。
- 已实测 ik / ngram / space 三种全文分析器，选定 ik 作为中文语料默认分析器。
- 已实测 PowerContext Server 1.4.1 的 scope 幂等创建、remember_memory、search_memory、prepare_context。

## 3. 已确认决策

| 编号 | 决策 | 理由 |
| --- | --- | --- |
| D1 | 文档主键使用文件内容 SHA-256 | 内容寻址天然去重，重复上传不产生新记录 |
| D2 | 页号使用 PDF 物理页号，从 1 开始，空页保留身份行 | 引用必须能被人肉眼在原文中核对 |
| D3 | 默认检索模式为 hybrid（RRF 融合） | 中文靠 ik 全文腿，英文与技术术语靠向量腿 |
| D4 | 任务记忆按「一个科研项目 = 一个 PowerContext Scope」建模 | master 分支只有 scope_id 一种隔离维度 |

## 4. 未解决问题

- Q1：all-MiniLM-L6-v2 使用英文 WordPiece 词表，中文语义向量质量有限，是否需要切换到多语模型。
- Q2：PowerContext 未配置 embedding 模型时 search_memory 只走 FTS，语义召回偏弱。
- Q3：Qoder Sites 只托管静态站点与函数，本地 FastAPI 与 seekdb 容器如何对外暴露。

## 5. 下一步计划

1. 完成 T1–T8 全部验收用例并记录真实结果，不预填。
2. 为问答加上服务端 citation 回查校验，剔除模型编造的引用。
3. 输出 Qoder Sites 部署可行性分析与三种接入方案。

## 6. 验收口径

每条用例必须记录：输入、预期、实际结果、PASS/FAIL、日志位置。
任何失败都必须原样报告，不得把未完成标记为完成。
