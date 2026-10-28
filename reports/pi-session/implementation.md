# 赛题三：Pi 会话分支采集与断点恢复 - 实现细节与关键代码

## 一、修改与新增文件清单

| 文件路径 | 变更类型 | 说明 |
| :--- | :--- | :--- |
| `src/powercontext/sources/pi_session.py` | **新增** | 核心实现：数据模型、JSONL 分支解析、正文规范化投影、稳定标识生成、增量 Checkpoint 与 PiSessionConnector |
| `src/powercontext/sources/__init__.py` | **修改** | 导出 `PiSessionInput`, `PiEventInput`, `PiEventSource`, `PiSessionConnector`, `parse_pi_session`, `pi_event_source_id`, `PI_EVENT_SOURCE_DEFINITION` |
| `tests/test_pi_session_comprehensive.py` | **新增** | 全面单元测试与回归测试集（覆盖结构、工具调用、大文本未截断、断点恢复、3次重复执行稳定性、Scope 隔离等 19 项测试） |
| `reports/requirements.md` | **新增** | 需求与评分标准分析报告 |
| `reports/architecture.md` | **新增** | 架构与算法设计文档 |
| `reports/implementation.md` | **新增** | 源码实现说明文档 |
| `reports/test_results.md` | **新增** | 真实测试结果及日志 |
| `reports/recovery_tests.md` | **新增** | 断点、重启及失败恢复验证报告 |
| `reports/submission.md` | **新增** | 提交信息与提测参数汇总 |

---

## 二、关键类与函数实现

### 1. 数据模型与稳定身份 (`src/powercontext/sources/pi_session.py`)

```python
class PiSessionInput(BaseModel):
    content: bytes
    leaf_id: str | None = None

    def __init__(self, content: bytes = b"", leaf_id: str | None = None, **data: Any) -> None:
        if "content" not in data and content:
            data["content"] = content
        if "leaf_id" not in data and leaf_id is not None:
            data["leaf_id"] = leaf_id
        super().__init__(**data)


class PiEventInput(BaseModel):
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    source_id: str
    name: str = ""
    definition_version: str = "1"
    materialization: SourceMaterialization = SourceMaterialization.CAPTURED
    description: str | None = None
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _ensure_identity_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "source_id" in data and not data.get("name"):
                data["name"] = data["source_id"]
            elif "name" in data and not data.get("source_id"):
                data["source_id"] = data["name"]
        return data

    @model_validator(mode="after")
    def _validate_identity(self) -> PiEventSource:
        if not self.name:
            self.name = self.source_id
        if self.name != self.source_id:
            raise ValueError("PiEventSource name and source_id must be identical")
        return self


def pi_event_source_id(session_id: str, event_id: str) -> str:
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a non-empty string")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id must be a non-empty string")
    identity = f"pi:{session_id}:{event_id}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id length {len(identity)} exceeds limit of {MAX_SOURCE_ID_LENGTH}")
    return identity
```

### 2. 分支历史回溯与规范化正文提取 (`parse_pi_session`)

