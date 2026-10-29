"""Regression tests that must keep passing before and after the SPEC-REQ-001 change.

They cover the behaviour the specification declares out of scope, so a regression
here means the implementation broke a compatibility constraint.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sample.taskmanager import Task, TaskStore, build_default_store, filter_by_status  # noqa: E402


def test_default_store_fixture_contents() -> None:
    store = build_default_store()

    assert [(task.id, task.status) for task in store.tasks] == [
        (1, "active"),
        (2, "done"),
        (3, "archived"),
    ]


def test_list_tasks_orders_by_priority_then_id() -> None:
    store = TaskStore()
    store.add(Task(id=9, title="low", status="active", priority=1))
    store.add(Task(id=4, title="high b", status="active", priority=7))
    store.add(Task(id=2, title="high a", status="active", priority=7))

    result = store.list_tasks()

    assert [item["id"] for item in result] == [2, 4, 9]


def test_list_tasks_on_empty_store_returns_empty_list() -> None:
    store = TaskStore()

    assert store.list_tasks() == []


def test_find_by_id_returns_matching_task() -> None:
    store = build_default_store()

    found = store.find_by_id(2)

    assert found is not None
    assert found.title == "Implement feature"


def test_find_by_id_returns_none_for_unknown_id() -> None:
    store = build_default_store()

    assert store.find_by_id(999) is None


def test_task_as_dict_shape_is_stable() -> None:
    task = Task(id=5, title="shape", status="active", priority=2)

    assert task.as_dict() == {"id": 5, "title": "shape", "status": "active", "priority": 2}


def test_filter_by_status_helper_keeps_none_semantics() -> None:
    store = build_default_store()

    assert len(filter_by_status(store.tasks, None)) == 3
    assert [task.id for task in filter_by_status(store.tasks, "done")] == [2]


def test_valid_statuses_constant_is_unchanged() -> None:
    from sample.taskmanager import VALID_STATUSES

    assert VALID_STATUSES == ("active", "done", "archived")
