# 技术说明：面向软件持续演进的 SDD 上下文管理系统

## 问题

规格驱动的开发里，"这次改动要动哪些代码、要满足哪些条款、上一轮做到哪了"这三类信息
通常散落在规格文档、代码库、测试文件和聊天记录里。模型拿到的上下文要么靠人手工拼，
要么靠检索猜，结果是"看起来合理但对不上规格"的补丁。本模块把这三类信息收敛成一条
可重复执行的流水线：**规格 → 物料入库 → 上下文组装 → 模型改码 → 验证 → 状态沉淀**。

## 架构

```
                 ┌──────────────┐
   规格 .md ───▶ │  MaterialImporter │──┐
   代码 .py ───▶ │  (ast 解析)      │  │
   测试 .py ───▶ └──────────────────┘  │
                                        ▼
                          ┌────────────────────────┐
                          │   seekdb (OceanBase)   │
                          │ sdd_specification       │
                          │ sdd_code_symbol         │
                          │ sdd_test                │
                          │ sdd_relation            │
                          └────────────────────────┘
                                        │ 检索 SQL
                                        ▼
   任务进展/待办/验证 ──▶ ┌────────────────────────┐
        (HTTP)           │    PowerContext Server   │
                         │ work contract + memory   │
                         └────────────────────────┘
                                        │ 状态读取
                                        ▼
                          ┌────────────────────────┐
                          │    ContextBuilder       │
                          │ 规格 + 代码 + 测试 + 状态 │
                          └────────────────────────┘
                                        │ 结构化上下文
                                        ▼
                          ┌────────────────────────┐
                          │   MiniMax (M3.1-Flash)  │
                          │ 返回 unified diff        │
                          └────────────────────────┘
                                        │ git apply
                                        ▼
                                   工作树改动
```

## 关键设计决策

**1. 物料用 AST 解析，不做文本切片。**
`MaterialImporter` 用 Python `ast` 走一遍文件，抽出函数、类与模块级变量作为
`sdd_code_symbol` 的行，抽出 `test_*` 函数作为 `sdd_test` 的行。这样数据库里的每个
符号都能回到磁盘上的真实行号，验收时可以直接核对"这个符号是不是真的存在"。
（早期版本把函数内局部变量也当成模块符号收录，已修正——只收录模块级赋值。）

**2. 规格的每个版本各自成行，并继承绑定关系。**
`sdd_specification` 以 `(spec_id, version)` 为主键，因此 v1.0.0 与 v1.1.0 并存。
`import_specification()` 检测到版本号变化时，会把上一版的 `sdd_relation`
（规格↔代码、规格↔测试的绑定）复制到新版本上。**这是规格更新能被上下文真正跟上的
关键**：否则新规格一入库就"丢失"了物料指向，上下文只能解析出规格本身。

**3. 上下文里的每个来源都必须能落地。**
`ContextBuilder` 只返回数据库里真实查出来的行，每行都带 `source_path` / `file_path`；
`sources` 段把三类来源分别汇总。验收 TEST-03 会逐个回磁盘核对文件是否存在、符号
是否真在文件里定义、测试函数是否真在测试文件里。

**4. 模型只被允许改"code"里的文件。**
`MiniMaxAgent` 的 system prompt 明确限定只改上下文 `code` 段列出的文件、不得改测试、
不得改断言，并要求返回单个 unified diff。为让补丁能干净落地，prompt 里同时给出
每个符号的**当前文件全文**（只给符号片段会让模型的行号与上下文不足）。
补丁应用顺序为 `git apply --recount` → `--recount --3way` → 原样 → `--3way`；
`--recount` 用来容忍模型给出的 hunk 行数不准。

