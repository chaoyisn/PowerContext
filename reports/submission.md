# 赛题二：CSV 行级采集与原始记录回查 - 提测信息

## 一、提测基本信息

- **赛题名称**：赛题二：CSV 行级采集与原始记录回查
- **题目编号**：`source-01-table-evidence`
- **满分**：20 分
- **比赛平台**：https://open.oceanbase.com/train/detail/21
- **代码仓库地址**：`https://github.com/chaoyisn/PowerContext`
- **提测分支 (Branch)**：`competition/csv-row-ingestion`
- **上游基线**：`oceanbase/powercontext` (`commit dab240063bfcfa7917898dc44da4baadb3747bd0` on `2026-competition`)

---

## 二、功能交付清单

1. `src/powercontext/sources/csv_rows.py`：实现 CSV 离线解析、单行 CAPTURED Source 模型、TextEvidence 投影及 SourceDefinition 注册。
2. `src/powercontext/sources/__init__.py`：导出 CSV 行级采集模块公共契约接口。
3. `tests/test_csv_rows_comprehensive.py`：覆盖 Unicode、中文、空字段保真、跨文档同主键隔离、长度边界、多 Scope 隔离与重启回查测试。
4. `reports/`：完整的需求分析、架构设计、实现原理、测试结果和提测文档。

---

## 三、提测平台填写指引

在平台「成绩提测」弹窗中填写：

- **代码仓库地址**：`https://github.com/chaoyisn/PowerContext` （系统已默认锁定）
- **Branch**：`competition/csv-row-ingestion`
- **Commit id**：`619e5dfb431a64ac5b584160cf41546dc336268f`
