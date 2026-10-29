"""Prove that a specification change really enters the development context.

``phase4_checks.py`` replays the two revisions that are committed in the
repository. This script answers the question a reviewer asks about the
mechanism itself:

> If I change a requirement, does the **new** requirement actually reach the
> context that MiniMax receives — or does the context keep serving the old
> text while only the version number moves?

The script therefore makes an **ad-hoc** change to the specification — a new
requirement the committed revisions do not contain, together with a bumped
version header — imports it, rebuilds the context and checks that:

* the new requirement text is present in the context;
* the new requirement was absent before the change;
* the content hash changed, so the change is not a cosmetic version bump;
* the code and test bindings survived the update;
* the superseded revision is still stored, but is not the effective one.

The script runs against an **isolated database namespace** and an **isolated
PowerContext scope**, and it restores the specification file before it exits.
The regular database and the committed evidence are therefore never touched.

Run it with::

    python minimax/scripts/check_spec_change_propagates.py
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.config import Settings, load_settings  # noqa: E402
from minimax.sdd_context.context_builder import ContextBuilder, link_materials  # noqa: E402
from minimax.sdd_context.importer import MaterialImporter  # noqa: E402
from minimax.sdd_context.powercontext_store import PowerContextStateStore  # noqa: E402
from minimax.sdd_context.seekdb_store import SeekDBStore  # noqa: E402

SPEC_PATH = REPOSITORY_ROOT / "minimax" / "specs" / "SPEC-REQ-001.md"
SPEC_ID = "SPEC-REQ-001"
TASK_ID = "TASK-SPEC-REQ-001"
TASK_TEXT = "为工单查询函数增加按 status 筛选工单的功能 list_tasks(status='active')"

# A requirement that no committed revision contains, so finding it in the
# context can only be the result of the change this script just made.
PROBE_MARKER = "PROBE-CHECK-7F3A"
PROBE_VERSION = "1.2.0"
PROBE_REVISION = "r3"
PROBE_SENTENCE = (
    f"## 8. Ad-hoc probe requirement ({PROBE_MARKER})\n\n"
    "This paragraph is inserted by `check_spec_change_propagates.py` to prove\n"
    "that a specification change actually reaches the development context.\n"
    "`list_tasks` MUST additionally accept the probe value `\"probe-7f3a\"`.\n"
)


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _drop_isolated_database(settings: Settings) -> dict[str, Any]:
    """Remove the isolated database so the run starts from an empty one."""

    import pymysql

    try:
        connection = pymysql.connect(
            host=settings.seekdb_host,
            port=settings.seekdb_port,
            user=settings.seekdb_user,
            password=settings.seekdb_password,
            connect_timeout=10,
            autocommit=True,
        )
    except Exception as error:
        return {"status": "BLOCKED", "detail": f"{type(error).__name__}: {error}"}
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{settings.seekdb_database}`")
        return {"status": "PASS", "dropped": settings.seekdb_database}
    except Exception as error:
        return {"status": "BLOCKED", "detail": str(error)[:300]}
    finally:
        connection.close()


def _create_isolated_scope(url: str) -> tuple[str | None, dict[str, Any]]:
    """Create a PowerContext scope that holds no task state before the run."""

    import httpx

    idempotency_key = f"sdd-specprobe-{uuid.uuid4().hex[:16]}"
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{url.rstrip('/')}/v1/scopes",
                json={
                    "title": idempotency_key,
                    "summary": "规格变更传播验证",
                    "idempotency_key": idempotency_key,
                },
            )
    except Exception as error:
        return None, {"status": "BLOCKED", "detail": f"{type(error).__name__}: {error}"}
    if response.status_code >= 400:
        return None, {"status": "BLOCKED", "detail": f"HTTP {response.status_code}: {response.text[:300]}"}
    payload = response.json()
    return payload.get("scope_id"), {"status": "PASS", "scope_id": payload.get("scope_id")}


def _import_materials(settings: Settings, importer: MaterialImporter) -> None:
    """Import the sample code and the tests, and bind them to the specification."""

    module_root = settings.root.resolve()
    code_paths = [module_root / "sample" / "taskmanager.py"]
    test_paths = [
        module_root / "tests" / "test_list_tasks_status_filter.py",
        module_root / "tests" / "test_list_tasks_status_wildcard.py",
        module_root / "tests" / "test_taskmanager_regression.py",
    ]
    for path in code_paths:
        importer.import_code(path)
    for path in test_paths:
        importer.import_test(path, [SPEC_ID])
    link_materials(
        importer,
        importer.store,
        spec_id=SPEC_ID,
        spec_version=importer.store.latest_specification(SPEC_ID)["version"],
        code_paths=[path.relative_to(module_root).as_posix() for path in code_paths],
        test_paths=[path.relative_to(module_root).as_posix() for path in test_paths],
    )


def _effective_specification(context: Any) -> dict[str, Any]:
    return context.specifications[0] if context.specifications else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove a specification change reaches the context")
    parser.add_argument("--output", default=None)
    arguments = parser.parse_args(argv)

    base = load_settings()
    base.ensure_directories()

    # An isolated namespace, so the probe cannot rewrite the stored revisions
    # of the regular database.
    scope_id, scope_report = _create_isolated_scope(base.powercontext_url)
    settings = Settings(
        **{
            **base.__dict__,
            "seekdb_database": f"{base.seekdb_database}_specprobe",
            "powercontext_scope_id": scope_id or "",
        }
    )
    drop_report = _drop_isolated_database(settings)

    original = SPEC_PATH.read_text(encoding="utf-8")
    payload: dict[str, Any] = {
        "mode": "SPEC_CHANGE_PROPAGATION",
        "description": (
            "临时修改一条规格要求（并提升版本号），重新导入并重建上下文，"
            "证明新要求真的进入了上下文，而不仅仅是版本号变化。"
            "运行结束后规格文件被还原，隔离库被删除。"
        ),
        "probe_marker": PROBE_MARKER,
        "isolated_database": settings.seekdb_database,
        "isolated_scope": scope_report,
        "database_reset": drop_report,
    }

    try:
        store = SeekDBStore(settings)
        store.initialize()
        importer = MaterialImporter(store, settings.root)
        state_store = PowerContextStateStore(settings)
        builder = ContextBuilder(store, state_store, settings.root)

        importer.import_specification(SPEC_PATH, SPEC_ID)
        _import_materials(settings, importer)
        before = builder.build(TASK_ID, TASK_TEXT, SPEC_ID)
        before_spec = _effective_specification(before)
        before_text = str(before_spec.get("content", ""))

        # The change: a new requirement the committed revisions do not
        # contain, with a bumped version header, exactly like a real revision.
        changed = original.replace("| Spec version | 1.1.0 |", f"| Spec version | {PROBE_VERSION} |")
        changed = changed.replace("| Revision | r2 |", f"| Revision | {PROBE_REVISION} |")
        changed = changed.rstrip() + "\n\n" + PROBE_SENTENCE
        SPEC_PATH.write_text(changed, encoding="utf-8")
        importer.import_specification(SPEC_PATH, SPEC_ID)
        after = builder.build(TASK_ID, TASK_TEXT, SPEC_ID)
        after_spec = _effective_specification(after)
        after_text = str(after_spec.get("content", ""))
    finally:
        # Always leave the working tree exactly as it was found.
        SPEC_PATH.write_text(original, encoding="utf-8")

    stored_versions = [
        row["version"]
        for row in store.query(
            "SELECT version FROM sdd_specification WHERE spec_id = %s ORDER BY version",
            (SPEC_ID,),
        )
    ]

    checks = {
        "version_advanced": before_spec.get("version") != after_spec.get("version"),
        "content_hash_changed": before_spec.get("content_hash") != after_spec.get("content_hash"),
        "new_requirement_reaches_context": PROBE_MARKER in after_text,
        "new_requirement_absent_before": PROBE_MARKER not in before_text,
        "context_resolves_exactly_one_specification": len(after.specifications) == 1,
        "code_binding_survived": bool(after.code),
        "test_binding_survived": bool(after.tests),
        "superseded_revision_still_stored": len(stored_versions) > 1,
        "effective_revision_is_the_newest": bool(stored_versions)
        and after_spec.get("version") == stored_versions[-1],
        "working_tree_restored": SPEC_PATH.read_text(encoding="utf-8") == original,
    }

    payload["before"] = {
        "version": before_spec.get("version"),
        "revision": before_spec.get("revision"),
        "content_hash": before_spec.get("content_hash"),
        "contains_probe": PROBE_MARKER in before_text,
    }
    payload["after"] = {
        "version": after_spec.get("version"),
        "revision": after_spec.get("revision"),
        "content_hash": after_spec.get("content_hash"),
        "contains_probe": PROBE_MARKER in after_text,
        "code_files": sorted({item["file_path"] for item in after.code}),
        "test_files": sorted({item["file_path"] for item in after.tests}),
    }
    payload["stored_versions"] = stored_versions
    payload["checks"] = checks
    payload["status"] = "PASS" if all(checks.values()) else "FAIL"

    payload["database_cleanup"] = _drop_isolated_database(settings)

    output = (
        Path(arguments.output)
        if arguments.output
        else base.evidence_dir / "spec_change_propagation.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
