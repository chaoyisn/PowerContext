"""Research task memory backed by PowerContext, with the project registry in seekdb.

Split of responsibilities (this is what makes acceptance test T7 meaningful):

* **seekdb** holds the project registry (``rf_projects``): id, title, objective and the
  PowerContext ``scope_id`` it maps to. Projects stay listable while PowerContext is down.
* **PowerContext** holds the memory itself: one Scope per project, Atomic Memories per
  bullet, and a JSON snapshot per save. Nothing here is ever presented as document
  evidence - every entry is tagged ``source="memory"``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from ..config import Settings, get_settings
from ..db.seekdb import SeekDBStore
from ..errors import NotFoundError, PowerContextUnavailableError, RequestValidationError
from ..logging_setup import get_logger
from .client import PowerContextGateway
from .models import (
    KINDS,
    KIND_PREFIX,
    SNAPSHOT_KIND,
    MemoryEntry,
    ResearchProgress,
    decode_entry,
    encode_item_text,
    utc_now_iso,
)

logger = get_logger(__name__)

_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def normalize_project_id(raw: str, title: str = "") -> str:
    candidate = (raw or "").strip().lower()
    if not candidate and title:
        candidate = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    if not candidate:
        candidate = f"project-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    candidate = re.sub(r"[^a-z0-9_-]+", "-", candidate).strip("-_")[:64]
    if not _PROJECT_ID.match(candidate):
        raise RequestValidationError(
            f"project_id '{candidate}' is not usable",
            detail={"pattern": _PROJECT_ID.pattern},
        )
    return candidate


@dataclass
class Project:
    project_id: str
    title: str
    objective: str
    scope_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SaveResult:
    project_id: str
    scope_id: str
    seq: int
    updated_at: str
    written: int = 0
    skipped_duplicates: int = 0
    snapshot_artifact_id: str | None = None
    snapshot_revision: int | None = None
    snapshot_unchanged: bool = False
    written_kinds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RestoreResult:
    project_id: str
    title: str
    scope_id: str | None
    memory_available: bool
    snapshot: dict[str, Any] | None = None
    entries: list[MemoryEntry] = field(default_factory=list)
    grouped: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    resume_brief: str = ""
    prepared_context: dict[str, Any] = field(default_factory=dict)
    memory_backend: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entries"] = [entry.to_dict() for entry in self.entries]
        payload["entry_count"] = len(self.entries)
        payload["source"] = "memory"
        return payload


def _row_to_project(row: dict[str, Any]) -> Project:
    return Project(
        project_id=row["project_id"],
        title=row["title"],
        objective=row["objective"] or "",
        scope_id=row.get("powercontext_scope_id"),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.isoformat()
    return str(value)


# --------------------------------------------------------------------- projects


def list_projects(store: SeekDBStore, settings: Settings | None = None) -> list[Project]:
    settings = settings or get_settings()
    rows = store.query(
        f"SELECT * FROM `{settings.projects_table}` ORDER BY updated_at DESC, project_id"
    )
    return [_row_to_project(row) for row in rows]


def get_project(store: SeekDBStore, project_id: str, settings: Settings | None = None) -> Project:
    settings = settings or get_settings()
    rows = store.query(
        f"SELECT * FROM `{settings.projects_table}` WHERE project_id = %s", (project_id,)
    )
    if not rows:
        raise NotFoundError(f"project '{project_id}' not found", detail={"project_id": project_id})
    return _row_to_project(rows[0])


def upsert_project(
    store: SeekDBStore,
    project_id: str,
    title: str,
    objective: str = "",
    scope_id: str | None = None,
    settings: Settings | None = None,
) -> Project:
    settings = settings or get_settings()
    now = _utcnow()
    store.execute(
        f"""INSERT INTO `{settings.projects_table}`
  (project_id, title, objective, powercontext_scope_id, created_at, updated_at)
