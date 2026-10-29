# PUSH_PRECHECK.md — 推送前检查结论与已执行的清理

检查时间：2026-10-29
分支：`2026-competition-ecosystem`
远端：`origin/2026-competition-ecosystem` = `d647275c308e09b7b623f322a26f5c4e85734fb0`（基线，未变）
本地：领先 13 个提交、落后 0 个提交 → **远端未分叉**，正常推送即为 fast-forward，不需要也不允许 force。

**推送结果（2026-10-29 11:40 本地时间）**：`git push origin 2026-competition-ecosystem` 成功，
`d647275c..2e0e61cc`（fast-forward，无 `--force`）。推送后 `git ls-remote` 与 `git rev-parse HEAD`
均为 `2e0e61cc6dd7d0888245eaf0fd9ff32a8ad2d82a` → **远端与本地一致**。
`refs/heads/master` 仍为 `aedf7beb…`，未被触碰；8 个 worktree 全部在线。

---

## 1. 检查结论

| 检查项 | 结论 |
| --- | --- |
| 分支 / HEAD / 远端 / worktree | 逐项核对：本 worktree 为 `D:/OceanBase/PowerContext-researchflow`，分支正确，工作区干净；另有 7 个并存 worktree，各自分支未被触碰 |
| 改动范围 | 仅 `qoder/researchflow/**`，其他赛题目录与 worktree 零改动 |
| 真实密钥 / 密码 | 未发现（`.env` 未跟踪，仓库内只有 `.env.example` 占位值） |
| 不应公开的文件 | **发现 1 处**：PowerContext 验收运行期产物曾被提交进历史（见 §1.1） |
| 个人资料 | **发现 1 处**：完整 Qoder UID 曾被写入 `SUBMISSION.md`（见 §1.2） |
| 大文件 / 二进制 | `verification/` 下为文本日志、报告与站点截图，体积可控 |

### 1.1 运行期产物

`qoder/researchflow/services/powercontext-acceptance-data/` 下 5 个文件曾被跟踪：

- `.powercontext.db.cursor-key`（32 字节，PowerContext 本地数据库游标加密密钥）
- `.powercontext.db.cursor-key.lock`
- `powercontext.db-shm`、`powercontext.db-wal`（SQLite 运行期文件，含记忆明文）
- `powercontext.db.pc-migration-state/maintenance.json`

引入提交：`f2bf83ba`（原 `e5df155d`，改写前 SHA）；此后连续 6 个提交的树中都存在。
风险性质：这是**本地**密钥，不是远端凭据；但与 WAL 同时公开等于可解读其中的记忆内容，
属「不应公开的文件」。
根因：`.gitignore` 只覆盖 `services/powercontext-data/` 与 `*.db`，
未覆盖验收专用目录与 `*.db-wal` / `*.db-shm`。

### 1.2 完整 Qoder UID

`SUBMISSION.md` 曾明文记录完整 36 字符 UID（前缀 `01a175e3`；**完整值不在本仓库任何位置记录**）。
引入提交：`ad91dd1e`（原 `bbd42ce4`）。风险性质：个人身份标识进入公开比赛仓库。
保留说明：`QODER_LOG.md` 与 `SITE_DEPLOYMENT.md` 中作为 `creator_uid` 报错证据出现的
是截断形式 `01a175e3-…`（仅前 8 位十六进制，不可反推完整值），予以保留。

---

## 2. 已执行的清理

### 2.1 前向清理（工作树与 .gitignore）

- 5 个运行期文件**转存不删除**：移到已忽略路径
  `services/powercontext-data/acceptance-backup/powercontext-acceptance-data/`，本地磁盘仍完整保留；
- `.gitignore` 补充：`services/powercontext-acceptance-data/`、`*.db-wal`、`*.db-shm`、
  `*.db-journal`、`*cursor-key*`、`*.qoder.site`；
- `SUBMISSION.md` 不再记录完整 UID，改为指向 Qoder 账号页截图取证。

前向清理只让 HEAD 变干净，**不能让历史变干净**——直接推送仍会把敏感 blob 一并发布，
且推送后不可撤回（远端对象可能被镜像或缓存）。因此清理必须覆盖历史。

### 2.2 历史清理（用户明确授权「方案 A」后执行）

授权范围：仅改写**从未推送过**的本地提交；不涉及其他 worktree 的分支；不涉及 master；
推送仍为 fast-forward，不使用 force。执行顺序：

1. `git branch backup/pre-clean-researchflow`（回滚点）；
2. `git filter-branch --index-filter <清理脚本> -- d647275c..HEAD`，脚本做两件事：
   - `git rm -r --cached --ignore-unmatch qoder/researchflow/services/powercontext-acceptance-data`
   - 若该提交的 `SUBMISSION.md` 含完整 UID，则用 `git cat-file` 取出 blob、替换为
     `<REDACTED-QODER-UID>`、`git hash-object -w` 写回并 `git update-index --cacheinfo`
3. 选用 `--index-filter` 而非 `--tree-filter`：不检出工作树，12 个提交约 6 秒完成。

