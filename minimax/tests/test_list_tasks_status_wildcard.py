"""Target functional tests for SPEC-REQ-001 revision r2 (spec version 1.1.0).

Revision r2 adds the wildcard filter value ``"*"``. These assertions are
written before the implementation exists and MUST NOT be edited when the
implementation changes: the same file must fail before the change and pass
after it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sample.taskmanager import build_default_store  # noqa: E402


def test_list_tasks_wildcard_returns_every_task() -> None:
    """Revision r2 acceptance criterion 8: the wildcard matches every task."""

    store = build_default_store()

    result = store.list_tasks(status="*")

    assert [item["id"] for item in result] == [1, 2, 3]


def test_list_tasks_wildcard_matches_unfiltered_result() -> None:
    """Revision r2 boundary condition 6: the wildcard is equivalent to no filter."""

    store = build_default_store()

    wildcard = store.list_tasks(status="*")
    unfiltered = store.list_tasks()

    assert wildcard == unfiltered


def test_list_tasks_wildcard_keeps_return_structure() -> None:
    """Compatibility constraint 2 still holds for the wildcard filter."""

    store = build_default_store()

    result = store.list_tasks(status="*")

    assert len(result) == 3
    for item in result:
        assert set(item) == {"id", "title", "status", "priority"}


def test_list_tasks_wildcard_does_not_affect_other_filters() -> None:
    """Boundary condition 4 stays true: matching remains case sensitive."""

    store = build_default_store()

    result = store.list_tasks(status="Active")

    assert result == []
