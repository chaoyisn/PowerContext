# 赛题四：证据页检索 Recall@20 专项实验与全流程 Trace

## 1. 实验设计

- **评测环境**：真实 503 物理页持久化 SQLite 数据库（PepsiCo 2022 10-K，503 页面全部持久化与索引）
- **方案 A（原始自然语言查询）**：直接以原始自然语言问题作为 FTS 查询字符串 (`mode='fts', limit=20`)
- **方案 B（通用关键词与财务术语归一化）**：过滤指令停用词，提取大写/数字/财务名词作为单次聚合查询 (`mode='fts', limit=20`)
- **方案 C（领域加权多查询变体 + 倒数排名融合 RRF + 物理页去重）**：生成正交章节变体（3.0x）、指标变体（2.0x-2.5x）、n-gram 变体（1.0x），通过 RRF 融合并进行精确 Citation 回查去重 (`limit=20`)

## 2. 详细执行 Trace 与对比明细

### 问题 1: `financebench_id_01009`

- **原始问题**：What are the geographies that Pepsico primarily operates in as of FY2022?
- **公开 Gold 证据页 (PDF 物理页码)**：[4, 5]

#### 方案检索与召回对比：
| 检索方案 | Memory API 调用次数 | 候选返回数 | 检出黄金页 | Recall@20 | 耗时 (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| 方案 A（原始自然语言） | 1 | 20 | 1/2 | **0.50** | 382.2 |
| 方案 B（停用词过滤单查询） | 1 | 20 | 1/2 | **0.50** | 308.6 |
| 方案 C（领域加权多变体 RRF） | 20 | 144 (去重前) | **2/2** | **1.00** | 2434.0 |

#### 方案 C 查询变体明细：
`item 1 business` (权重: 3.0, 命中: 35), `our operations` (权重: 2.0, 命中: 35), `reportable segments` (权重: 2.0, 命中: 2), `divisions` (权重: 1.5, 命中: 16), `geographies` (权重: 1.5, 命中: 4), `geographic` (权重: 1.5, 命中: 2), `geographies pepsico` (权重: 1.0, 命中: 35), `pepsico primarily` (权重: 1.0, 命中: 35), `primarily operates` (权重: 1.0, 命中: 35), `operates fy` (权重: 1.0, 命中: 4), `fy 2022` (权重: 1.0, 命中: 35), `geographies pepsico primarily` (权重: 1.0, 命中: 18), `pepsico primarily operates` (权重: 1.0, 命中: 18), `primarily operates fy` (权重: 1.0, 命中: 1), `operates fy 2022` (权重: 1.0, 命中: 3)

#### 方案 C 最终 Top20 物理页码排序：
`[6, 100, 4, 9, 33, 31, 69, 54, 5, 109, 26, 71, 104, 53, 114, 107, 7, 15, 118, 141]`
- **Citation 精确回查验证**：全部通过 (PASS)

### 问题 2: `financebench_id_00735`

- **原始问题**：Has Pepsico reported any materially important ongoing legal battles from FY2022 and FY2021?
- **公开 Gold 证据页 (PDF 物理页码)**：[26]

#### 方案检索与召回对比：
| 检索方案 | Memory API 调用次数 | 候选返回数 | 检出黄金页 | Recall@20 | 耗时 (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| 方案 A（原始自然语言） | 1 | 20 | 0/1 | **0.00** | 334.2 |
| 方案 B（停用词过滤单查询） | 1 | 20 | 0/1 | **0.00** | 324.1 |
| 方案 C（领域加权多变体 RRF） | 32 | 164 (去重前) | **1/1** | **1.00** | 3304.9 |

#### 方案 C 查询变体明细：
`item 3 legal proceedings` (权重: 3.0, 命中: 35), `legal proceedings` (权重: 2.0, 命中: 35), `litigation` (权重: 1.5, 命中: 13), `pepsico reported` (权重: 1.0, 命中: 35), `reported materially` (权重: 1.0, 命中: 28), `materially important` (权重: 1.0, 命中: 13), `important ongoing` (权重: 1.0, 命中: 21), `ongoing legal` (权重: 1.0, 命中: 35), `legal battles` (权重: 1.0, 命中: 35), `battles fy` (权重: 1.0, 命中: 0), `fy 2022` (权重: 1.0, 命中: 35), `2022 fy` (权重: 1.0, 命中: 35), `fy 2021` (权重: 1.0, 命中: 35), `pepsico reported materially` (权重: 1.0, 命中: 13), `reported materially important` (权重: 1.0, 命中: 3)

#### 方案 C 最终 Top20 物理页码排序：
`[4, 26, 24, 111, 121, 118, 218, 239, 25, 119, 3, 205, 76, 37, 86, 99, 177, 68, 19, 79]`
- **Citation 精确回查验证**：全部通过 (PASS)

### 问题 3: `financebench_id_01328`

- **原始问题**：What is the quantity of restructuring costs directly outlined in Pepsico's income statements for FY2022? If restructuring costs are not explicitly outlined then state 0.
- **公开 Gold 证据页 (PDF 物理页码)**：[78]

#### 方案检索与召回对比：
| 检索方案 | Memory API 调用次数 | 候选返回数 | 检出黄金页 | Recall@20 | 耗时 (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| 方案 A（原始自然语言） | 1 | 20 | 1/1 | **1.00** | 377.9 |
| 方案 B（停用词过滤单查询） | 1 | 20 | 1/1 | **1.00** | 333.4 |
| 方案 C（领域加权多变体 RRF） | 32 | 186 (去重前) | **1/1** | **1.00** | 3591.4 |

#### 方案 C 查询变体明细：
`restructuring` (权重: 2.0, 命中: 14), `restructuring charges` (权重: 2.5, 命中: 35), `restructuring costs` (权重: 2.5, 命中: 35), `restructuring and impairment` (权重: 2.5, 命中: 35), `quantity restructuring` (权重: 1.0, 命中: 15), `costs directly` (权重: 1.0, 命中: 35), `directly pepsico` (权重: 1.0, 命中: 35), `pepsico income` (权重: 1.0, 命中: 35), `income statements` (权重: 1.0, 命中: 35), `statements fy` (权重: 1.0, 命中: 35), `fy 2022` (权重: 1.0, 命中: 35), `2022 restructuring` (权重: 1.0, 命中: 35), `costs 0` (权重: 1.0, 命中: 35), `quantity restructuring costs` (权重: 1.0, 命中: 6), `restructuring costs directly` (权重: 1.0, 命中: 13)

#### 方案 C 最终 Top20 物理页码排序：
`[79, 49, 78, 42, 46, 43, 31, 64, 48, 56, 93, 76, 55, 50, 211, 121, 68, 109, 63, 40]`
- **Citation 精确回查验证**：全部通过 (PASS)

### 问题 4: `financebench_id_03620`

- **原始问题**：What is the FY2022 unadjusted EBITDA less capex for PepsiCo? Define unadjusted EBITDA as unadjusted operating income + depreciation and amortization [from cash flow statement]. Answer in USD millions. Respond to the question by assuming the perspective of an investment analyst who can only use the details shown within the statement of cash flows and the income statement.
- **公开 Gold 证据页 (PDF 物理页码)**：[62, 64]

#### 方案检索与召回对比：
| 检索方案 | Memory API 调用次数 | 候选返回数 | 检出黄金页 | Recall@20 | 耗时 (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| 方案 A（原始自然语言） | 1 | 9 | 1/2 | **0.50** | 205.7 |
| 方案 B（停用词过滤单查询） | 1 | 20 | 2/2 | **1.00** | 312.9 |
| 方案 C（领域加权多变体 RRF） | 78 | 233 (去重前) | **2/2** | **1.00** | 7662.2 |

#### 方案 C 查询变体明细：
`consolidated statements of cash flows` (权重: 3.0, 命中: 35), `consolidated statement of cash flows` (权重: 3.0, 命中: 35), `statement of cash flows` (权重: 2.0, 命中: 29), `statements of cash flows` (权重: 2.0, 命中: 35), `operating activities` (权重: 1.5, 命中: 35), `consolidated statement of income` (权重: 3.0, 命中: 35), `consolidated statements of income` (权重: 3.0, 命中: 35), `consolidated statements of operations` (权重: 2.5, 命中: 35), `consolidated statement of operations` (权重: 2.5, 命中: 35), `consolidated statements of earnings` (权重: 2.5, 命中: 35), `operating income` (权重: 1.5, 命中: 35), `operating profit` (权重: 1.5, 命中: 35), `depreciation and amortization` (权重: 2.5, 命中: 15), `capital expenditures` (权重: 2.5, 命中: 35), `additions to property` (权重: 2.0, 命中: 35)

#### 方案 C 最终 Top20 物理页码排序：
`[54, 64, 121, 55, 31, 63, 77, 495, 111, 65, 59, 112, 107, 106, 105, 62, 53, 100, 40, 114]`
- **Citation 精确回查验证**：全部通过 (PASS)

### 问题 5: `financebench_id_04481`

- **原始问题**：What is the FY2022 unadjusted EBITDA % margin for PepsiCo? Calculate unadjusted EBITDA using unadjusted operating income and D&A (from cash flow statement). Give a response to the question by relying on the details shown in the statement of cash flows and the P&L statement.
- **公开 Gold 证据页 (PDF 物理页码)**：[62, 64]

#### 方案检索与召回对比：
| 检索方案 | Memory API 调用次数 | 候选返回数 | 检出黄金页 | Recall@20 | 耗时 (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| 方案 A（原始自然语言） | 1 | 12 | 1/2 | **0.50** | 264.2 |
| 方案 B（停用词过滤单查询） | 1 | 20 | 1/2 | **0.50** | 307.9 |
| 方案 C（领域加权多变体 RRF） | 64 | 192 (去重前) | **2/2** | **1.00** | 6297.6 |

#### 方案 C 查询变体明细：
`consolidated statements of cash flows` (权重: 3.0, 命中: 35), `consolidated statement of cash flows` (权重: 3.0, 命中: 35), `statement of cash flows` (权重: 2.0, 命中: 29), `statements of cash flows` (权重: 2.0, 命中: 35), `operating activities` (权重: 1.5, 命中: 35), `consolidated statement of income` (权重: 3.0, 命中: 35), `consolidated statements of income` (权重: 3.0, 命中: 35), `consolidated statements of operations` (权重: 2.5, 命中: 35), `consolidated statement of operations` (权重: 2.5, 命中: 35), `consolidated statements of earnings` (权重: 2.5, 命中: 35), `operating income` (权重: 1.5, 命中: 35), `operating profit` (权重: 1.5, 命中: 35), `item 7 management discussion and analysis` (权重: 3.0, 命中: 35), `management discussion and analysis` (权重: 2.5, 命中: 16), `results of operations` (权重: 2.5, 命中: 35)

#### 方案 C 最终 Top20 物理页码排序：
`[54, 121, 31, 40, 55, 495, 64, 63, 111, 59, 77, 65, 112, 107, 53, 114, 62, 4, 106, 68]`
- **Citation 精确回查验证**：全部通过 (PASS)
