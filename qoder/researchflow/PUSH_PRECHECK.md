# PUSH_PRECHECK.md — 推送前检查结论与待授权操作

检查时间：2026-10-29
分支：`2026-competition-ecosystem`
远端：`origin/2026-competition-ecosystem` = `d647275c308e09b7b623f322a26f5c4e85734fb0`（基线，未变）
本地：领先 9 个提交、落后 0 个提交 → **远端未分叉**，正常推送即可 fast-forward，无需 force。

---

## 1. 检查结果

| 检查项 | 结论 |
| --- | --- |
| 改动范围 | 仅 `qoder/researchflow/**`（126 个文件），其他赛题目录与 worktree 零改动 |
| 真实密钥/密码 | 未发现（`.env` 未跟踪，仓库内仅 `.env.example` 占位值） |
| 不应公开的文件 | **发现 1 处**：PowerContext 验收运行期产物被提交进历史 |
| 个人资料 | **发现 1 处**：完整 Qoder UID 曾被写入 `SUBMISSION.md` |
| 大文件/二进制 | `verification/acceptance-run/` 为文本日志与报告，体积可控 |

### 1.1 运行期产物（已在 HEAD 清除，但存在于历史）

`qoder/researchflow/services/powercontext-acceptance-data/` 下 5 个文件：

- `.powercontext.db.cursor-key`（32 字节，PowerContext 本地数据库游标加密密钥）
- `.powercontext.db.cursor-key.lock`
- `powercontext.db-shm`、`powercontext.db-wal`（SQLite 运行期文件，含记忆明文）
- `powercontext.db.pc-migration-state/maintenance.json`

引入提交：`e5df155d`；存在于 `e5df155d`、`745f9561`、`503c965e`、`dd834fd2`、`0c71d86c`、`bbd42ce4` 共 6 个提交的树中。
风险：这是**本地**密钥（非远端凭据），泄露面限于随仓库公开的 SQLite 运行期数据；但属于「不应公开的文件」，且与 WAL 同时公开等于可解读其中的记忆内容。

### 1.2 完整 Qoder UID（已在 HEAD 清除，但存在于历史）

`<REDACTED-QODER-UID>` 出现在 `bbd42ce4` 的 `SUBMISSION.md:58`。
风险：个人身份标识进入公开比赛仓库。
说明：`QODER_LOG.md` 与 `SITE_DEPLOYMENT.md` 中保留的是截断形式 `01a175e3-…`（仅前 8 位十六进制，不可反推完整 UID），作为 `creator_uid` 报错证据使用。

### 1.3 已完成的清理（提交 `29c2cf06`，前向、非破坏性）

- 5 个运行期文件转存到已忽略路径 `services/powercontext-data/acceptance-backup/powercontext-acceptance-data/`（**文件未删除**，仍在本地磁盘）；
- `.gitignore` 补充 `services/powercontext-acceptance-data/`、`*.db-wal`、`*.db-shm`、`*.db-journal`、`*cursor-key*`；
- `SUBMISSION.md` 改为不完整记录 UID，指向 Qoder 账号页截图取证；
- 校验：`git ls-files qoder/researchflow/services` 为空；`git grep <REDACTED> HEAD` 无命中。

**但 `29c2cf06` 只让 HEAD 变干净，不能让历史变干净。** 直接推送会把上述 6 个提交连同敏感 blob 一起发布到远端，且一旦推送即不可撤回（远端对象可能被镜像/缓存）。因此本轮**未执行推送**。

---

## 2. 需要本人决策的操作（三选一）

### 方案 A（推荐）：改写这 9 个未推送提交，再正常推送

只影响当前分支范围内、且**从未推送过**的提交；不涉及其他 worktree 的分支，不涉及 master，推送仍是 fast-forward（无 force）。

```bash
cd D:/OceanBase/PowerContext-researchflow

# 0) 备份当前分支指针（可随时恢复）
git branch backup/pre-clean-researchflow

# 1) 从历史中移除运行期产物与完整 UID（仅限本分支未推送区间）
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch --force --tree-filter '
  rm -rf qoder/researchflow/services/powercontext-acceptance-data
  if [ -f qoder/researchflow/SUBMISSION.md ]; then
    sed -i "s/<REDACTED-QODER-UID>/<REDACTED-QODER-UID>/g" qoder/researchflow/SUBMISSION.md
  fi
' -- d647275c308e09b7b623f322a26f5c4e85734fb0..HEAD

# 2) 校验历史已干净（两条命令都应无输出 / 计数为 0）
for c in $(git rev-list d647275c..HEAD); do
  git ls-tree -r --name-only $c -- qoder/researchflow/services/powercontext-acceptance-data
done
for c in $(git rev-list d647275c..HEAD); do
  git grep -l "<REDACTED>" $c -- qoder/researchflow
done

# 3) 校验工作树与测试未受影响
git status --short            # 应为空
cd qoder/researchflow/backend && python -m pytest tests/ -q   # 149 passed

# 4) 正常推送（fast-forward，不加 --force）
cd D:/OceanBase/PowerContext-researchflow
git push origin 2026-competition-ecosystem

# 5) 校验远端 SHA 与本地一致
git fetch origin
git rev-parse HEAD origin/2026-competition-ecosystem   # 两行应完全相同

# 6) 确认无误后删除备份分支与 filter-branch 原始引用
git branch -D backup/pre-clean-researchflow
git update-ref -d refs/original/refs/heads/2026-competition-ecosystem
```

若本机已安装 `git-filter-repo`，可用等价且更快的写法：

```bash
git filter-repo --force --refs d647275c308e09b7b623f322a26f5c4e85734fb0..HEAD \
  --path qoder/researchflow/services/powercontext-acceptance-data --invert-paths \
  --replace-text <(echo '<REDACTED-QODER-UID>==><REDACTED-QODER-UID>')
```

### 方案 B：不改写历史，接受运行期产物与 UID 进入远端

```bash
git push origin 2026-competition-ecosystem
```

不推荐：完整 UID 与本地 cursor-key 会永久留在公开仓库历史中；比赛仓库通常会被镜像。若选择此方案，请至少先在 Qoder 账号侧确认该 UID 可公开。

### 方案 C：从基线重建一个干净的单提交历史

不改写现有提交，改为在基线之上新建一个只含最终干净树的提交并推送（远端仍在基线，因此也是 fast-forward）。
代价：丢失 9 个提交的分阶段粒度，且本地分支与远端从此不同源，后续更新需要额外处理。仅在方案 A 不可行时使用；执行前请明确告知，不要自行选择此方案。

---

## 3. 推送后的收尾核对

- [ ] `git rev-parse HEAD` == `git rev-parse origin/2026-competition-ecosystem`
- [ ] 远端分支上 `git log --stat d647275c..origin/2026-competition-ecosystem` 的路径全部以 `qoder/researchflow/` 开头
- [ ] 在远端网页端搜索 `powercontext-acceptance-data` 与 `<REDACTED>`，均应无结果
- [ ] 更新 `SUBMISSION.md` §5：将「仓库推送（待授权）」勾选为已完成，并填写推送后的提交 SHA
