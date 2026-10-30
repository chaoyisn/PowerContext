# 《记仇小镇：NPC 的复仇日记》

> Dify × OceanBase（seekdb）× PowerContext —— 2026 赛题 20 分作品

一个小镇，两个记仇的居民，和一本会跨会话翻旧账的日记。

你在小镇广场醒来。奥托镇长和猫咪侦探墨墨表面上彬彬有礼，但他们都记仇：
**你做过的每一件事都被写进日记，下次见面他们会翻出来给你看。**
偷走镇长的金王冠会立刻触发「王冠失窃案」支线；给墨墨加餐能换来松口；
给镇长恶作剧……他会"更礼貌地"记恨你。

---

## 一、架构：三层各司其职

```
                    ┌──────────────────────────────────────────┐
   玩家自然语言  →   │  Dify 1.8.0 Chatflow (advanced-chat)    │
                    │                                          │
                    │  start → code_input → http_register      │
                    │       → http_state → code_state          │
                    │       → if_action ┬→ http_action        │
                    │                   ├→ code_result        │
                    │                   └→ code_reject        │
                    │       → llm_roleplay → code_clean        │
                    │       → answer / answer_reject           │
                    └──────┬─────────────────────┬─────────────┘
                           │ HTTP (ssrf_proxy)    │ 模板注入
                           ▼                     ▼
              ┌────────────────────────┐   ┌──────────────────────┐
              │  town-backend (Flask)   │   │  LLM (Anthropic 兼容)│
              │  输入校验 / 规则判定     │──▶│  只生成台词          │
              │  事务落库 / 幂等         │   │  不碰状态            │
              └────┬──────────────┬─────┘   └──────────────────────┘
                   │              │
                   ▼              ▼
        ┌──────────────────┐  ┌──────────────────────────┐
        │ seekdb (OceanBase)│  │ PowerContext             │
        │ 人设/道具/关系/    │  │ 关键事件记忆 · 跨会话召回 │
        │ 事件/剧情进度      │  │ 按 player_id 隔离 Scope   │
        └──────────────────┘  └──────────────────────────┘
```

**职责边界是硬性的：**

| 层 | 做什么 | 绝不做什么 |
|---|---|---|
| **Dify** | 编排、意图判定、台词生成、条件分支 | 不直接改状态 |
| **seekdb** | 存人设、道具、关系数值、事件、剧情进度 | 不做规则判定 |
| **PowerContext** | 存关键事件，跨会话召回 | 不存数值状态 |
| **Python 后端** | 输入校验、规则裁定、事务落库、幂等、异常映射 | **不生成台词** |
| **LLM** | 只写台词 | **输出不可信**，任何数值都不写库 |

> 模型说"我偷到了王冠"不代表偷到了。偷没偷成由后端的确定性代码判定，
> LLM 只能在事后据此写台词。

---

## 二、目录结构

```
dify/
├── app/
│   └── memory-town-chatflow.yml   # 可导入的 Chatflow DSL（Dify 1.8.0 / DSL 0.4.0）
├── backend/
│   └── town_backend/
│       ├── api.py                 # HTTP API：校验、隔离、幂等、异常映射
│       ├── engine.py              # 规则引擎：动作分类、关系增减、剧情推进
│       ├── store.py               # seekdb 访问层（事务、约束）
│       ├── memory.py              # PowerContext 访问层（scope 绑定、读写）
│       └── config.py              # 配置
├── data/
│   ├── schema.sql                 # 8 张业务表 + CHECK 约束
│   └── seed.sql                   # 3 地点 / 2 NPC / 5 道具行
├── deploy/
│   ├── docker-compose.yaml        # Dify 精简编排 + town-backend
│   ├── .env.example               # 配置模板（不含真实密钥）
│   └── ssrf_proxy/conf.d/         # 放行 town-backend 的 squid 规则
├── scripts/
│   ├── init_seekdb.py             # 建表 + 灌种子数据
│   ├── verify_seekdb.py           # 真实 seekdb 验收（12 项）
│   ├── verify_backend_api.py      # 真实后端 API 验收（15 项）
│   ├── verify_memory.py           # 真实 PowerContext 验收（7 项）
│   ├── verify_dify_e2e.py         # 真实 Dify 全链路 T1–T9 验收（23 项）
│   ├── import_and_run_dify.py     # 导入 DSL 并跑一轮对话
│   └── run_all_checks.py          # 一条命令跑全部验收
├── tests/
│   └── test_rules.py              # Mock 单元测试（18 项，不需要任何服务）
├── examples/
│   └── play_demo.py               # 实机演示脚本
└── evidence/                      # 各次验收的 JSON 证据
```

