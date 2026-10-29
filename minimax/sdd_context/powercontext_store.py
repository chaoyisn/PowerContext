"""PowerContext-backed task state for the SDD context module.

Task progress is stored through the official PowerContext HTTP contract:

* ``POST /v1/work/contracts/create`` records the task contract (objective,
  in-scope items, completion criteria).
* ``POST /v1/memory/remember`` records one state record per task field group.
* ``POST /v1/memory/entries/list`` reads the persisted records back.
* ``POST /v1/work/outcomes/record`` records verification results.

The state survives a process restart because it lives in the PowerContext
server database, not in this process.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings, load_settings


class PowerContextUnavailableError(RuntimeError):
    """Raised when the PowerContext server cannot serve the request."""


KIND_TASK_DESCRIPTION = "sdd-task-description"
KIND_COMPLETED = "sdd-completed"
KIND_TODO = "sdd-todo"
KIND_VERIFICATION = "sdd-verification"

_STATE_KINDS = (KIND_TASK_DESCRIPTION, KIND_COMPLETED, KIND_TODO, KIND_VERIFICATION)


def _prefix(task_id: str) -> str:
    return f"[{task_id}]"


class PowerContextStateStore:
    """Reads and writes SDD task state in PowerContext."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._client: httpx.Client | None = None
        self._scope_id: str | None = None

    # --------------------------------------------------------------- transport

    def _http(self) -> httpx.Client:
        if self._client is None:
            headers = {"content-type": "application/json"}
            if self.settings.powercontext_token:
                headers["authorization"] = f"Bearer {self.settings.powercontext_token}"
            self._client = httpx.Client(
                base_url=self.settings.powercontext_url,
                headers=headers,
                timeout=self.settings.powercontext_timeout,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            response = self._http().request(method, path, json=payload)
        except Exception as error:
            raise PowerContextUnavailableError(
                f"PowerContext request {method} {path} failed"
            ) from error
        if response.status_code >= 400:
            raise PowerContextUnavailableError(
                f"PowerContext {method} {path} returned {response.status_code}: {response.text[:400]}"
            )
        if not response.content:
            return None
        return response.json()

    # ------------------------------------------------------------------ scopes

    def scope_id(self) -> str:
        """Return the configured scope, falling back to the server default."""

        if self.settings.powercontext_scope_id:
            return self.settings.powercontext_scope_id
        if self._scope_id:
            return self._scope_id
        payload = self._request("GET", "/v1/scopes/default")
        self._scope_id = payload["scope_id"]
        return self._scope_id

    def health(self) -> dict[str, Any]:
        try:
            payload = self._request("GET", "/v1/scopes/default")
        except PowerContextUnavailableError as error:
            return {"available": False, "url": self.settings.powercontext_url, "error": str(error)}
        return {"available": True, "url": self.settings.powercontext_url, "scope_id": payload["scope_id"]}

    # ------------------------------------------------------------------ writes

    def create_task(self, task_id: str, description: str, *, in_scope: list[str], criteria: list[str]) -> dict[str, Any]:
        """Record the task contract and its description."""

        scope_id = self.scope_id()
        contract = {
            "schema": "powercontext.work-contract.v1",
            "trust": "untrusted_input",
            "objective": description,
            "facts": [{"text": description, "basis": "declared", "evidence": []}],
            "in_scope": in_scope or [task_id],
            "exclusions": [],
            "completion_criteria": criteria or [description],
            "authorization_notes": [],
            "open_questions": [],
        }
        receipt = self._request(
            "POST",
            "/v1/work/contracts/create",
            {
                "scope_id": scope_id,
                "source_id": f"sdd-contract-{task_id}",
                "contract": contract,
            },
        )
        self.remember(task_id, KIND_TASK_DESCRIPTION, description)
        return {
            "task_id": task_id,
            "scope_id": scope_id,
            "contract_source_id": receipt.get("source", {}).get("source_id"),
            "contract_digest": receipt.get("content_digest"),
        }

    def remember(self, task_id: str, kind: str, text: str) -> dict[str, Any]:
        """Store one state record for a task."""

        payload = self._request(
            "POST",
            "/v1/memory/remember",
            {"scope_id": self.scope_id(), "kind": kind, "text": f"{_prefix(task_id)} {text}"},
        )
        records = payload.get("records") or []
        return {
            "artifact_id": records[0].get("artifact", {}).get("artifact_id") if records else None,
            "revision": records[0].get("artifact", {}).get("revision") if records else None,
            "kind": kind,
        }

    def record_completed(self, task_id: str, item: str) -> dict[str, Any]:
        return self.remember(task_id, KIND_COMPLETED, item)

    def record_todo(self, task_id: str, item: str) -> dict[str, Any]:
        return self.remember(task_id, KIND_TODO, item)

    def record_verification(self, task_id: str, result: str) -> dict[str, Any]:
        return self.remember(task_id, KIND_VERIFICATION, result)

    def record_outcome(
        self,
        task_id: str,
        *,
        status: str,
        summary: str,
        checks: list[dict[str, Any]],
        remaining_work: list[str],
    ) -> dict[str, Any]:
        """Record the verification outcome through the official work-outcome API."""

        outcome = {
            "schema": "powercontext.task-outcome.v1",
            "trust": "untrusted_observation",
            "objective": summary,
            "status": status,
            "summary": summary,
            "observations": [{"text": summary, "basis": "declared", "evidence": []}],
            "checks": checks
            or [{"name": "verification", "status": "unknown", "details": summary, "basis": "declared", "evidence": []}],
            "produced_artifacts": [],
            "remaining_work": remaining_work,
        }
        receipt = self._request(
            "POST",
            "/v1/work/outcomes/record",
            {
                "scope_id": self.scope_id(),
                "source_id": f"sdd-outcome-{task_id}",
                "outcome": outcome,
            },
        )
        return {
            "task_id": task_id,
            "outcome_source_id": receipt.get("source", {}).get("source_id"),
            "outcome_digest": receipt.get("content_digest"),
        }

    # ------------------------------------------------------------------- reads

    def list_entries(self, kind: str | None = None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            payload: dict[str, Any] = {"scope_id": self.scope_id(), "limit": 100}
            if cursor:
                payload["cursor"] = cursor
            body = self._request("POST", "/v1/memory/entries/list", payload)
            entries.extend(body.get("entries") or [])
            cursor = body.get("next_cursor")
            if not cursor:
                break
        if kind is None:
            return entries
        return [entry for entry in entries if entry.get("kind") == kind]

    def load_task_state(self, task_id: str) -> dict[str, Any]:
        """Read back every state record that belongs to ``task_id``."""

        state: dict[str, Any] = {
            "task_id": task_id,
            "scope_id": self.scope_id(),
            "description": None,
            "completed": [],
            "todos": [],
            "verifications": [],
            "artifact_ids": {},
        }
        marker = _prefix(task_id)
        for entry in self.list_entries():
            kind = entry.get("kind")
            if kind not in _STATE_KINDS:
                continue
            text = str(entry.get("text") or "")
            if not text.startswith(marker):
                continue
            body = text[len(marker) :].strip()
            state["artifact_ids"][kind] = entry.get("artifact", {}).get("artifact_id")
            if kind == KIND_TASK_DESCRIPTION:
                state["description"] = body
            elif kind == KIND_COMPLETED:
                state["completed"].append(body)
            elif kind == KIND_TODO:
                state["todos"].append(body)
            elif kind == KIND_VERIFICATION:
                state["verifications"].append(body)
        state["has_state"] = bool(
            state["description"] or state["completed"] or state["todos"] or state["verifications"]
        )
        return state

    def list_tasks(self) -> list[str]:
        """Return every task id that has at least one persisted state record."""

        markers: dict[str, bool] = {}
        for entry in self.list_entries():
            if entry.get("kind") not in _STATE_KINDS:
                continue
            text = str(entry.get("text") or "")
            if not text.startswith("["):
                continue
            closing = text.find("]")
            if closing < 0:
                continue
            markers[text[1:closing]] = True
        return sorted(markers)

    def dump_json(self, payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