```python
def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    if not isinstance(value.content, (bytes, bytearray)):
        raise ValueError("content must be bytes")

    raw = bytes(value.content)
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as err:
        raise ValueError("Session content is not valid UTF-8") from err

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Session content is empty")

    try:
        header = json.loads(lines[0])
    except Exception as err:
        raise ValueError(f"Invalid JSON in session header: {err}") from err

    if not isinstance(header, dict):
        raise ValueError("Session header must be a JSON object")

    if header.get("type") != "session":
        raise ValueError("First record must have type='session'")
    if header.get("version") != 3:
        raise ValueError("First record must have version=3")
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("First record must have a non-empty string 'id'")

    records: list[dict[str, Any]] = []
    records_by_id: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()

    for idx, line in enumerate(lines[1:], start=2):
        try:
            record = json.loads(line)
        except Exception as err:
            raise ValueError(f"Invalid JSON on line {idx}: {err}") from err

        if not isinstance(record, dict):
            raise ValueError(f"Record on line {idx} must be a JSON object")

        rec_id = record.get("id")
        if not isinstance(rec_id, str) or not rec_id:
            raise ValueError(f"Record on line {idx} must have a non-empty string 'id'")

        if rec_id in seen_ids:
            raise ValueError(f"Duplicate record id {rec_id!r} on line {idx}")

        parent_id = record.get("parentId")
        if parent_id is not None and parent_id != "":
            if not isinstance(parent_id, str):
                raise ValueError(f"Invalid parentId on line {idx}")
            if parent_id not in seen_ids:
                raise ValueError(f"Record {rec_id!r} points to non-existent or forward parent {parent_id!r}")

        seen_ids.add(rec_id)
        records_by_id[rec_id] = record
        records.append(record)

    if not records:
        raise ValueError("No records found in session")

    if value.leaf_id is not None:
        if value.leaf_id not in records_by_id:
            raise ValueError(f"Leaf id {value.leaf_id!r} not found in session")
        leaf_id = value.leaf_id
    else:
        leaf_id = records[-1]["id"]

    chain: list[dict[str, Any]] = []
    curr: str | None = leaf_id
    visited: set[str] = set()

    while curr is not None and curr != "":
        if curr in visited:
            raise ValueError(f"Cycle detected at node {curr!r}")
        visited.add(curr)
        node = records_by_id.get(curr)
        if node is None:
            raise ValueError(f"Missing ancestor node {curr!r}")
        chain.append(node)
        curr = node.get("parentId")

    chain.reverse()

    events: list[PiEventInput] = []
    for node in chain:
        extracted = _extract_event_info(node)
        if extracted is not None:
            event_type, role, content = extracted
            events.append(
                PiEventInput(
                    session_id=session_id,
                    event_id=node["id"],
                    parent_id=node.get("parentId"),
                    event_type=event_type,
                    role=role,
                    content=content,
                    record=node,
                )
            )

    return tuple(events)
```

### 3. 断点持久化与防篡改采集器 (`PiSessionConnector`)

```python
class PiSessionConnector:
    name: str = "pi-session-history"
    version: str = "1"
    source_definitions: frozenset[str] = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession) -> ConnectorRunCompletion:
        if not self.path.exists() or not self.path.is_file():
            raise ValueError(f"File not found: {self.path}")

        content = self.path.read_bytes()
        raw = content[3:] if content.startswith(b"\xef\xbb\xbf") else content

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as err:
            raise ValueError(f"Invalid UTF-8 in {self.path}") from err

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise ValueError(f"Empty session file: {self.path}")

        # 解析并校验文件内所有记录
        all_records_by_id: dict[str, dict[str, Any]] = {}
        seen_ids: set[str] = set()
        for idx, line in enumerate(lines[1:], start=2):
            rec = json.loads(line)
            rec_id = rec.get("id")
            if not isinstance(rec_id, str) or not rec_id or rec_id in seen_ids:
                raise ValueError(f"Invalid or duplicate id on line {idx}")
            pid = rec.get("parentId")
            if pid is not None and pid != "" and pid not in seen_ids:
                raise ValueError(f"Missing parent {pid} on line {idx}")
            seen_ids.add(rec_id)
            all_records_by_id[rec_id] = rec

        # 加载已有 checkpoint 并执行历史防篡改比对
        checkpoint = session.checkpoint
        known_events: dict[str, str] = {}
        if isinstance(checkpoint, dict):
            known_events = dict(checkpoint.get("events", {}))

        for rec_id, rec in all_records_by_id.items():
            if rec_id in known_events:
                expected_digest = known_events[rec_id]
                actual_digest = _record_digest(rec)
                if actual_digest != expected_digest:
                    raise ValueError(f"Historical record {rec_id!r} was mutated")

        # 解析目标分支并仅提交未采集事件
        events = parse_pi_session(PiSessionInput(content=content, leaf_id=self.leaf_id))
        for event in events:
            if event.event_id not in known_events:
                await session.submit(event.event_id, "pi-event", event)
                known_events[event.event_id] = _record_digest(event.record)

        new_checkpoint = {
            "version": 1,
            "events": known_events,
        }

        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint=new_checkpoint,
        )
```