---

## 三、跑起来

### 3.1 前置

| 组件 | 版本 | 说明 |
|---|---|---|
| Docker / Docker Compose | v2 | 跑 Dify 与 town-backend |
| seekdb（OceanBase 兼容） | 5.7.25 兼容 | 游戏状态库 |
| PowerContext | 1.4.1 | 关键事件记忆服务 |
| Python | 3.10+ | 后端与验收脚本 |

### 3.2 启动

```bash
cd dify/deploy
cp .env.example .env          # 按需修改；.env 不要提交
docker compose -f docker-compose.yaml up -d
```

`docker-compose.yaml` 启的是精简版 Dify（api / worker / worker_beat / db / redis /
sandbox / plugin_daemon / ssrf_proxy）外加 `town-backend`，**不含** nginx 与 web 前端 ——
本赛题的验收入口是 Dify 的 Console API / Service API，命令行即可驱动。

三处关键配置：

- **模型接入**：`ANTHROPIC_API_BASE_URL` 指向 Anthropic 兼容端点。本地默认用
  `host.docker.internal:15721` 的 MiniMax 代理。
- **SSRF 放行**：Dify 的 HTTP Request 节点流量全部经过 `ssrf_proxy`，
  官方模板最后一行是 `http_access deny all`。本赛题额外挂了
  `ssrf_proxy/conf.d/allow-town-backend.conf`，放行 `town-backend:8848`
  与宿主机上的模型代理、PowerContext。
- **seekdb / PowerContext 地址**：容器内访问用 `host.docker.internal`。

### 3.3 初始化游戏数据

```bash
cd dify
python scripts/init_seekdb.py
```

建 8 张表并灌入种子数据。脚本幂等，可重复执行。

### 3.4 导入 Chatflow

```bash
# 方式一：脚本导入并立刻跑一轮
python scripts/import_and_run_dify.py --email <console账号> --password <密码>

# 方式二：Dify 控制台手动导入
#   Dify → 工作室 → 导入 DSL → 选择 app/memory-town-chatflow.yml
```

### 3.5 体验游戏

```bash
python examples/play_demo.py --email <console账号> --password <密码>
```

脚本会依次演给你看：新玩家进镇 → 偷王冠 → **换新会话再进**（镇长翻旧账）→
换另一个玩家（毫无牵连）。每一步都打印真实的 seekdb 状态与 PowerContext 记忆。

手动玩（走 Dify Chatflow 调试器）时：

| 输入框 | 填什么 | 说明 |
|---|---|---|
| `player_id` | `alice` | **稳定不变**，是跨会话记忆的锚点 |
| `session_id` | 留空 | 留空则自动用 Dify 的 conversation_id |
| 对话输入 | `我要偷走镇长的金王冠` | 自由文本，任意说法都行 |

同一个 `player_id` 换一个新会话（Debugging 面板里新建会话），
镇长会记得你上次干的事 —— 这就是 PowerContext 在起作用。

---

## 四、验收

### 4.1 一条命令

```bash
cd dify
python scripts/run_all_checks.py --email <console账号> --password <密码>
```

### 4.2 真实集成测试 vs Mock 单元测试

**这两类测试严格分开报告，单元测试通过 ≠ 端到端验收通过。**

