"""Target functional tests for SPEC-REQ-001.

These assertions are the contract of the specification. They are written before the
implementation exists and MUST NOT be edited when the implementation changes: the
same file must fail before the change and pass after it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sample.taskmanager import build_default_store  # noqa: E402


def test_list_tasks_filters_by_active_status() -> None:
    """SPEC-REQ-001 acceptance criterion 1: only `active` tasks are returned."""

    store = build_default_store()

    result = store.list_tasks(status="active")

    assert [item["id"] for item in result] == [1]


def test_list_tasks_filters_by_done_status() -> None:
    """SPEC-REQ-001 acceptance criterion 2."""

    store = build_default_store()

    result = store.list_tasks(status="done")

    assert [item["id"] for item in result] == [2]


def test_list_tasks_filters_by_archived_status() -> None:
    """SPEC-REQ-001 acceptance criterion 3."""

    store = build_default_store()

    result = store.list_tasks(status="archived")

    assert [item["id"] for item in result] == [3]


def test_list_tasks_filters_by_unknown_status_returns_empty() -> None:
    """SPEC-REQ-001 boundary condition 3 and acceptance criterion 4."""

    store = build_default_store()

    result = store.list_tasks(status="unknown")

    assert result == []


def test_list_tasks_without_status_returns_all_tasks() -> None:
    """Compatibility constraint 1 and acceptance criterion 5."""

    store = build_default_store()

    result = store.list_tasks()

    assert [item["id"] for item in result] == [1, 2, 3]


def test_list_tasks_preserves_return_structure() -> None:
    """Compatibility constraint 2 and acceptance criterion 6."""

    store = build_default_store()

    result = store.list_tasks(status="active")

    assert len(result) == 1
    assert set(result[0]) == {"id", "title", "status", "priority"}
    assert result[0]["title"] == "Write specification"
    assert result[0]["status"] == "active"
    assert result[0]["priority"] == 5


def test_list_tasks_filter_is_case_sensitive() -> None:
    """SPEC-REQ-001 boundary condition 4."""

    store = build_default_store()

    result = store.list_tasks(status="Active")

    assert result == []


@pytest.mark.parametrize("status", ["active", "done", "archived"])
def test_list_tasks_filtered_result_keeps_priority_order(status: str) -> None:
    """Compatibility constraint 3: ordering stays priority desc, id asc."""

    store = build_default_store()

    result = store.list_tasks(status=status)

    ids = [item["id"] for item in result]
    assert ids == sorted(ids, key=lambda value: (-store.find_by_id(value).priority, value))
