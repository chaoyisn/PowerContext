# 赛题三：Pi 会话分支采集与断点恢复 - 提测信息

## 一、提测基本信息

- **赛题名称**：赛题三：Pi 会话分支采集与断点恢复
- **题目编号**：`source-02-pi-history`
- **满分**：20 分
- **比赛平台**：https://open.oceanbase.com/train/detail/21
- **代码仓库地址**：`https://github.com/chaoyisn/PowerContext`
- **提测分支 (Branch)**：`competition/pi-session-branch-resume`
- **上游基线**：`oceanbase/powercontext` (`commit dab240063bfcfa7917898dc44da4baadb3747bd0` on `2026-competition`)

---

## 二、功能交付清单

1. `src/powercontext/sources/pi_session.py`：实现 Pi 会话完整分支回溯、工具调用与结果规范化正文提取、不可变 Source 模型、`TextEvidence` 投影、稳定标识生成以及支持断点持久化与历史防篡改的 `PiSessionConnector`。
2. `src/powercontext/sources/__init__.py`：导出 Pi 会话采集模块的官方公共契约接口。
3. `tests/test_pi_session_comprehensive.py`：包含 19 项单元与回归测试（会话分支解析、工具调用排序、Unicode 保留、大工具文本无损持久化、3 次连续重复稳定性测试、多 Scope 隔离等）。
4. `reports/`：完整的需求分析 (`requirements.md`)、架构设计 (`architecture.md`)、源码实现 (`implementation.md`)、测试执行报告 (`test_results.md`)、断点恢复验证 (`recovery_tests.md`) 及本提测信息文件。

---

## 三、提测平台填写指引

在平台「成绩提测」界面中填写：

- **代码仓库地址**：`https://github.com/chaoyisn/PowerContext`
- **Branch**：`competition/pi-session-branch-resume`
- **Commit id**：`471b07bc5058b0ff3ac0a9dc9ab6dc3597ecc29b`
