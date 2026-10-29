"""A minimal task manager used as the SDD business sample.

The module is deliberately dependency free so the SDD context module can import,
index and test it in a clean environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

VALID_STATUSES = ("active", "done", "archived")


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    status: str
    priority: int = 0

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "title": self.title, "status": self.status, "priority": self.priority}


@dataclass
class TaskStore:
    tasks: list[Task] = field(default_factory=list)

    def add(self, task: Task) -> Task:
        self.tasks.append(task)
        return task

    def list_tasks(self, status: str | None = None) -> list[dict[str, object]]:
        """Return every task ordered by descending priority then ascending id.

        ``status`` is accepted for the SPEC-REQ-001 query contract but the filter
        is not implemented yet.
        """

        del status
        return [task.as_dict() for task in sorted(self.tasks, key=lambda item: (-item.priority, item.id))]

    def find_by_id(self, task_id: int) -> Task | None:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None


def build_default_store() -> TaskStore:
    store = TaskStore()
    store.add(Task(id=1, title="Write specification", status="active", priority=5))
    store.add(Task(id=2, title="Implement feature", status="done", priority=3))
    store.add(Task(id=3, title="Archive old notes", status="archived", priority=1))
    return store


def filter_by_status(tasks: Iterable[Task], status: str | None) -> list[Task]:
    """Return the tasks whose status equals ``status``; ``None`` keeps every task."""

    if status is None:
        return list(tasks)
    return [task for task in tasks if task.status == status]
