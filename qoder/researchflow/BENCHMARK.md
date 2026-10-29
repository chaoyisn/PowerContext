# BENCHMARK.md — 测试方法、原始结果与效果对比

所有数字来自本机真实运行（2026-10-29），原始 JSON 在 `logs/` 下，可复跑。
**基线均为脚本代理，不是人工实测**；其局限在每节明确标注，不用来夸大收益。

环境：Windows 11 / Python 3.11.7 / seekdb v1.4.0.0（Docker，127.0.0.1:2881）/
PowerContext 1.4.1（SQLite，127.0.0.1:17429）/ DeepSeek `deepseek-chat` / embedding 见各节。

---

## 1. B1 中文记忆检索（10 条查询）

数据集：`backend/tests/data/memory_queries_zh.json`（决策 2 / 实验结果 2 / 未完成 1 /
下一步 2 / 中英混合 2 / 负例 1）。项目 `bench-zh-memory`，12 条记忆 + 1 快照。
脚本：`scripts/bench_memory_zh.py`。原始结果：`logs/bench-memory-zh-20261029-090133.json`。

| 召回路径 | 命中（含负例判定） | 负例误报 | 说明 |
| --- | --- | --- | --- |
| PowerContext `search_memory`（fts5 unicode61） | 6/10 | **1/1** | 元提问（「下一步计划是什么」）词面零重叠，召回为 0；负例反而有命中 |
| PowerContext `prepare_context` | 6/10 | 1/1 | 同上 |
| 精确读取（全量 `list_memory_entries` + 快照，V1 兜底） | 字段级 100% | 0 | 不做检索，直接重组快照 |
| **ResearchFlow 本地 CJK 匹配 + kind 定向读取（V2 新增）** | **hit@3 10/10，hit@1 8/10** | **0/1** | 数据仍来自 PowerContext，仅匹配逻辑自研；`search_backend_used` 明示来源 |

问题定位结论：**存储层无损**（全量读取 100% 恢复），**召回层**是瓶颈
（unicode61 不分中文 + 元提问词面零重叠），**排序层**次要。因此修复放在召回：
CJK 二元组覆盖 + 意图→kind 定向读取 + 0.2 覆盖下限（负例单个泛化词不再误召回）。

修复前后对比（同一数据集、同一 PowerContext 实例）：

| 指标 | 修复前（仅 PowerContext 搜索） | 修复后（含本地 CJK 路径） |
| --- | --- | --- |
| 正例 hit@3 | 5/9 | 9/9 |
| 负例误报 | 1/1 | 0/1 |
| 元提问（下一步/未解决） | 0/3 | 3/3 |

---

## 2. B2 中英混合文档检索（11 条查询）

数据集：`backend/tests/data/bilingual_queries.json`（中→英 3 / 英→中 2 / 英精确 1 /
中→中 1 / 过滤 2 / 负例 2）。脚本：`scripts/bench_retrieval.py`。
原始结果：`logs/bench-retrieval-20261029-091422.json`（含两轮阈值）。

### 2.1 跨语言相似度实测（翻译句对，余弦）

| 句对 | multilingual | minilm |
| --- | --- | --- |
| 「一条记录如果在两条腿里都排第一，融合分数是 0.0328」 ↔ 英文原句 | **0.792** | 0.174 |
| 「全文分析器 ik 能正确切分中文」 ↔ 英文原句 | **0.813** | 0.442 |
| 负例（无关句） | 0.057 | 0.093 |

### 2.2 检索质量（门控阈值 0.62， shipped 默认）

| provider | mode | R@1 | R@3 | R@5 | MRR | pageAcc@1 | 延迟 ms | 负例误报 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hashing | vector | 0.78 | 0.78 | 0.78 | 0.78 | 0.78 | 23 | 0/2 |
| hashing | fulltext | 0.78 | 0.78 | 0.78 | 0.78 | 0.78 | 28 | 0/2 |
| hashing | hybrid | 0.78 | 0.78 | 0.78 | 0.78 | 0.78 | 27 | 0/2 |
| minilm | vector | 0.78 | 0.78 | 0.78 | 0.78 | 0.78 | 251 | 0/2 |
| minilm | fulltext | 0.78 | 0.78 | 0.78 | 0.78 | 0.78 | 258 | 0/2 |
| minilm | hybrid | 0.78 | 0.78 | 0.78 | 0.78 | 0.78 | 304 | 0/2 |
| multilingual | vector | 0.67 | 0.67 | 0.67 | 0.67 | 0.67 | 223 | 0/2 |
| multilingual | fulltext | 0.78 | 0.78 | 0.78 | 0.78 | 0.78 | 232 | 0/2 |
| multilingual | hybrid | 0.78 | 0.78 | 0.78 | 0.78 | 0.78 | 252 | 0/2 |