| 脚本 | 类型 | 依赖真实服务 | 覆盖 |
|---|---|---|---|
| `scripts/verify_seekdb.py` | **真实集成** | seekdb | 12 项：建表、种子、CRUD、CHECK 约束、道具转移、幂等、玩家隔离、UTF-8 |
| `scripts/verify_backend_api.py` | **真实集成** | 后端 + seekdb + PowerContext | 15 项：全部端点、动作类型、关系变化、支线触发、幂等、400/404/409、畸形请求体 |
| `scripts/verify_memory.py` | **真实集成** | PowerContext | 7 项：写入、跨实例召回、玩家隔离、空召回、Scope 绑定稳定、kind 正确 |
| `scripts/verify_dify_e2e.py` | **真实集成** | 全部（含 Dify） | 23 项：T1–T9 逐条 |
| `tests/test_rules.py` | **Mock 单元** | 无 | 18 项：动作分类优先级、道具别名、目标解析、关系增减方向、幂等哈希、ID 校验 |

### 4.3 当前结果

全部在真实环境跑通：

| 套件 | 结果 | 证据 |
|---|---|---|
| seekdb | **12/12 PASS** | `evidence/seekdb_verify.json` |
| 后端 API | **15/15 PASS** | `evidence/backend_api_verify.json` |
| PowerContext | **7/7 PASS** | `evidence/memory_verify.json` |
| Dify 全链路 T1–T9 | **23/23 PASS** | `evidence/dify_e2e.json` |
| Mock 单元测试 | **18/18 PASS** | 无需证据（stdout 即结果） |

### 4.4 T1–T9 对照

| # | 验收点 | 实现位置 | 结果 |
|---|---|---|---|
| T1 | DSL 可导入并可执行 | `app/memory-town-chatflow.yml` | **PASS** — 真实导入 13 节点 / 13 连线，导出比对未被改写；对话跑通拿到台词 |
| T2 | 新玩家进入并与 NPC 互动 | `start` → `code_input` → `http_register` | **PASS** — 玩家落库、落在小镇广场、拿到 NPC 台词 |
| T3 | 动作真的修改 seekdb 数据 | `engine.perform_action` | **PASS** — 王冠 `owner` 变成玩家、镇长好感 -15 / 怨念 +25、`plot_crown_theft` 进入 `investigating` |
| T4 | 关键事件真的写进 PowerContext | `engine._key_event_text` → `MemoryStore.remember_key_event` | **PASS** — 召回区里能查到那条 `town-key-event` |
| T5 | 新会话召回旧记忆 | `http_state` → `memory.key_events` → `llm_roleplay` 提示词 | **PASS** — 新会话里镇长主动点出"偷走金王冠" |
| T6 | 不跨玩家泄漏 | `MemoryStore` 的 scope binding 按 `player_id` | **PASS** — B 召回 0 条含 A 的内容 |
| T7 | 同样输入不同历史 → 不同反馈 | 关系数值累积 + 记忆注入提示词 | **PASS** — 有前科 25 → 50，台词明显更针对 |
| T8 | 重复请求 / 超时 / DB 异常 | `api.py` 幂等 + 异常映射；`engine` 事务 | **PASS** — 幂等回放、409 冲突、400/404/409/400/409 全部按预期 |
| T9 | 干净环境可初始化并复现 | `scripts/init_seekdb.py` + `reset_fixtures()` | **PASS** — 全新玩家走完一整轮 |

---

## 五、几个关键设计

### 5.1 幂等：靠 `sys.workflow_run_id`

Dify 每次运行都会生成一个新的 `workflow_run_id`（uuid4），后端把它当作
`Idempotency-Key`。同一请求重放不会重复扣数值、重复落事件、重复写记忆。
后端还会算请求指纹，**同一个 key 配不同内容直接 409**，而不是悄悄覆盖。

### 5.2 拒绝必须如实说出来

`http_action` 节点**故意不设** `error_strategy`。设了的话 Dify 会把真实
`status_code` / `body` 换成默认值，409 的规则拒绝就和一个网络错误长得一样，
没法区分。于是后端返回的 409 会原样传到 `code_result`，由代码节点翻译成
"被拒绝"并交给 LLM —— **镇长会拦下你，而不是假装你成功了**。