VALUES (%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE
  title=VALUES(title),
  objective=IF(VALUES(objective)='', objective, VALUES(objective)),
  powercontext_scope_id=IFNULL(VALUES(powercontext_scope_id), powercontext_scope_id),
  updated_at=VALUES(updated_at)""",
        (project_id, title, objective, scope_id, now, now),
    )
    return get_project(store, project_id, settings)


async def ensure_scope(
    store: SeekDBStore,
    gateway: PowerContextGateway,
    project: Project,
    settings: Settings | None = None,
) -> str:
    """Return the PowerContext scope for a project, creating it idempotently if needed.

    ``CreateScopeRequest.idempotency_key`` is what makes this safe to call on every
    request and after every restart: the same key always resolves to the same scope_id.
    """
    settings = settings or get_settings()
    if project.scope_id:
        return project.scope_id

    from powercontext.http import CreateScopeRequest

    idempotency_key = f"{settings.powercontext_integration}:project:{project.project_id}"
    async with gateway.session() as client:
        scope = await client.create_scope(
            CreateScopeRequest(
                title=(project.title or project.project_id)[:250],
                summary=(project.objective or f"ResearchFlow project {project.project_id}")[:1900],
                idempotency_key=idempotency_key,
                external_references=[
                    {"kind": f"{settings.powercontext_integration}_project", "value": project.project_id}
                ],
            )
        )
    scope_id = scope.scope_id
    store.execute(
        f"UPDATE `{settings.projects_table}` SET powercontext_scope_id = %s, updated_at = %s "
        "WHERE project_id = %s",
        (scope_id, _utcnow(), project.project_id),
    )
    logger.info(
        "powercontext scope ready",
        fields={"project_id": project.project_id, "scope_id": scope_id, "key": idempotency_key},
    )
    return scope_id


async def create_project(
    store: SeekDBStore,
    gateway: PowerContextGateway,
    *,
    project_id: str = "",
    title: str,
    objective: str = "",
    settings: Settings | None = None,
) -> tuple[Project, bool]:
    """Register a project and bind its PowerContext scope. Returns (project, memory_bound)."""
    settings = settings or get_settings()
    if not title.strip():
        raise RequestValidationError("title must not be empty")
    pid = normalize_project_id(project_id, title)

    project = upsert_project(store, pid, title.strip(), objective.strip(), None, settings)
    try:
        await ensure_scope(store, gateway, project, settings)
        project = get_project(store, pid, settings)
    except PowerContextUnavailableError as exc:
        # The project row still exists in seekdb; the scope is bound on the next save/restore.
        logger.warning(
            "project created without PowerContext scope",
            fields={"project_id": pid, "error": str(exc)},
        )
        return project, False
    return project, True


# --------------------------------------------------------------------- memory IO


async def _read_entries(gateway: PowerContextGateway, scope_id: str) -> list[MemoryEntry]:
    from powercontext.http import ListMemoryEntriesRequest

    entries: list[MemoryEntry] = []
    cursor: str | None = None
    async with gateway.session() as client:
        while True:
            page = await client.list_memory_entries(
                ListMemoryEntriesRequest(scope_id=scope_id, limit=100, cursor=cursor)
            )
            for record in page.entries:
                entries.append(
                    decode_entry(
                        record.kind,
                        record.text,
                        record.artifact.artifact_id,
                        record.artifact.revision,
                        str(getattr(record.state, "value", record.state)),
                    )
                )
            cursor = page.next_cursor
            if not cursor:
                break
    entries.sort(key=lambda entry: (entry.seq, entry.updated_at, entry.artifact_id))
    return entries


def _latest_snapshot(entries: Sequence[MemoryEntry]) -> dict[str, Any] | None:
    snapshots = [e for e in entries if e.kind == "progress_snapshot"]
    if not snapshots:
        return None
    newest = max(snapshots, key=lambda e: (e.seq, e.updated_at))
    try:
        payload = json.loads(newest.text)
    except json.JSONDecodeError:
        return None
    payload["_artifact_id"] = newest.artifact_id
    payload["_revision"] = newest.revision
    payload["_state"] = newest.state
    return payload


async def save_progress(
    store: SeekDBStore,
    gateway: PowerContextGateway,
    progress: ResearchProgress,
    settings: Settings | None = None,
) -> SaveResult:
    """Explicitly persist a research progress snapshot plus any new bullets.

    Only called from a user action - ResearchFlow never writes model guesses here.
    """
    settings = settings or get_settings()
    progress.validate()
    project = get_project(store, progress.project_id, settings)
    scope_id = await ensure_scope(store, gateway, project, settings)

    from powercontext.http import RememberMemoryRequest

    async with gateway.session() as client:
        existing = await _read_entries(gateway, scope_id)
        # remember_memory is not idempotent (measured), so dedupe against what is stored.
        seen = {(entry.kind, entry.text) for entry in existing if entry.kind != "progress_snapshot"}
        next_seq = max((entry.seq for entry in existing), default=0) + 1

        progress.seq = next_seq
        if not progress.updated_at:
            progress.updated_at = utc_now_iso()

        written_kinds: list[str] = []
        written = 0
        skipped = 0
        for kind, content in progress.items():
            if (kind, content) in seen:
                skipped += 1
                continue
            await client.remember_memory(
                RememberMemoryRequest(
                    scope_id=scope_id,
                    kind=f"{KIND_PREFIX}{kind}",
                    text=encode_item_text(next_seq, progress.updated_at, content),
                    reason=f"explicit save by {progress.confirmed_by} (seq {next_seq})",
                )
            )
            seen.add((kind, content))
            written_kinds.append(kind)
            written += 1

        latest_snapshot = _latest_snapshot(existing)
        fingerprint = progress.content_fingerprint()
        snapshot_unchanged = bool(latest_snapshot) and latest_snapshot.get("fingerprint") == fingerprint
        if snapshot_unchanged:
            mutation = None
        else:
            mutation = await client.remember_memory(
                RememberMemoryRequest(
                    scope_id=scope_id,
                    kind=SNAPSHOT_KIND,
                    text=progress.snapshot_json(),
                    reason=f"progress snapshot seq {next_seq}",
                )
            )

    if snapshot_unchanged:
        snapshot_artifact = None
        snapshot_artifact_id = latest_snapshot.get("_artifact_id")
        snapshot_revision = latest_snapshot.get("_revision")
    else:
        snapshot_artifact = mutation.records[0].artifact if mutation and mutation.records else None
        snapshot_artifact_id = snapshot_artifact.artifact_id if snapshot_artifact else None
        snapshot_revision = snapshot_artifact.revision if snapshot_artifact else None
    if snapshot_unchanged and written == 0:
        # Nothing was persisted, so the sequence must not appear to advance.
        reported_seq = max((entry.seq for entry in existing), default=0)
    else:
        reported_seq = next_seq
    store.execute(
        f"UPDATE `{settings.projects_table}` SET objective = %s, updated_at = %s WHERE project_id = %s",
        (progress.objective or project.objective, _utcnow(), progress.project_id),
    )
    result = SaveResult(
        project_id=progress.project_id,
        scope_id=scope_id,
        seq=reported_seq,
        updated_at=progress.updated_at,
        written=written,
        skipped_duplicates=skipped,
        snapshot_artifact_id=snapshot_artifact_id,
        snapshot_revision=snapshot_revision,
        snapshot_unchanged=snapshot_unchanged,
        written_kinds=written_kinds,
    )
    logger.info(
        "progress saved to PowerContext",
        fields={
            "project_id": result.project_id,
            "scope_id": scope_id,
            "seq": reported_seq,
            "written": written,
            "skipped": skipped,
            "snapshot_unchanged": snapshot_unchanged,
        },
    )
    return result


def _group(entries: Sequence[MemoryEntry]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in (*KINDS, "progress_snapshot")}
    for entry in entries:
        grouped.setdefault(entry.kind, []).append(entry.to_dict())
    return grouped


def build_resume_brief(snapshot: dict[str, Any] | None, entries: Sequence[MemoryEntry]) -> str:
    """Deterministic 'where did I stop / what is next' brief built from stored memory only."""
    source = snapshot or {}
    lines: list[str] = []

    def bullets(label: str, values: Sequence[str]) -> None:
        if not values:
            return
        lines.append(f"{label}：")
        lines.extend(f"  - {value}" for value in values)

    title = source.get("title") or ""
    if title:
        lines.append(f"项目：{title}")
    if source.get("objective"):
        lines.append(f"研究目标：{source['objective']}")
    if source.get("updated_at"):
        lines.append(f"上次保存时间：{source['updated_at']}（seq {source.get('seq', '?')}）")
    lines.append("")
    lines.append("【上次做到了哪里】")
    bullets("已完成工作", source.get("completed_work") or [])
    bullets("已确认决策", source.get("decisions") or [])
    evidence = source.get("key_evidence") or []
    if evidence:
        lines.append("关键证据：")
        lines += [
            f"  - {item.get('filename')} 第 {item.get('page_no')} 页（chunk {item.get('chunk_id')}）"
            for item in evidence
        ]
    if not any([source.get("completed_work"), source.get("decisions"), evidence]):
        lines.append("  （快照中没有记录）")
    lines.append("")
    lines.append("【接下来该做什么】")
    bullets("下一步", source.get("next_steps") or [])
    bullets("未解决问题", source.get("open_questions") or [])
    if not any([source.get("next_steps"), source.get("open_questions")]):
        lines.append("  （快照中没有记录）")

    if not snapshot:
        kinds = {entry.kind for entry in entries if entry.kind != "progress_snapshot"}
        lines.append("")
        lines.append(f"（没有进度快照，仅有 {len(entries)} 条离散记忆，类型：{', '.join(sorted(kinds)) or '无'}）")
    lines.append("")
    lines.append("以上全部来自 PowerContext 历史记忆，不是文献原文证据。")
    return "\n".join(lines)


def build_recall_query(
    user_query: str, project: Project, snapshot: dict[str, Any] | None
) -> tuple[str, bool]:
    """Expand the recall query with ASCII anchors.

    PowerContext 1.4.1's default SQLite index is ``fts5(... tokenize='unicode61')``, which
    treats a run of CJK characters as one token, so a pure-Chinese query matches nothing
    (measured: '已确认决策' -> 0 hits, 'seekdb' -> 4 hits, '决策 D1 SHA-256' -> 4 hits).
    Appending the ASCII anchors that are genuinely present in the stored memories gives the
    FTS leg something it can match. This is query expansion, not result fabrication: the
    caller still receives the raw ``recall_query`` and the ``expanded`` flag.
    """
    base = (user_query or "").strip() or "当前研究进度 已确认决策 下一步计划 progress decisions next steps"
    anchors: list[str] = [project.project_id]
    for text in (project.title, project.objective, str((snapshot or {}).get("title", ""))):
        anchors.extend(re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+-]{1,}", text or ""))
    ordered: list[str] = []
    for anchor in anchors:
        if anchor not in ordered:
            ordered.append(anchor)
    if not ordered:
        return base, False
    expanded = f"{base} {' '.join(ordered[:8])}".strip()
    return expanded[:1000], True


async def restore_progress(
    store: SeekDBStore,
    gateway: PowerContextGateway,
    project_id: str,
    *,
    query: str = "",
    settings: Settings | None = None,
) -> RestoreResult:
    """Recover a project's task state in a brand new session."""
    settings = settings or get_settings()
    project = get_project(store, project_id, settings)
    result = RestoreResult(
        project_id=project.project_id,
        title=project.title,
        scope_id=project.scope_id,
        memory_available=False,
        memory_backend={
            "backend": "PowerContext",
            "url": gateway.url,
            "scope_id": project.scope_id,
            "role": "task memory (not document evidence)",
        },
    )

    health = await gateway.health()
    result.memory_backend.update(
        {"available": health.get("available"), "package_version": health.get("package_version")}
    )
    if not health.get("available"):
        result.error = health.get("error")
        result.resume_brief = (
            "PowerContext 当前不可用，无法恢复任务记忆。\n"
            f"原因：{result.error}\n"
            "文献检索与问答不受影响（它们只依赖 seekdb）。"
        )
        logger.warning(
            "restore skipped, PowerContext unavailable", fields={"project_id": project_id}
        )
        return result

    try:
        scope_id = await ensure_scope(store, gateway, project, settings)
    except PowerContextUnavailableError as exc:
        result.error = str(exc)
        return result

    result.scope_id = scope_id
    result.memory_available = True

    from powercontext.http import PrepareContextRequest, SearchMemoryRequest

    entries = await _read_entries(gateway, scope_id)
    result.entries = entries
    result.grouped = _group(entries)
    result.snapshot = _latest_snapshot(entries)
    result.resume_brief = build_resume_brief(result.snapshot, entries)

    raw_query = (query or "").strip()
    recall_query, expanded = build_recall_query(raw_query, project, result.snapshot)
    async with gateway.session() as client:
        prepared = await client.prepare_context(
            PrepareContextRequest(
                scope_id=scope_id,
                query=recall_query[:8000],
                max_bytes=settings.powercontext_max_context_bytes,
            )
        )
        searched = await client.search_memory(
            SearchMemoryRequest(scope_id=scope_id, query=recall_query[:8000], limit=10)
        )
    result.prepared_context = {
        "query": raw_query,
        "recall_query": recall_query,
        "recall_query_expanded": expanded,
        "status": str(getattr(prepared, "status", "")),
        "content_bytes": int(getattr(prepared, "content_bytes", 0) or 0),
        "content": getattr(prepared, "content", None),
        "search_mode": str(getattr(getattr(searched, "mode", None), "value", searched.mode)),
        "search_hits": [
            {
                "kind": hit.memory.kind,
                "text": hit.memory.text,
                "score": hit.score,
                "artifact_id": hit.memory.artifact.artifact_id,
                "source": "memory",
            }
            for hit in searched.hits
        ],
        "source": "memory",
        "note": (
            "PowerContext 1.4.1 的 SQLite 索引使用 fts5 unicode61 分词，纯中文查询无法命中；"
            "已用项目中真实存在的 ASCII 锚点扩展查询。完整记忆恢复不依赖搜索，"
            "而是通过 list_memory_entries 全量读取。"
        ),
    }
    logger.info(
        "progress restored",
        fields={
            "project_id": project_id,
            "entries": len(entries),
            "has_snapshot": result.snapshot is not None,
            "context_bytes": result.prepared_context["content_bytes"],
        },
    )
    return result


async def list_history(
    store: SeekDBStore,
    gateway: PowerContextGateway,
    project_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    project = get_project(store, project_id, settings)
    scope_id = await ensure_scope(store, gateway, project, settings)
    entries = await _read_entries(gateway, scope_id)
    snapshots = [entry for entry in entries if entry.kind == "progress_snapshot"]
    return {
        "project_id": project_id,
        "scope_id": scope_id,
        "source": "memory",
        "entry_count": len(entries),
        "snapshot_count": len(snapshots),
        "entries": [entry.to_dict() for entry in entries],
        "grouped": _group(entries),
    }