### 2.3 阈值权衡（multilingual，召回优先配置 0.28）

| mode | R@1 | R@3 | R@5 | MRR | 负例误报 |
| --- | --- | --- | --- | --- | --- |
| vector | 0.78 | **1.00** | **1.00** | 0.87 | **1/2** |
| fulltext | 0.78 | 0.89 | 0.89 | 0.83 | 1/2 |
| hybrid | 0.78 | **1.00** | **1.00** | 0.87 | 1/2 |

结论：0.28 能救回英→中改写类查询（R@5 1.00），但把一条负例（PostgreSQL/MVCC）放了进来。
证据系统里假引用比漏召回代价更高，因此 **shipped 默认保持 0.62（fp 0/2）**；
0.28 作为召回优先的可配置项写入 `.env.example` 并注明代价。

未覆盖的 2 条正例（en2zh-decision / en2zh-open）是「英文改写问中文原文」，
在 0.62 下三种 provider 均被门控拦下——如实记录为当前能力边界。

---

## 3. D 工作流提效测量

脚本：`scripts/bench_workflow.py`。原始结果：`logs/bench-workflow-20261029-095416.json`。
图表：`site/public/shots/bench-workflow.svg`。

### 3.1 工作流一：上传多文档 → 定位技术问题 → 给出引用页（6 问）

| 指标 | 基线（Ctrl-F 关键词扫描代理） | ResearchFlow（hybrid + 门控） |
| --- | --- | --- |
| 总耗时 | 0.0 ms（仅机器扫描，**不含人工阅读与核对**） | 909 ms（含 embedding、ANN、FTS、门控、引用组装） |
| 定位正确（top1） | 6/6 | 5/6 |
| 定位正确（top5 内） | 6/6 | 5/6 |
| 需人工修正 | 0 | 1（w1-hnsw 正确块排在第 6 位，top_k=5 截断） |
| 产出可点引用 / 页级证据对象 | **0**（只给页号，无证据对象、无门控、无页身份保证） | 5/6（w1-hnsw 无引用，与定位失败一致） |

说明：基线的 0ms 是**下界代理**——真实人工需要打开 PDF、逐页翻找、肉眼核对页码，
且得不到任何可追溯的证据对象；该时间无法在本机自动测量，故不虚构。
w1-hnsw 的失败在 multilingual + 0.28 配置下可恢复（见 §2.3），已作为已知限制记录。

### 3.2 工作流二：记录进度 → 结束会话 → 恢复决策与 next_steps

| 指标 | 基线（扫描手工笔记 demo/progress_notes.md） | ResearchFlow（PowerContext 保存+跨进程恢复） |
| --- | --- | --- |
| 耗时 | 0.3 ms（正则扫描代理） | 保存 599 ms + 恢复 1988 ms = 2587 ms |
| 字段恢复 | 5/7（笔记漏记 D4、N3） | 7/7 逐字段精确相等 |
| 需人工修正 | 2 | 0 |
| 结构化 / 来源指针 / 新会话可恢复 | 否 / 否 / 否 | 是 / 是（doc_id+page_no+chunk_id） / 是（独立进程实测） |

说明：笔记 fixture 故意漏记两条，用以建模「人会忘写」这一真实成本；
基线即使扫全也无法给出来源指针与跨会话恢复能力。

---

## 4. 回归与验收（非提效，但同场记录）

| 套件 | 结果 | 位置 |
| --- | --- | --- |
| pytest（V1 88 + 中文记忆 21 + 安全 25 + 保留集 15） | **149 passed** | `backend/tests/` |
| 验收 T1–T9 | **9/9 PASS，150 项校验 0 失败** | `verification/acceptance-run/` |
| 全新环境复现（新 venv / 新 seekdb 容器与卷 / 新 PowerContext 数据目录） | **20/20 步 PASS** | `logs/fresh-env-20261029-094431.json` |
| 站点渲染验证（数据/截图/刷新/移动端溢出/控制台错误） | 通过 | `scripts/verify_site.cjs` |

---

## 5. 复跑命令

```bash
python scripts/bench_memory_zh.py                       # B1
python scripts/bench_retrieval.py                       # B2（默认三 provider，阈值 0.62）
RF_RETRIEVAL_VECTOR_CONFIDENCE=0.28 python scripts/bench_retrieval.py --providers multilingual
python scripts/bench_workflow.py                        # D
python scripts/fresh_env_e2e.py                         # C1 全新环境
cd backend && python -m pytest tests/ -q                # 回归
python scripts/run_acceptance.py                        # T1-T9
```
