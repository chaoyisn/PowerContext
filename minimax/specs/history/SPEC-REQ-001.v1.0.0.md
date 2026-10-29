# SPEC-REQ-001 — Filter tasks by status

| Field | Value |
| --- | --- |
| Requirement ID | SPEC-REQ-001 |
| Title | 工单查询函数支持按 status 筛选 |
| Spec version | 1.0.0 |
| Revision | r1 |
| Status | approved |
| Applies to | `minimax/sample/taskmanager.py` |

## 1. Functional requirement

`TaskStore.list_tasks` MUST accept an optional `status` keyword argument. When a
status value is supplied, only the tasks whose `status` equals that value are
returned. When the argument is omitted, every task is returned exactly as before.

## 2. Input and output

- Input: `status: str | None = None`.
  - `None` (or omitted) means "no filter".
  - A non-empty string means "exact, case-sensitive match on `Task.status`".
- Output: `list[dict[str, object]]` — unchanged shape.
  Each element keeps exactly the keys `id`, `title`, `status`, `priority`.

## 3. Applicable code files and symbols

| File | Symbol | Role |
| --- | --- | --- |
| `minimax/sample/taskmanager.py` | `TaskStore.list_tasks` | primary edit target |
| `minimax/sample/taskmanager.py` | `Task` | value object, must not change |
| `minimax/sample/taskmanager.py` | `TaskStore.find_by_id` | must not change |
| `minimax/sample/taskmanager.py` | `filter_by_status` | existing helper that performs the predicate |
| `minimax/sample/taskmanager.py` | `build_default_store` | fixture used by tests |

## 4. Boundary conditions

1. `status=None` and the argument being absent are equivalent.
2. An empty string is a valid filter value and matches only tasks whose status is
   the empty string (normally none).
3. A status that matches no task returns an empty list, not an error.
4. Matching is case sensitive: `"Active"` does not match `"active"`.
5. The `status` argument is keyword-only in practice; positional use is not required.

## 5. Compatibility constraints

1. `list_tasks()` with no arguments MUST keep returning every task.
2. The returned data structure MUST keep the same keys and value types.
3. The ordering rule MUST stay "descending priority, then ascending id".
4. No other query logic may change: `find_by_id`, `Task`, `build_default_store`
   and `filter_by_status` keep their current behaviour and signature.
5. The module MUST keep working without any third-party dependency.

## 6. Target test and regression tests

- Target functional test: `minimax/tests/test_list_tasks_status_filter.py`
  (`test_list_tasks_filters_by_active_status`) — MUST fail before implementation
  and MUST pass afterwards, with identical assertions.
- Regression tests: `minimax/tests/test_taskmanager_regression.py` — MUST keep
  passing before and after the change.
- Contract test: `minimax/tests/test_list_tasks_status_filter.py`
  (`test_list_tasks_without_status_returns_all_tasks`).

## 7. Acceptance criteria

1. `list_tasks(status="active")` on the default fixture returns exactly the ids
   `[1]`.
2. `list_tasks(status="done")` returns exactly the ids `[2]`.
3. `list_tasks(status="archived")` returns exactly the ids `[3]`.
4. `list_tasks(status="unknown")` returns `[]`.
5. `list_tasks()` still returns all three tasks in the order `[1, 2, 3]`.
6. Each returned dictionary still carries the keys `id`, `title`, `status`,
   `priority`.
7. The regression suite passes unchanged.