**5. 状态存在服务端，跨进程才有意义。**
任务进展、待办、验证结果通过 PowerContext 的官方 HTTP 接口写入
（`/v1/work/contracts/create`、`/v1/memory/remember`、`/v1/work/outcomes/record`），
读取走 `/v1/memory/entries/list`。因为数据落在 PowerContext 的数据库里，进程退出后
由**全新进程**仍能读回，并被 `ContextBuilder` 合入下一次构建的上下文——
这一步在 TEST-05 中以两个独立子进程实测。

**6. Red→Green 的失败必须是功能性的。**
Red 阶段的样例代码接受 `status` 参数但显式忽略它（`del status`），因此失败是
`AssertionError` 而不是 `TypeError`；测试文件在 Red 与 Green 之间逐字节一致
（SHA256 记录在日志和验收报告里），杜绝"改断言换通过"。
哈希取自**行尾归一化后**的内容，并与 git 中的 blob 哈希交叉比对，
因此在任何平台、任何 `core.autocrlf` 设置下结果一致。

## 一次完整运行的实测数据

| 环节 | 实测结果 |
| --- | --- |
| Red (r1) | `6 failed, 12 passed`，`EXITCODE=1`，失败均为 `AssertionError` |
| MiniMax r1 | 模型 `MiniMax-M3.1-Flash`，5579→271 tokens，补丁落地 `minimax/sample/taskmanager.py` |
| Green (r1) | `18 passed`，`EXITCODE=0` |
| Red (r2) | `3 failed, 1 passed`，`EXITCODE=1`（通配符 `"*"` 未实现） |
| 规格更新 | v1.0.0 → v1.1.0，`content_hash` 变化，继承绑定 3 条 |
| MiniMax r2 | 补丁落地，生成 `None if status == "*" else status` |
| Green (r2) | `22 passed`，`EXITCODE=0` |
| seekdb | `5.7.25-OceanBase seekdb-v1.4.0.0`，四表共 39 行 |
| PowerContext | 跨进程写 3 类记录 → 新进程读回并合入上下文（读取进程 PID 与写入进程 PID 不同） |
| 验收 | TEST-01..06 全部 PASS（`minimax/evidence/acceptance_report.json`） |

## 可复现的验证入口

```bash
python minimax/scripts/verify.py --all              # 六项官方验收（退出码 0 = 全过）
python minimax/scripts/diagnose.py                   # 环境诊断：服务未起 / 密码错 / 库不存在 / 业务失败
python minimax/scripts/audit_minimax_evidence.py     # 历史调用证据审计（离线，不调用模型）
python minimax/scripts/live_minimax_check.py         # 在线真实调用验证（单独入口）
python minimax/scripts/audit_red_green.py            # r1 / r2 逐轮 Red→Green 审计
python minimax/scripts/regenerate_round_logs.py      # 从真实提交重生成 Red/Green 日志
python -m minimax.scripts.phase4_checks              # 规格更新 + 跨进程恢复
python minimax/scripts/reproduce_clean.py            # 隔离环境端到端复现
```

这些入口都只做真实操作：真实 pytest 子进程、真实 SQL、真实 HTTP。
依赖不可用时对应项判 `BLOCKED`，不会伪装成 `PASS`。

**历史审计与在线验证严格分离。** 六项验收中的 TEST-02 只读仓库里已归档的真实调用记录，
把每轮的补丁重放到改动前的代码上并跑该轮自己的目标测试，全程不消耗模型额度；
需要一次真实在线调用时使用 `live_minimax_check.py`，其结果单独存档，
不会与历史开发轮次混在一起。

## 边界与后续

- 当前只覆盖 Python 单一语言；`ast` 解析路径换成 tree-sitter 即可扩展到多语言。
- 规格以 Markdown 表格承载元信息，字段解析在 `_parse_spec_header()`；
  换成 YAML front-matter 只需改这一处。
- 上下文检索目前以规格 ID 为主、任务词为辅（`search_specifications`）；
  数据量变大后可加向量检索，但**不得**退化成"读本地文件"——那会让数据库失去意义。