第一次尝试用的是 `--tree-filter` + 内联 `sed`，被 Qoder 安全分类器拦截
（理由：历史改写属破坏性操作，且需先确定敏感内容处理方案）。没有绕过：
先完成 §2.1 的非破坏性清理、把方案写成本文件、取得用户明确授权后才执行 §2.2。

### 2.3 改写结果校验（全部通过）

| 校验 | 命令 | 结果 |
| --- | --- | --- |
| 最终内容未被改动 | `git diff --stat backup/pre-clean-researchflow HEAD` | 空 → 与改写前 HEAD **逐字节一致** |
| 工作树未被污染 | `git status --short` | 空 |
| 敏感路径已从全部提交移除 | 遍历 `git rev-list d647275c..HEAD` 逐个 `git ls-tree -r --name-only <c> -- …/powercontext-acceptance-data` | 无任何输出 |
| 完整 UID 已从全部提交移除 | 遍历同一区间逐个 `git grep -l <完整 UID> <c> -- qoder/researchflow` | 无任何输出 |

改写后 SHA 对照（仅列被改动者；`7b666fb1`、`3682702b` 未变）：

| 原 SHA | 新 SHA | 提交 |
| --- | --- | --- |
| `e5df155d` | `f2bf83ba` | P3 证据问答 / HTTP API / 四页工作台 |
| `745f9561` | `e1e79cea` | P4 交付文档与验收证据 |
| `503c965e` | `a1a84e8e` | 比赛展示站与录制证据 |
| `dd834fd2` | `eec43693` | 中文记忆召回 / 多语 embedding / 安全加固 |
| `0c71d86c` | `3ffda476` | B/C/D 基准与安全审计 |
| `bbd42ce4` | `ad91dd1e` | V2 交付文档与站点数据 |
| `29c2cf06` | `63cea54c` | 清理运行时凭据与个人信息 |

> 注：V3 的三个提交（站点发布、推送前检查文档、V3 交付材料）在 §2.2 之后又经历一次
> 同样的清理（本文早期版本在示例命令里引用了完整 UID），SHA 已再次变化，
> 因此本文不记录它们的 SHA；以 `git log --oneline d647275c..HEAD` 为准。

---

## 3. 推送与推送后核对

```bash
cd D:/OceanBase/PowerContext-researchflow

# 1) 再次确认远端未分叉（若出现 behind>0，停止并报告，不要 force）
git fetch origin
git rev-list --left-right --count origin/2026-competition-ecosystem...HEAD   # 期望：0<TAB>N

# 2) 正常推送（fast-forward）
git push origin 2026-competition-ecosystem

# 3) 校验远端与本地一致
git fetch origin
git rev-parse HEAD origin/2026-competition-ecosystem    # 两行必须完全相同

# 4) 校验推送范围只含本项目路径
git log --stat d647275c..origin/2026-competition-ecosystem --name-only | grep -v '^qoder/researchflow/' | grep -v '^commit\|^Author\|^Date\|^ *$\|^    ' | head

# 5) 清理本地改写残留（确认远端无误后）
git update-ref -d refs/original/refs/heads/2026-competition-ecosystem
git branch -D backup/pre-clean-researchflow
# 注意：不要在此仓库执行 `git reflog expire --all` + `git gc --prune=now`。
# 该 object database 由 8 个 worktree 共享，而各 worktree 的 index 不是可达性根，
# 立即硬回收可能删掉其他 worktree「已 git add 但尚未提交」的 blob。
# 旧提交在本地只会留在 reflog 中，由默认两周宽限期的常规 gc 自然回收；它们从未被推送。
```

- [x] 远端 SHA == 本地 HEAD SHA（`2e0e61cc6dd7d0888245eaf0fd9ff32a8ad2d82a`）
- [x] 远端提交涉及的路径全部以 `qoder/researchflow/` 开头（`git diff --name-only d647275c..HEAD` 无越界路径）
- [x] 全部未推送提交中已无 `services/powercontext-acceptance-data` 任何文件（逐提交 `ls-tree` 扫描零命中）
- [x] 全部未推送提交中已无完整 UID 及其长片段（逐提交 `git grep` 扫描零命中；仓库内仅保留 8 位前缀证据）
- [x] 其他 worktree 的分支未被改动（`git worktree list` 8 项齐全，`refs/heads/master` 远端仍为 `aedf7beb…`）
- [x] `refs/original/` 与本次自建的 `backup/pre-clean-researchflow` 已删除；
      其余 `backup-*` 分支属他人既有分支，未触碰
- [x] 最终远端 SHA 已回填 `SUBMISSION.md` §5 第 1 项

### 3.1 推送范围

`d647275c..2e0e61cc`，13 个提交，全部位于 `qoder/researchflow/`：
P0 审计 → seekdb 证据库 + PowerContext 记忆 → 证据问答/HTTP API/四页工作台 →
P4 交付文档 → 展示站 → 中文召回与多语 embedding → B/C/D 基准与安全 → V2 交付文档 →
运行时凭据清理 → 发布文档 → 站点发布 → V3 交付材料 → 历史清理记录。
