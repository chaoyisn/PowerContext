# 05 · T1–T9 验收结果与原始日志索引

验收运行器：`scripts/run_acceptance.py`（自带独立 PowerContext `:17430` 与 API `:8788`，
真实重启与断连，不复用产品实例）。

复现命令：

```bash
cd qoder/researchflow
backend/.venv/Scripts/python scripts/run_acceptance.py
```

## 1. 结果（本次封版运行）

| 编号 | 场景 | 结果 | 耗时(ms) | 校验项 | 原始日志 |
| --- | --- | --- | --- | --- | --- |
| T1 | 上传 PDF：全部物理页有稳定记录，seekdb 保存正确 | **PASS** | 9365.6 | 20 | `logs/acceptance-20261029-100634/T1.log` |
| T2 | 明确问题：检索返回正确资料与真实页码 | **PASS** | 4211.5 | 28 | `T2.log` |
| T3 | 不存在答案的问题：不伪造 citation | **PASS** | 4647.5 | 20 | `T3.log` |
| T4 | 新建项目并保存已确认决策与 next_steps，PowerContext 实际写入 | **PASS** | 1016.4 | 17 | `T4.log` |
| T5 | 结束并重建会话后恢复之前的决策与 next_steps | **PASS** | 2083.6 | 14 | `T5.log` |
| T9-LLM | 配置 LLM 后的真实证据问答与 citation 服务端校验 | **PASS** | 3546.4 | 7 | `T9-LLM.log` |
| T6 | 重启服务后数据库与记忆仍可查询 | **PASS** | 16942.1 | 11 | `T6.log` |
| T7 | 断开 PowerContext，对比任务恢复能力，证明其真实作用 | **PASS** | 41559.8 | 19 | `T7.log` |
| T8 | 断开 seekdb，检索接口报真实错误而非返回预置答案 | **PASS** | 17487.4 | 14 | `T8.log` |
| | **合计** | **9 PASS / 0 FAIL / 0 SKIP** | | **150** | |

每个用例在报告里都带 **输入 / 预期 / 实际 / 逐项校验 / 日志路径** 五要素，
没有预填结论：`verification/acceptance-run/acceptance-report.md`（人读）与
`acceptance-report.json`（机读，`cases[].checks[]`）。

## 2. 运行环境（同一份报告内记录）

| 项目 | 值 |
| --- | --- |
| seekdb | `127.0.0.1:2881`，`5.7.25-OceanBase seekdb-v1.4.0.0`，库 `test`，前缀 `rfacc_` |
| 全文 / 向量 | `ik` 分析器；384 维 embedding（`minilm`） |
| PowerContext | `1.4.1` @ `http://127.0.0.1:17430`（验收自带） |
| LLM | `deepseek-chat`（`llm_enabled=True`，密钥仅来自环境变量） |
| run_tag | `c83a126f` |

## 3. 其他真实测试产物

| 产物 | 位置 | 说明 |
| --- | --- | --- |
| pytest 单元 + 集成 | `logs/pytest-*.log`（`149 passed`） | 直接打真实 seekdb 与真实 PowerContext；含 held-out 用例 |
| 全新环境复现 | `logs/fresh-env-20261029-094431.json`、`logs/fresh-env-run.log` | 新 venv + 新容器，评审旅程 20 步全过 |
| 检索基准 | `logs/bench-retrieval-*.json` | 三模对比与门控标定 |
| 中文记忆基准 | `logs/bench-memory-zh-*.json` | 脚本代理测量（口径见 `09-usage-impact-sources.md`） |
| 工作流测量 | `logs/bench-workflow-20261029-095416.json` | 脚本代理测量，**不是**真实用户提效 |
| SDK 缺陷复现记录 | `QODER_LOG.md` V2 09:30；`SECURITY.md` 审计行 6 | 全文腿静默丢弃 where 子句的实测与 fail-closed 修复 |

## 4. 未通过项（不隐藏）

- `BENCHMARK.md` B2：2 条「英文改写问中文原文」在默认阈值下被证据门控拦下（判为不可答），
  这是保守失败，不是错误答案；
- `BENCHMARK.md` W1：1 条排序不符预期（正确块排第 6）。

两处都保留在文档与原始 JSON 中，评审可复跑核对。
