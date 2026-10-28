# PowerContext 赛题十：自动化测试与验证报告

## 一、测试执行概览

本赛题构建了多层次自动化测试矩阵，包括官方赛题验收测试、T01-T30 定向测试集、性质测试以及相关模块回归测试。

所有关键测试均严格执行了至少 **3 次重复运行**，测试结果 100% 稳定通过。

| 测试套件 | 覆盖类别 | 测试用例数 | 运行次数 | 通过率 |
| :--- | :--- | :---: | :---: | :---: |
| **官方验收测试** (`test_evidence_selection.py`) | 查询驱动、长文本非开头命中、Unicode 预算、公开 SciFact 样本 | 3 | 3 | **100% (3/3 PASS)** |
| **赛题专项测试** (`test_query_aware_evidence_selection.py`) | T01-T30、字符坐标严格回查、信封结构、边界预算、端到端 HTTP | 33 | 3 | **100% (33/33 PASS)** |
| **API 契约测试** (`test_api_contract.py`) | OpenAPI 契约、请求与响应模型定义一致性 | 46 | 1 | **100% (46/46 PASS)** |
| **上下文组装测试** (`test_context_text_assembly.py`) | 默认组装路径兼容、Section Limit、多 Family 回归 | 25 | 1 | **100% (25/25 PASS)** |
| **召回预算门测试** (`test_recall_sufficiency_gate.py`) | Recall Sufficiency Gate、预算探测 probe_budget 兼容 | 19 | 1 | **100% (19/19 PASS)** |
| **客户端与契约测试** (`test_client.py` + `test_api_contract.py`) | 客户端调用、序列化、契约规范 | 70 | 1 | **100% (70/70 PASS)** |
| **代码规范检查** (`ruff check`) | PEP 8、代码复杂度、未引变量、字符串合规 | 全文件 | 1 | **ALL PASSED (0 Errors)** |

---

## 二、官方赛题验收测试执行记录

测试命令：
```bash
uv run pytest -q -c competition/pytest.ini --confcutdir=competition competition/challenges/context-01-evidence-selection/acceptance
```

### 3 次连续重复执行实录：

- **Run 1**:
  ```text
  ...                                                                      [100%]
  3 passed in 2.32s
  ```
- **Run 2**:
  ```text
  ...                                                                      [100%]
  3 passed in 2.26s
  ```
- **Run 3**:
  ```text
  ...                                                                      [100%]
  3 passed in 2.45s
  ```

---

## 三、T01-T30 专项用例清单与验证结论

```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
collected 33 items

tests/unit/test_query_aware_evidence_selection.py::test_t01_short_text_single_fragment PASSED [  3%]
tests/unit/test_query_aware_evidence_selection.py::test_t02_long_text_middle_hit PASSED [  6%]
tests/unit/test_query_aware_evidence_selection.py::test_t03_long_text_end_hit PASSED [  9%]
tests/unit/test_query_aware_evidence_selection.py::test_t04_multiple_relevant_fragments PASSED [ 12%]
tests/unit/test_query_aware_evidence_selection.py::test_t05_multiple_distinct_sources PASSED [ 15%]
tests/unit/test_query_aware_evidence_selection.py::test_t06_repeated_keyword_not_duplicate_exact_spans PASSED [ 18%]
tests/unit/test_query_aware_evidence_selection.py::test_t07_overlapping_fragments_merged PASSED [ 21%]
tests/unit/test_query_aware_evidence_selection.py::test_t08_adjacent_fragments_merged PASSED [ 24%]
tests/unit/test_query_aware_evidence_selection.py::test_t09_chinese_character_offset PASSED [ 27%]
tests/unit/test_query_aware_evidence_selection.py::test_t10_emoji_and_multibyte PASSED [ 30%]
tests/unit/test_query_aware_evidence_selection.py::test_t11_newlines_spaces_and_quotes PASSED [ 33%]
tests/unit/test_query_aware_evidence_selection.py::test_t12_case_and_normalization PASSED [ 36%]
tests/unit/test_query_aware_evidence_selection.py::test_t13_runtime_source_verification PASSED [ 39%]
tests/unit/test_query_aware_evidence_selection.py::test_t14_start_end_half_open_invariants PASSED [ 42%]
tests/unit/test_query_aware_evidence_selection.py::test_t15_distinct_revisions_preserved PASSED [ 45%]
tests/unit/test_query_aware_evidence_selection.py::test_t16_exact_budget_boundary PASSED [ 48%]
tests/unit/test_query_aware_evidence_selection.py::test_t17_budget_off_by_one PASSED [ 51%]
tests/unit/test_query_aware_evidence_selection.py::test_t18_citation_overhead_exceeds_budget PASSED [ 54%]
tests/unit/test_query_aware_evidence_selection.py::test_t19_chinese_utf8_byte_expansion PASSED [ 57%]
tests/unit/test_query_aware_evidence_selection.py::test_t20_multiple_candidates_budget_enforcement PASSED [ 60%]
tests/unit/test_query_aware_evidence_selection.py::test_t21_minimal_legal_budget PASSED [ 63%]
tests/unit/test_query_aware_evidence_selection.py::test_t22_empty_candidates PASSED [ 66%]
tests/unit/test_query_aware_evidence_selection.py::test_t23_unrelated_query PASSED [ 69%]
tests/unit/test_query_aware_evidence_selection.py::test_t24_deterministic_ranking PASSED [ 72%]
tests/unit/test_query_aware_evidence_selection.py::test_t25_scope_isolation PASSED [ 75%]
tests/unit/test_query_aware_evidence_selection.py::test_t26_http_e2e_api PASSED [ 78%]
tests/unit/test_query_aware_evidence_selection.py::test_t27_json_structure_integrity PASSED [ 81%]
tests/unit/test_query_aware_evidence_selection.py::test_t28_content_bytes_exact_utf8_match PASSED [ 84%]
tests/unit/test_query_aware_evidence_selection.py::test_t29_default_prepare_regression PASSED [ 87%]
tests/unit/test_query_aware_evidence_selection.py::test_t30_assembly_multi_family_regression PASSED [ 90%]
tests/unit/test_query_aware_evidence_selection.py::test_property_exact_reconstruction_and_invariants[1] PASSED [ 93%]
tests/unit/test_query_aware_evidence_selection.py::test_property_exact_reconstruction_and_invariants[2] PASSED [ 96%]
tests/unit/test_query_aware_evidence_selection.py::test_property_exact_reconstruction_and_invariants[3] PASSED [100%]

============================= 33 passed in 3.80s ==============================
```

---

## 四、基线溯源检查

命令：`uv run python -m selftest_support.check_baseline`
输出：
```text
Frozen baseline is reachable from HEAD or a fetched branch.
GitHub access and repository origin are checked separately when submitting.
```
确认代码历史基于官方 `9db17534` 基线衍化，历史完整，可顺利提测。
