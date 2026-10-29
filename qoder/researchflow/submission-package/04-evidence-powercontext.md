# 04 · PowerContext 真实记忆与恢复证据

PowerContext 在本项目里承担**任务连续性**角色：一个科研项目 = 一个 Scope，保存的是
「已确认决策 / 已完成工作 / 未解决问题 / 下一步」，与 seekdb 的文献证据完全分离。
它不是缓存，也不是本地 JSON：所有写入与恢复都通过 PowerContext 自己的 HTTP API。

| 项目 | 值 |
| --- | --- |
| 版本 | `powercontext==1.4.1`（package 与 server 契约 `1.4`） |
| 产品用实例 | `http://127.0.0.1:17429`（独立 venv `services/.venv-powercontext`） |
| 验收用实例 | `http://127.0.0.1:17430`（验收跑自带，避免污染产品数据） |
| Scope 绑定 | `create_scope(idempotency_key=project_id)` → 重启与重试都安全 |
| 保存语义 | 仅用户显式触发；`remember_memory` **非幂等**，因此快照去重靠上层判定 |

## 1. 写入证据

| 证据 | 位置 | 实际结果 |
| --- | --- | --- |
| 真实写入并回读 | `logs/acceptance-20261029-100634/T4.log`（1016.4 ms） | 项目 `acc-c83a126f` 绑定 scope `scp_1pdehwady4r7zmyvxhhka53vak`；6 条要点 + 1 条快照写入 PowerContext，并**用它自己的 API 读回** |
| 契约实测（改变设计的三条事实） | `QODER_LOG.md` §P2 02:40 | `create_scope` 幂等 / `remember_memory` 非幂等 / `list_memory_entries` 无序 |
| 重复保存不产生重复记忆 | 前端「显式保存研究进度」二次提交 | 返回 `内容未变化，未产生重复记忆`（`written=0`、`snapshot_unchanged=true`） |

## 2. 恢复证据

| 证据 | 位置 | 实际结果 |
| --- | --- | --- |
| 跨进程恢复 | `T5.log`（2083.6 ms） | 仅凭 `project_id`，decisions 与 next_steps 在**全新客户端进程**中逐字段一致恢复 |
| 服务重启后恢复 | `T6.log` + `powercontext-after-restart.log` | PowerContext 被杀掉并重启后，按 project_id 恢复记忆；ResearchFlow API 重启后 seekdb 数据仍可查 |
| 断连对照（证明它真的在起作用） | `T7.log`（41559.8 ms）+ `powercontext-after-t7.log` | 杀掉 PowerContext：记忆接口报真实故障且**不返回任何快照**，而检索与问答继续工作（只依赖 seekdb）；重启后同一批决策恢复 |

## 3. 中文召回的实测限制与处理

- 实测：PowerContext 内置 SQLite 全文索引为 `fts5 tokenize='unicode61'`，
  **纯中文查询返回 0 条命中**（`QODER_LOG.md` §P2 03:00、§V2 09:10）。
- 处理：在恢复路径上加了一层中文感知召回（bigram + 语义回退），并且响应里
  用 `search_backend_used` 明示这一条究竟由哪个后端答的——不冒充 PowerContext 原生能力。
- 复现：`backend/.venv/Scripts/python scripts/bench_memory_zh.py`，
  结果 `logs/bench-memory-zh-20261029-*.json`（脚本代理测量，见 `09-usage-impact-sources.md` 的口径说明）。

## 4. 边界

- 记忆按 `project_id` 隔离；未提供多用户鉴权，因此**不得**把本后端直接暴露公网（见 `06` 与 `../SECURITY.md`）。
- Scope 与项目是 1:1；换 project_id 即换记忆空间，不存在跨项目串读。
- 保存动作不自动发生：模型输出不会被写入记忆，只有用户在表单里确认后才写。
