# 05 · T1–T9 验收结果与原始日志索引

验收运行器：`scripts/run_acceptance.py`（自带独立 PowerContext `:17430` 与 API `:8788`，
真实重启与断连，不复用产品实例）。

复现命令：

```bash
cd qoder/researchflow
backend/.venv/Scripts/python scripts/run_acceptance.py
```

## 1. 结果（运行号 `20261029-213920`，2026-10-29 21:40:59 生成）

这是**界面简化并重新发布之后**重跑的一轮；上一轮（`20261029-100634`）的同结构结果已被本轮覆盖，
两份报告结构一致，用例定义与校验项数量未改。

| 编号 | 场景 | 结果 | 耗时(ms) | 校验项 | 原始日志 |
| --- | --- | --- | --- | --- | --- |
| T1 | 上传 PDF：全部物理页有稳定记录，seekdb 保存正确 | **PASS** | 9200.0 | 20 | `logs/acceptance-20261029-213920/T1.log` |
| T2 | 明确问题：检索返回正确资料与真实页码 | **PASS** | 5198.5 | 28 | `T2.log` |
| T3 | 不存在答案的问题：不伪造 citation | **PASS** | 4833.1 | 20 | `T3.log` |
| T4 | 新建项目并保存已确认决策与 next_steps，PowerContext 实际写入 | **PASS** | 2569.7 | 17 | `T4.log` |
| T5 | 结束并重建会话后恢复之前的决策与 next_steps | **PASS** | 2146.6 | 14 | `T5.log` |
| T9-LLM | 配置 LLM 后的真实证据问答与 citation 服务端校验 | **PASS** | 3816.9 | 7 | `T9-LLM.log` |
| T6 | 重启服务后数据库与记忆仍可查询 | **PASS** | 15834.5 | 11 | `T6.log` |
| T7 | 断开 PowerContext，对比任务恢复能力，证明其真实作用 | **PASS** | 23842.4 | 19 | `T7.log` |
| T8 | 断开 seekdb，检索接口报真实错误而非返回预置答案 | **PASS** | 17277.7 | 14 | `T8.log` |
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
| run_tag | `6aa01781` |

## 3. 其他真实测试产物

| 产物 | 位置 | 说明 |
| --- | --- | --- |
| pytest 单元 + 集成 | `logs/pytest-*.log`（`149 passed`） | 直接打真实 seekdb 与真实 PowerContext；含 held-out 用例 |
| 全新环境复现 | `logs/fresh-env-20261029-222030.json`（23/23，22:20）；同日 09:44 一次 22/22、22:12 一次因端口冲突失败均保留 | 新 venv + 新容器 + 新数据目录，评审旅程本体 21 步全过，含端口前置检查与清理 |
| 检索基准 | `logs/bench-retrieval-*.json` | 三模对比与门控标定 |
| 中文记忆基准 | `logs/bench-memory-zh-*.json` | 脚本代理测量（口径见 `09-usage-impact-sources.md`） |
| 工作流测量 | `logs/bench-workflow-20261029-095416.json` | 脚本代理测量，**不是**真实用户提效 |
| 真实浏览器交互验收 | `verification/browser-acceptance/`（`interactions.json` + `interactions-run.log` + 48 张响应式截图） | **30/30 PASS**，Playwright 驱动真实 Chromium 做真实手势，渲染文本与拦截到的接口 JSON 逐字比对；含界面简化后新增的「渐进披露」用例（折叠后控件真的离开 DOM，但非默认设置仍写在按钮上）；口径见 `../VERIFICATION.md` §8 |
| SDK 缺陷复现记录 | `QODER_LOG.md` V2 09:30；`SECURITY.md` 审计行 6 | 全文腿静默丢弃 where 子句的实测与 fail-closed 修复 |

## 4. 未通过项（不隐藏）

- `BENCHMARK.md` B2：2 条「英文改写问中文原文」在默认阈值下被证据门控拦下（判为不可答），
  这是保守失败，不是错误答案；
- `BENCHMARK.md` W1：1 条排序不符预期（正确块排第 6）。
- 上游 LLM 偶发 5xx：UI 验收轮出现过一次 `/api/qa/ask` 503（第三方抖动，后端重试到上限后如实透传，
  前端表现为可读错误卡 + 重试）。已记录于 `../VERIFICATION.md` §8，未计为前端缺陷也未从证据里抹掉。

两处都保留在文档与原始 JSON 中，评审可复跑核对。