### 5.3 跨会话记忆怎么落地的

- `player_id` 稳定 → PowerContext 的 scope binding 按 `(integration, kind, external_id)`
  解析到同一个 scope；
- 关键事件写进 `kind=town-key-event`；
- **新会话**里 `GET /api/state` 把这个 scope 里的记忆召回，塞进 `memory_block`；
- `llm_roleplay` 的提示词里有一节就叫「他们记得的事（跨会话记忆）」，
  并明写规则：出现过玩家的偷窃/恶作剧/送礼时，**必须表现出还记得**。

### 5.4 找不到人时，找你算账的人会主动出现

玩家没点名任何人时，目标 NPC 的选择依据是**谁对你怨念最大** ——
这正是"记仇小镇"该有的样子。

### 5.5 台词要清洗

模型代理会返回 `<think>...</think>` 推理块（Dify 插件把它包成了 think 标签）。
`code_clean` 节点把这些剥掉，并去掉 markdown 与包裹引号，
玩家看到的应该是一句台词，不是一段思考过程。

---

## 六、边界与已知限制

- **V1 只做 2 个 NPC、3 个地点、1 条主线支线。** 后巷、墨墨的支线、
  多结局都还没做。
- **动作判定是关键词加权，不是语义理解。** "吓唬一下"这种说法目前
  判不出"恶作剧"。模型提示只能在没有关键词时破平，**不能推翻关键词**。
- **幂等键来自 `workflow_run_id`，即"一次运行一次"。** 用户在同一个
  会话里连说两遍同一句话会被当成两次独立动作（这是刻意的：说两遍
  确实该记两笔）。
- **PowerContext 的召回是整段文本匹配，不做向量检索。** V1 的事件量很小，
  够用；事件多了要另想办法。
- **模型代理强制开启 thinking，无法关闭。** 所以清洗节点是必需的，
  而不是锦上添花。
- **`town-backend` 目前无鉴权**（`X-Town-Token` 留空即不校验）。
  对外暴露前必须设置。

---

## 七、复现清单

```bash
# 0. 启动服务
cd dify/deploy && docker compose -f docker-compose.yaml up -d

# 1. 初始化游戏数据
cd .. && python scripts/init_seekdb.py

# 2. 跑全部验收
python scripts/run_all_checks.py --email <账号> --password <密码>

# 3. 玩一把
python examples/play_demo.py --email <账号> --password <密码>
```

单独跑某一项：

```bash
python scripts/verify_seekdb.py --json evidence/seekdb_verify.json
python scripts/verify_backend_api.py --json evidence/backend_api_verify.json
python scripts/verify_memory.py --json evidence/memory_verify.json
python scripts/verify_dify_e2e.py --email <账号> --password <密码> --json evidence/dify_e2e.json
python tests/test_rules.py          # Mock 单元测试，不需要服务
```

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DIFY_API_BASE` | `http://127.0.0.1:5001` | Dify Console API |
| `SDD_SEEKDB_HOST` / `_PORT` / `_DATABASE` | `127.0.0.1` / `2881` / `memory_town` | seekdb |
| `SDD_POWERCONTEXT_URL` | `http://127.0.0.1:8800` | PowerContext |
| `TOWN_BACKEND_TOKEN` | 空 | 设为非空则后端要求 `X-Town-Token` 头 |

---

## 八、安全约定

- 仓库里**没有任何真实密码、Token 或 API Key**；`deploy/.env.example` 只有占位值，
  真实 `.env` 不提交。
- 后端日志只记方法、路径、状态码与耗时，**不记录请求体**，玩家输入不会落日志。
- Dify 的 HTTP Request 节点用的是 `no-auth`，凭据不写在 DSL 里。
- 模型输出**永远不直接写库**：数值、道具归属、剧情阶段全部由后端确定性代码裁定。
- 记忆写失败会返回 **502 `memory_write_failed`**，绝不把没写进去的当成功。
