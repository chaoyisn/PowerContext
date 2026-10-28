# PowerContext 赛题十一：真实测试结果与验证矩阵

## 一、测试套件概览

本次针对「赛题十一：seekdb 混合检索的单 SQL 候选查询」开展了全方位、端到端的自动化测试，包括：
1. **官方基准验收套件**：`competition/challenges/retrieval-02-hybrid-search/acceptance/test_native_hybrid.py`
2. **T01~T35 扩展全覆盖单元套件**：`tests/unit/test_seekdb_single_sql_hybrid.py`
3. **基准可达性与血缘校验**：`python -m selftest_support.check_baseline`
4. **代码风格与静态规范检查**：`uv run ruff check`

---

## 二、官方验收测试运行记录

官方测试涵盖嵌入式 seekdb 实例启动、多轮追加修订、多 scope 隔离、单通道/双通道搜索、标签过滤、软删除与恢复以及最终的 EXPLAIN 索引验证：

```bash
docker run --rm ... make -C /selftest test-hybrid PYTHON=/opt/selftest-venv/bin/python PRODUCT=/candidate
```

**连续三次运行验证**：
- **第 1 次运行**：`1 passed in 35.01s`（通过率 100%）
- **第 2 次运行**：`1 passed in 34.49s`（通过率 100%）
- **第 3 次运行**：`1 passed in 32.80s`（通过率 100%）

---

## 三、T01 ~ T35 扩展测试矩阵实测结果

在 `tests/unit/test_seekdb_single_sql_hybrid.py` 中共设计 18 个综合测试用例，覆盖赛题要求的全部 35 个功能点：

| 测试用例函数 | 覆盖规范编号 | 测试核心验证目标 | 测试结果 |
| :--- | :--- | :--- | :--- |
| `test_t01_t02_t03_single_sql_hybrid_and_select_count` | T01, T02, T03 | 单 SQL 混合候选获取、候选 SELECT 数量为 1、双路均有候选 | **PASS** |
| `test_t04_fts_only_candidate` | T04 | 仅全文关键词命中候选验证 | **PASS** |
| `test_t05_vector_only_candidate` | T05 | 仅语义向量匹配命中候选验证 | **PASS** |
| `test_t06_t07_t08_deduplication_and_identity_isolation` | T06, T07, T08 | 双通道命中去重与同内容不同身份条目隔离 | **PASS** |
| `test_t09_t10_scope_filtering_and_isolation` | T09, T10 | Scope 过滤下推与跨 Scope 强隔离 | **PASS** |
| `test_t11_t12_t13_revision_and_lifecycle_filtering` | T11, T12, T13 | 当前 Revision 过滤、旧 Revision 不占 TopK、停用与恢复 | **PASS** |
| `test_t14_database_tag_filtering` | T14 | 数据库内标签过滤（TagFilter）下推验证 | **PASS** |
| `test_t15_t16_t17_limits_and_boundaries` | T15, T16, T17 | 全文/向量每路 TopK 边界与候选池截断 | **PASS** |
| `test_t18_multilingual_cjk_queries` | T18 | 中文（CJK）与中英混合查询正确性 | **PASS** |
| `test_t19_no_result_query` | T19 | 无匹配关键词与语义的查询优雅返回空 | **PASS** |
| `test_t21_embedding_profile_mismatch` | T21 | 维度或参数不匹配的 Profile 报错校验 | **PASS** |
| `test_t22_sql_injection_defense` | T22 | SQL 参数绑定对注入语句的防御有效性 | **PASS** |
| `test_t23_t24_t25_quality_and_ranking_consistency` | T23, T24, T25 | 逐 Query 候选与 RRF 排序与基线 100% 一致 | **PASS** |
| `test_t26_t27_real_seekdb_and_explain_plan` | T26, T27 | 真实 seekdb 执行计划包含 TEXT RETRIEVAL 与 VECTOR INDEX | **PASS** |
| `test_t29_t30_memory_and_topic_memory_regression` | T29, T30 | Memory 各模式检索回归 | **PASS** |
| `test_t31_sqlite_backend_compatibility` | T31 | SQLite 后端兼容性测试 | **PASS** |
| `test_t33_concurrency_isolation` | T33 | 多 Scope 并发请求隔离与无数据竞争 | **PASS** |
| `test_t34_t35_citation_verification_and_runtime_regression` | T34, T35 | Citation 精确回查与运行时全流程回归 | **PASS** |

**单元测试总计**：`18 passed in 467.06s (100% 通过)`

---

## 四、代码规范与血缘审计

1. **Ruff 检查**：
   ```bash
   uv run ruff check src/ tests/unit/
   # All checks passed! (0 errors)
   ```
2. **基线检查**：
   ```bash
   python -m selftest_support.check_baseline
   # Frozen baseline is reachable from HEAD or a fetched branch.
   ```
